"""Align stage: cut the talk into windows and assign slides to them.

Windows follow the video's own chapters when it has them; otherwise ~target_words
blocks cut at segment boundaries. Each slide is written about exactly once — by the
window with the largest on-screen overlap (`primary`); windows it merely brushes list
it as `context`. Each synthesis call later sees ONLY its window's transcript slice and
its window's slides.
"""

from __future__ import annotations

import logging
import math

from .config import RunConfig
from .rundir import RunDir
from .schemas import validate
from .util import read_json, write_json

log = logging.getLogger("talkbrief")

_FALLBACK_WINDOW_S = 300.0
_MIN_CONTEXT_OVERLAP_S = 8.0


def _words_in(segments: list[dict], lo: float, hi: float) -> int:
    return sum(len(s["text"].split()) for s in segments if s["start"] < hi and s["end"] > lo)


def _split_points(segments: list[dict], lo: float, hi: float, parts: int) -> list[float]:
    """Cut [lo,hi) into `parts` word-balanced pieces at segment boundaries."""
    inside = [s for s in segments if lo <= s["start"] < hi]
    total = sum(len(s["text"].split()) for s in inside)
    if total == 0 or parts <= 1:
        return []
    cuts: list[float] = []
    acc, next_cut = 0, total / parts
    for s in inside:
        acc += len(s["text"].split())
        if acc >= next_cut and len(cuts) < parts - 1:
            cuts.append(s["end"])
            next_cut += total / parts
    return cuts


def build_windows(
    segments: list[dict], chapters: list[dict], duration_s: float, target_words: int
) -> list[dict]:
    end_of_talk = max(
        duration_s,
        segments[-1]["end"] if segments else 0.0,
        chapters[-1]["end_s"] if chapters else 0.0,
    )
    spans: list[tuple[float, float, str | None]] = []

    if len(chapters) >= 2:
        for i, c in enumerate(chapters):
            end = c["end_s"] or (chapters[i + 1]["start_s"] if i + 1 < len(chapters) else end_of_talk)
            spans.append((c["start_s"], end, c["title"] or None))
        if spans and spans[-1][1] < end_of_talk:
            lo, _hi, title = spans[-1]
            spans[-1] = (lo, end_of_talk, title)
    elif segments:
        lo, words = 0.0, 0
        for s in segments:
            words += len(s["text"].split())
            if words >= target_words:
                spans.append((lo, s["end"], None))
                lo, words = s["end"], 0
        if lo < end_of_talk - 0.001:  # no empty trailing window
            spans.append((lo, end_of_talk, None))
        elif spans:
            spans[-1] = (spans[-1][0], end_of_talk, spans[-1][2])
        else:
            spans.append((0.0, end_of_talk, None))
    else:
        n = max(1, math.ceil(end_of_talk / _FALLBACK_WINDOW_S))
        spans = [
            (i * end_of_talk / n, (i + 1) * end_of_talk / n, None) for i in range(n)
        ]

    # a chapter far above target still gets split — the output ceiling is real
    final: list[tuple[float, float, str | None]] = []
    for lo, hi, title in spans:
        words = _words_in(segments, lo, hi)
        if words > 1.6 * target_words:
            cuts = _split_points(segments, lo, hi, math.ceil(words / target_words))
            edges = [lo, *cuts, hi]
            for j in range(len(edges) - 1):
                part_title = f"{title} ({j + 1})" if title else None
                final.append((edges[j], edges[j + 1], part_title))
        else:
            final.append((lo, hi, title))

    return [
        {
            "id": f"w{i:02d}",
            "start_s": round(lo, 3),
            "end_s": round(hi, 3),
            "chapter_title": title,
            "word_count": _words_in(segments, lo, hi),
            "primary_slide_ids": [],
            "context_slide_ids": [],
        }
        for i, (lo, hi, title) in enumerate(final, start=1)
    ]


def assign_slides(windows: list[dict], slides: list[dict]) -> None:
    for slide in slides:
        overlap: dict[str, float] = {}
        for w in windows:
            overlap[w["id"]] = sum(
                max(0.0, min(sp["end_s"], w["end_s"]) - max(sp["start_s"], w["start_s"]))
                for sp in slide["on_screen"]
            )
        best_id, best_ov = None, -1.0
        for w in windows:  # strict > keeps the EARLIEST window on ties
            if overlap[w["id"]] > best_ov:
                best_id, best_ov = w["id"], overlap[w["id"]]
        if best_ov <= 0:
            # a slide that overlaps no window (edge rounding) goes to the nearest one
            best_id = min(
                windows,
                key=lambda w: abs(slide["first_seen_s"] - (w["start_s"] + w["end_s"]) / 2),
            )["id"]
        floor = max(_MIN_CONTEXT_OVERLAP_S, 0.15 * slide["on_screen_total_s"])
        for w in windows:
            if w["id"] == best_id:
                w["primary_slide_ids"].append(slide["id"])
            elif overlap[w["id"]] >= floor:
                w["context_slide_ids"].append(slide["id"])

    order = {s["id"]: s["first_seen_s"] for s in slides}
    for w in windows:
        w["primary_slide_ids"].sort(key=lambda sid: order[sid])
        w["context_slide_ids"].sort(key=lambda sid: order[sid])


def run_align(rd: RunDir, meta: dict, cfg: RunConfig) -> dict:
    transcript = read_json(rd.transcript_path)
    slides_doc = read_json(rd.slides_json)
    windows = build_windows(
        transcript["segments"],
        meta.get("chapters") or [],
        meta.get("duration_s") or 0.0,
        cfg.target_window_words,
    )
    assign_slides(windows, slides_doc["slides"])
    doc = {"schema_version": 1, "windows": windows}
    validate("alignment", doc)
    write_json(rd.alignment_path, doc)
    log.info(
        "align: %d windows (%s), %d slides assigned",
        len(windows),
        "chapters" if len(meta.get("chapters") or []) >= 2 else "word-blocks",
        len(slides_doc["slides"]),
    )
    return doc
