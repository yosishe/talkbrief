"""Transcript stage: json3 captions → timed segments; optional faster-whisper ASR.

json3 is requested (not vtt/srt) because it keeps per-cue timing that survives into
quote anchoring. Caption provenance (manual/auto) rides along from fetch — a manual
track and an auto track are different artifacts and are never treated as equals.

ASR (the `[asr]` extra) uses faster-whisper with `hotwords` seeded from the video
title+channel: feeding metadata hints measured a 0/14 → 14/14 fix on proper nouns
in a prior pipeline.
"""

from __future__ import annotations

import logging

from .config import RunConfig
from .rundir import RunDir
from .schemas import validate
from .util import read_json, write_json

log = logging.getLogger("talkbrief")

_GAP_WINDOW_S = 60.0
_MAX_OK_GAP_S = 600.0


def flatten_json3(raw: dict) -> list[dict]:
    segments: list[dict] = []
    for ev in raw.get("events") or []:
        t0 = ev.get("tStartMs")
        if t0 is None:
            continue
        text = "".join(s.get("utf8", "") for s in (ev.get("segs") or []))
        text = " ".join(text.split())
        if not text:
            continue
        start = t0 / 1000.0
        end = start + (ev.get("dDurationMs") or 0) / 1000.0
        if segments and text == segments[-1]["text"] and start < segments[-1]["end"] + 0.01:
            segments[-1]["end"] = max(segments[-1]["end"], end)
            continue
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return segments


def coverage_report(segments: list[dict], duration_s: float) -> dict:
    if not segments:
        return {
            "ok": False,
            "spoken_fraction": 0.0,
            "largest_internal_gap_seconds": duration_s,
            "gaps": [],
        }
    duration = duration_s or segments[-1]["end"]
    full_windows = int(duration // _GAP_WINDOW_S)  # a trailing partial window doesn't count
    covered = 0
    for w in range(full_windows):
        lo, hi = w * _GAP_WINDOW_S, (w + 1) * _GAP_WINDOW_S
        if any(s["start"] < hi and s["end"] > lo for s in segments):
            covered += 1
    spoken = covered / full_windows if full_windows else 1.0
    gaps = []
    largest = 0.0
    for a, b in zip(segments, segments[1:], strict=False):
        gap = b["start"] - a["end"]
        largest = max(largest, gap)
        if gap > _GAP_WINDOW_S:
            gaps.append({"start_s": round(a["end"], 3), "end_s": round(b["start"], 3)})
    return {
        "ok": spoken >= 0.5 and largest <= _MAX_OK_GAP_S,
        "spoken_fraction": round(spoken, 3),
        "largest_internal_gap_seconds": round(largest, 3),
        "gaps": gaps,
    }


def asr_transcribe(rd: RunDir, meta: dict, cfg: RunConfig) -> tuple[list[dict], str | None]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "ASR requested but faster-whisper is not installed — pip install 'talkbrief[asr]'"
        ) from e
    media = rd.root / meta["media_file"]
    hotwords = " ".join(x for x in (meta.get("title"), meta.get("channel")) if x)[:200]
    log.info("asr: faster-whisper %s (hotwords from metadata)", cfg.asr_model)
    model = WhisperModel(cfg.asr_model, device="auto", compute_type="auto")
    seg_iter, info = model.transcribe(str(media), vad_filter=True, hotwords=hotwords or None)
    segments = [
        {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()}
        for s in seg_iter
        if s.text.strip()
    ]
    return segments, getattr(info, "language", None)


def run_transcript(rd: RunDir, meta: dict, cfg: RunConfig) -> dict:
    prov = dict(meta.get("caption_provenance") or {"kind": "none", "track": None})
    prov.setdefault("cue_count", None)
    prov.setdefault("asr_model", None)
    caption_files = sorted(rd.captions_dir.glob("cap.*.json3"))

    use_asr = cfg.asr == "force" or (cfg.asr == "auto" and not caption_files)
    if use_asr:
        segments, lang = asr_transcribe(rd, meta, cfg)
        source = "asr"
        prov = {"kind": "asr", "track": None, "cue_count": len(segments), "asr_model": cfg.asr_model}
    elif caption_files:
        segments = flatten_json3(read_json(caption_files[0]))
        source = "captions"
        lang = (prov.get("track") or "").split("-")[0] or None
        prov["cue_count"] = len(segments)
    else:
        segments, source, lang = [], "none", None

    prov.pop("file", None)
    doc = {
        "schema_version": 1,
        "language": lang,
        "source": source,
        "provenance": prov,
        "segments": segments,
        "coverage": coverage_report(segments, meta.get("duration_s") or 0.0),
    }
    validate("transcript", doc)
    write_json(rd.transcript_path, doc)
    cov = doc["coverage"]
    log.info(
        "transcript: %s (%s), %d segments, %.0f%% of minutes spoken",
        source, prov["kind"], len(segments), cov["spoken_fraction"] * 100,
    )
    if not cov["ok"] and segments:
        log.warning(
            "transcript coverage looks poor (largest gap %.0fs) — the brief may miss material",
            cov["largest_internal_gap_seconds"],
        )
    return doc
