"""Fetch stage: yt-dlp metadata, caption track (json3, keeps per-cue timing), ≤720p media.

Notes that carry measurements:
- Media is capped at 720p — 1080p measured ~2.8× the bytes for no OCR gain on slides.
- `-N 8` concurrent fragments measured ≈14× download speedup on this class of video.
- Current yt-dlp needs an external JS runtime (deno) for YouTube; `doctor` checks it.
- Caption provenance (manual/auto/none) is recorded because manual and auto tracks are
  different artifacts and must never be compared as equals.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from pathlib import Path

from .config import RunConfig
from .rundir import FAILED_FINAL, FAILED_RETRYABLE, RunDir
from .util import run_cmd, write_json

log = logging.getLogger("talkbrief")

_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})")

_FINAL_ERROR_PATTERNS = (
    "Private video",
    "Video unavailable",
    "members-only",
    "has been removed",
    "account associated with this video has been terminated",
    "confirm your age",
    "not available in your country",
)


class FetchError(RuntimeError):
    def __init__(self, message: str, error_class: str = FAILED_RETRYABLE):
        super().__init__(message)
        self.error_class = error_class


def classify_ytdlp_error(stderr: str) -> str:
    return (
        FAILED_FINAL
        if any(p.lower() in stderr.lower() for p in _FINAL_ERROR_PATTERNS)
        else FAILED_RETRYABLE
    )


def extract_video_id(url: str) -> str | None:
    m = _VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def _ytdlp(cfg: RunConfig) -> list[str]:
    # prefer a yt-dlp binary on PATH (often fresher than the pip pin); the pip
    # dependency guarantees the module fallback always exists
    base = ["yt-dlp"] if shutil.which("yt-dlp") else [sys.executable, "-m", "yt_dlp"]
    cmd = [*base, "--no-playlist"]
    if cfg.cookies_from:
        cmd += ["--cookies-from-browser", cfg.cookies_from]
    return cmd


def fetch_info(url: str, cfg: RunConfig) -> dict:
    """`yt-dlp -J` with a player-client retry ladder (extractor churn is weekly-scale)."""
    ladders: list[list[str]] = [
        [],
        ["--extractor-args", "youtube:player_client=web_safari"],
        ["--extractor-args", "youtube:player_client=tv"],
    ]
    last_err = ""
    for extra in ladders:
        res = run_cmd(_ytdlp(cfg) + extra + ["-J", url], timeout=180)
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout)
        last_err = res.stderr
        if classify_ytdlp_error(last_err) == FAILED_FINAL:
            break
    raise FetchError(
        f"yt-dlp metadata failed: {last_err[-500:]}", classify_ytdlp_error(last_err)
    )


def pick_caption_track(info: dict, preferred: tuple[str, ...]) -> tuple[str | None, str]:
    """Return (track_lang, kind) with kind in manual|auto|none.

    Preference order: manual in a preferred language (exact, then regional variant),
    manual in the video's own language, auto in a preferred language, auto original.
    """
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    def _match(tracks: dict, lang: str) -> str | None:
        if lang in tracks:
            return lang
        for cand in sorted(tracks):
            if cand.startswith(lang + "-"):
                return cand
        return None

    for lang in preferred:
        if t := _match(manual, lang):
            return t, "manual"
    if (orig := info.get("language")) and (t := _match(manual, orig)):
        return t, "manual"
    for lang in preferred:
        if t := _match(auto, lang):
            return t, "auto"
    if (orig := info.get("language")) and (t := _match(auto, orig)):
        return t, "auto"
    # `-orig` auto tracks (e.g. "en-orig") are the untranslated ASR track
    for cand in sorted(auto):
        if cand.endswith("-orig"):
            return cand, "auto"
    return None, "none"


def distill_meta(info: dict, url: str) -> dict:
    chapters = [
        {
            "title": c.get("title") or "",
            "start_s": float(c.get("start_time") or 0.0),
            "end_s": float(c.get("end_time") or 0.0),
        }
        for c in (info.get("chapters") or [])
    ]
    return {
        "id": info["id"],
        "url": info.get("webpage_url") or url,
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader"),
        "duration_s": float(info.get("duration") or 0.0),
        "upload_date": info.get("upload_date"),
        "language": info.get("language"),
        "description": (info.get("description") or "")[:2000],
        "chapters": chapters,
        "captions": {
            "manual": sorted((info.get("subtitles") or {}).keys()),
            "auto": sorted((info.get("automatic_captions") or {}).keys()),
        },
    }


def download_captions(url: str, cfg: RunConfig, rd: RunDir, info: dict) -> dict:
    """Download the chosen track as json3; return provenance."""
    track, kind = pick_caption_track(info, cfg.caption_langs)
    provenance = {"kind": kind, "track": track, "cue_count": None, "asr_model": None}
    if track is None:
        log.info("captions: none available")
        return provenance
    res = run_cmd(
        _ytdlp(cfg)
        + [
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", track,
            "--sub-format", "json3",
            "-P", str(rd.captions_dir),
            "-o", "cap",
            url,
        ],
        timeout=300,
    )
    files = sorted(rd.captions_dir.glob("cap.*.json3"))
    if res.returncode != 0 or not files:
        log.warning("captions: download failed for track %s (%s)", track, res.stderr[-200:])
        return {"kind": "none", "track": None, "cue_count": None, "asr_model": None}
    provenance["file"] = files[0].name
    log.info("captions: %s track %r -> %s", kind, track, files[0].name)
    return provenance


def download_media(url: str, cfg: RunConfig, rd: RunDir) -> Path:
    res = run_cmd(
        _ytdlp(cfg)
        + [
            "-f", "bv*[height<=720]+ba/b[height<=720]/b",
            "--merge-output-format", "mp4",
            "-N", "8",
            "-P", str(rd.media_dir),
            "-o", "video.%(ext)s",
            url,
        ],
        timeout=3600,
    )
    files = [p for p in rd.media_dir.glob("video.*") if p.suffix != ".part"]
    if res.returncode != 0 or not files:
        raise FetchError(
            f"yt-dlp media download failed: {res.stderr[-500:]}",
            classify_ytdlp_error(res.stderr),
        )
    return files[0]


def run_fetch(url: str, cfg: RunConfig, rd: RunDir | None = None) -> tuple[RunDir, dict]:
    """Full fetch stage. Returns (run_dir, meta)."""
    info = fetch_info(url, cfg)
    if rd is None:
        rd = RunDir.create(cfg.outdir, info["id"], info.get("title") or "")
    rd.ensure()
    meta = distill_meta(info, url)
    meta["caption_provenance"] = download_captions(url, cfg, rd, info)
    media = download_media(url, cfg, rd)
    meta["media_file"] = f"media/{media.name}"
    write_json(rd.meta_path, meta)
    log.info("fetch: %s (%.0f min) -> %s", meta["title"], meta["duration_s"] / 60, rd.root)
    return rd, meta
