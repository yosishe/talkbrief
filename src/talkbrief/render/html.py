"""Render stage: one self-contained interactive HTML file (and optionally a PDF).

Embed policy (measured): raw extracted slides average ~163 KB; re-encoded at ≤1280px
q5 they land at ~80–120 KB, so a 40–60-slide talk embeds to a ~5–9 MB single file.
Above `embed_max_mb` the images fall back to a report/assets/ folder with a notice.
The report makes NO network requests — it must open from file:// offline.
"""

from __future__ import annotations

import base64
import logging
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import RunConfig
from ..i18n import STRINGS
from ..rundir import RunDir
from ..util import hms, read_json

log = logging.getLogger("talkbrief")

_TEMPLATES = Path(__file__).parent / "templates"


def _reencode(image: Path) -> bytes:
    """Downscale/recompress one slide for embedding (≤1280px wide, q5)."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-i", str(image),
         "-vf", "scale='min(1280,iw)':-2",
         "-q:v", "5", "-f", "mjpeg", "-"],
        capture_output=True, timeout=60,
    )
    if proc.returncode != 0 or not proc.stdout:
        return image.read_bytes()  # fall back to the original bytes
    return proc.stdout


def _prepare_images(
    rd: RunDir, slide_facts: list[dict], cfg: RunConfig
) -> tuple[dict[str, str], str]:
    """Return ({slide_id: src}, mode) where mode is 'embed' or 'assets'.
    Takes the slides.json facts (which carry `file`), not the digest entries."""
    blobs: dict[str, bytes] = {}
    for s in slide_facts:
        img = rd.slides_dir / s["file"]
        if img.exists():
            blobs[s["id"]] = _reencode(img)
    total_mb = sum(len(b) for b in blobs.values()) / 1e6
    embed = cfg.embed == "always" or (cfg.embed == "auto" and total_mb <= cfg.embed_max_mb)
    if embed:
        srcs = {
            sid: "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")
            for sid, b in blobs.items()
        }
        return srcs, "embed"
    assets = rd.report_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    srcs = {}
    for sid, b in blobs.items():
        name = f"{sid}.jpg"
        (assets / name).write_bytes(b)
        srcs[sid] = f"assets/{name}"
    log.info("render: images too large to embed (%.1f MB) — using assets/ folder", total_mb)
    return srcs, "assets"


def _transcript_lines(segments: list[dict], lo: float, hi: float) -> list[dict]:
    lines: list[dict] = []
    buf: list[str] = []
    start: float | None = None
    for s in segments:
        if s["end"] <= lo or s["start"] >= hi:
            continue
        if start is None:
            start = s["start"]
        buf.append(s["text"])
        if sum(len(t.split()) for t in buf) >= 22:
            lines.append({"t": hms(start), "text": " ".join(buf)})
            buf, start = [], None
    if buf:
        lines.append({"t": hms(start or lo), "text": " ".join(buf)})
    return lines


def _spans_label(on_screen: list[dict], max_shown: int = 3) -> str:
    labels = [f"{hms(sp['start_s'])}–{hms(sp['end_s'])}" for sp in on_screen]
    if len(labels) > max_shown:
        labels = labels[:max_shown] + [f"+{len(labels) - max_shown}"]
    return ", ".join(labels)


def _chip(point: dict, video_id: str) -> dict:
    quote = point.get("quote")
    t = point.get("t")
    url = f"https://youtu.be/{video_id}?t={int(t)}" if quote and t is not None else None
    short = (quote or "").strip()
    if len(short) > 90:
        short = short[:87].rstrip() + "…"
    return {
        "text": point.get("text") or point.get("one_liner") or "",
        "quote": short or None,
        "url": url,
        "grounded": bool(point.get("grounded")),
        "slide_sourced": point.get("match_source") == "slide",
    }


def render_report(rd: RunDir, meta: dict, cfg: RunConfig) -> Path:
    verified = read_json(rd.verified_path)
    slides_doc = read_json(rd.slides_json)
    alignment = read_json(rd.alignment_path)
    transcript = read_json(rd.transcript_path)
    segments = transcript["segments"]
    lang = verified.get("lang", cfg.lang)
    s = STRINGS.get(lang, STRINGS["en"])
    video = verified["video"]
    vid = video["id"]

    facts = {sd["id"]: sd for sd in slides_doc["slides"]}
    # only the slides the digest actually covers get rendered — and only those
    # are worth re-encoding/embedding (a screencast can have hundreds of keyframes)
    rendered_ids = {e["slide_id"] for e in verified["slides"]}
    srcs, embed_mode = _prepare_images(
        rd, [sd for sd in slides_doc["slides"] if sd["id"] in rendered_ids], cfg
    )

    window_of: dict[str, dict] = {}
    for w in alignment["windows"]:
        for sid in w["primary_slide_ids"]:
            window_of[sid] = w

    rslides = []
    for entry in verified["slides"]:
        sid = entry["slide_id"]
        fact = facts.get(sid)
        if fact is None:
            continue
        w = window_of.get(sid)
        rslides.append({
            "id": sid,
            "index": fact["index"],
            "img": srcs.get(sid),
            "heading": entry.get("heading") or f"Slide {fact['index']}",
            "what_it_shows": entry.get("what_it_shows") or "",
            "significance": entry.get("significance") or "",
            "not_said_aloud": entry.get("not_said_aloud"),
            "points": [_chip(p, vid) for p in entry.get("speaker_points", [])],
            "spans": _spans_label(fact["on_screen"]),
            "times_returned": fact["times_returned"],
            "watch_url": f"https://youtu.be/{vid}?t={int(fact['first_seen_s'])}",
            "first_seen_hms": fact["hms"],
            "transcript": _transcript_lines(segments, w["start_s"], w["end_s"]) if w else [],
        })

    ov = verified["overview"]
    chapters = []
    for c in ov.get("chapters", []):
        t = c.get("start_s")
        chapters.append({
            "title": c.get("title", ""),
            "one_liner": c.get("one_liner", ""),
            "hms": hms(t) if t is not None else None,
            "url": f"https://youtu.be/{vid}?t={int(t)}" if t is not None else None,
        })

    ver = verified.get("verification", {})
    recall = ver.get("token_recall")
    context = {
        "lang": lang,
        "dir": "rtl" if lang == "he" else "ltr",
        "s": s,
        "video": {
            "id": vid,
            "url": video.get("url") or f"https://youtu.be/{vid}",
            "title": video.get("title", ""),
            "channel": video.get("channel") or "",
            "duration_hms": hms(video.get("duration_s") or 0),
        },
        "tldr": ov.get("tldr", ""),
        "narrative": ov.get("narrative", []),
        "takeaways": [_chip(p, vid) for p in ov.get("key_takeaways", [])],
        "glossary": ov.get("glossary", []),
        "numbers": [_chip(p | {"text": p.get("item", "")}, vid) for p in ov.get("numbers_and_names", [])],
        "chapters": chapters,
        "slides": rslides,
        "windows": verified.get("windows", []),
        "transcript_only": len(rslides) == 0,
        "grounding": s["grounding"].format(
            grounded=ver.get("quotes_grounded", 0), total=ver.get("quotes_total", 0)
        ),
        "token_recall": (
            s["token_recall"].format(recall=f"{recall:.0%}") if recall is not None else None
        ),
        "model_line": f"{verified['model'].get('backend')}"
        + (f" · {verified['model'].get('model')}" if verified["model"].get("model") else ""),
        "embed_mode": embed_mode,
        "version": __import__("talkbrief").__version__,
    }

    env = Environment(
        loader=FileSystemLoader(_TEMPLATES),
        autoescape=select_autoescape(["html", "j2"]),
    )
    html = env.get_template("report.html.j2").render(**context)
    rd.report_dir.mkdir(parents=True, exist_ok=True)
    rd.report_html.write_text(html, encoding="utf-8")
    size_mb = rd.report_html.stat().st_size / 1e6
    log.info("render: %s (%.1f MB, %s mode)", rd.report_html, size_mb, embed_mode)
    return rd.report_html
