"""Synthesis stage: one map call per window, one reduce call over the whole talk.

Design principles, each earned by a measured failure in a prior pipeline:

- The model NEVER writes a timestamp. It writes verbatim quotes; verify.py stamps the
  time (2 of 4 hand-written prose timestamps once pointed at the wrong moment).
- The transcript INPUT is never chunked below window level; it is the OUTPUT that is
  split across windows (sources over ~4,500 words collapsed to 42–76% coverage in a
  single call; output segmentation fixed them to 111–150%).
- Slides are routed by text density: text-rich slides go as OCR text (measured 24×
  token reduction), visual/diagram/code slides go as image files the model Reads.
  Code slides are ALWAYS images — OCR destroys indentation.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from .config import RunConfig
from .llm import LLMBackend, LLMRequest
from .rundir import RunDir
from .schemas import MAP_OUTPUT, REDUCE_OUTPUT, validate
from .util import hms, read_json, write_json

log = logging.getLogger("talkbrief")

_CODE_LINE_RE = re.compile(r"^(?:\s{2,}\S|def |class |import |func |const |let |var |#include|for\s*\(|if\s*\()")
_SYMBOLS = set("{}();=<>[]|&")


def code_like(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    code_lines = sum(1 for ln in lines if _CODE_LINE_RE.match(ln))
    symbol_frac = sum(1 for c in text if c in _SYMBOLS) / max(1, len(text))
    return code_lines / len(lines) > 0.25 or symbol_frac > 0.05


def route_slide(slide: dict, cfg: RunConfig) -> str:
    """'text' | 'image'. Empty/weak OCR routes to the image channel — costlier, not
    worse (this is also what makes non-Latin slides safe when OCR can't read them)."""
    if slide["ocr_chars"] >= cfg.min_ocr_chars_for_text_route and not code_like(slide["ocr_text"]):
        return "text"
    return "image"


def _spans_str(slide: dict) -> str:
    return ", ".join(f"{hms(sp['start_s'])}–{hms(sp['end_s'])}" for sp in slide["on_screen"])


def transcript_slice(segments: list[dict], lo: float, hi: float, *, stamps: bool = True) -> str:
    """Merge segments into readable ~22-word lines, each prefixed with its start time."""
    lines: list[str] = []
    buf: list[str] = []
    buf_start: float | None = None
    for s in segments:
        if s["end"] <= lo or s["start"] >= hi:
            continue
        if buf_start is None:
            buf_start = s["start"]
        buf.append(s["text"])
        if sum(len(t.split()) for t in buf) >= 22:
            prefix = f"[{hms(buf_start)}] " if stamps else ""
            lines.append(prefix + " ".join(buf))
            buf, buf_start = [], None
    if buf:
        prefix = f"[{hms(buf_start or lo)}] " if stamps else ""
        lines.append(prefix + " ".join(buf))
    return "\n".join(lines)


def _rules(lang: str) -> str:
    base = (
        "RULES:\n"
        "- Use ONLY the transcript slice and the slides given here. Do not invent.\n"
        "- NEVER write a timestamp. To support a point, copy a VERBATIM quote of at least 4\n"
        "  consecutive words from the transcript into \"quote\" — code will locate it and stamp\n"
        "  the time. If nothing quotable supports a point, set \"quote\" to null.\n"
        "- Copy numbers digit-for-digit. Never round, never convert units.\n"
        "- \"what_it_shows\" describes the visual itself; \"speaker_points\" is what the speaker\n"
        "  actually said while it was up; \"significance\" is the slide's role in the talk's\n"
        "  argument; \"not_said_aloud\" is information visible on the slide that the speaker\n"
        "  did NOT say out loud (use null only when there is none).\n"
        "- If the transcript mangles a proper noun that is printed on a slide, prefer the\n"
        "  slide's spelling.\n"
    )
    if lang == "he":
        base += (
            "- Write all prose fields in HEBREW. Keep technical terms, tool names, model names\n"
            "  and code in their original English/Latin form inside the Hebrew text. The \"quote\"\n"
            "  fields stay VERBATIM in the talk's original language — never translate a quote.\n"
        )
    else:
        base += "- Write in clear, information-dense English prose.\n"
    return base


def build_map_prompt(
    window: dict, slides_by_id: dict, segments: list[dict], meta: dict,
    outline: str, routing: dict[str, str], lang: str,
) -> tuple[str, list[str]]:
    parts: list[str] = []
    images: list[str] = []
    any_images = any(routing[sid] == "image" for sid in window["primary_slide_ids"])
    if any_images:
        parts.append(
            "First, use the Read tool to read EVERY image file listed under SLIDES below. "
            "Only after you have looked at all of them, write the JSON reply.\n"
        )
    title = f"TALK: {meta.get('title', '')} — {meta.get('channel') or ''}".strip(" —")
    chapter = f" — chapter: {window['chapter_title']}" if window.get("chapter_title") else ""
    parts.append(title)
    parts.append(f"WINDOW {window['id']} ({hms(window['start_s'])}–{hms(window['end_s'])}){chapter}")
    parts.append(f"TALK OUTLINE (you are writing only your window):\n{outline}")
    parts.append(_rules(lang))

    if window["primary_slide_ids"]:
        parts.append("SLIDES IN THIS WINDOW (cover each exactly once, in order):")
        for sid in window["primary_slide_ids"]:
            s = slides_by_id[sid]
            if routing[sid] == "text":
                parts.append(
                    f"SLIDE {sid} (on screen {_spans_str(s)}) — OCR TEXT:\n{s['ocr_text']}\nEND SLIDE"
                )
            else:
                images.append(f"slides/{s['file']}")
                parts.append(
                    f"SLIDE {sid} (on screen {_spans_str(s)}) — IMAGE FILE: slides/{s['file']}"
                    " — Read this file to see it."
                )
    else:
        parts.append(
            "SLIDES IN THIS WINDOW: none. Return an empty \"slides\" array and put the "
            "window's substance into \"window_points\" and \"window_summary\"."
        )
    if window["context_slide_ids"]:
        ctx = []
        for sid in window["context_slide_ids"]:
            first_line = (slides_by_id[sid]["ocr_text"].splitlines() or [""])[0][:80]
            ctx.append(f"{sid}: {first_line!r}")
        parts.append(
            "CONTEXT SLIDES (also on screen here, but covered by another window — for "
            "orientation only, do NOT write entries for them):\n" + "\n".join(ctx)
        )

    parts.append("TRANSCRIPT SLICE:")
    slice_text = transcript_slice(segments, window["start_s"], window["end_s"])
    parts.append(slice_text if slice_text else "(no transcript available for this window)")
    parts.append(
        f'Reply with ONLY the JSON object. "window_id" must be "{window["id"]}".'
    )
    return "\n\n".join(parts), images


def build_reduce_prompt(
    maps: dict[str, dict], segments: list[dict], meta: dict, windows: list[dict], lang: str
) -> str:
    parts = [
        f"TALK: {meta.get('title', '')} — {meta.get('channel') or ''}",
        "You are writing the OVERVIEW layer of a grounded brief: the whole-talk narrative.",
        _rules(lang),
    ]
    chapters = meta.get("chapters") or []
    if len(chapters) >= 2:
        parts.append(
            "The video declares these chapters — use these exact titles, in order, one entry "
            "each, and for every chapter pick a verbatim quote spoken NEAR ITS START (code "
            "stamps the time from the quote):\n"
            + "\n".join(f"- {c['title']}" for c in chapters)
        )
    else:
        parts.append(
            "The video declares no chapters. Propose 4–10 chapters of your own; for each, "
            "pick a verbatim quote spoken near where it begins."
        )
    parts.append(
        "WINDOW SUMMARIES (already written by the per-window pass):\n"
        + "\n".join(f"{wid}: {m['window_summary']}" for wid, m in sorted(maps.items()))
    )
    parts.append("FULL TRANSCRIPT:")
    end = windows[-1]["end_s"] if windows else float(meta.get("duration_s") or 0)
    parts.append(transcript_slice(segments, 0.0, end + 1.0, stamps=False) or "(none)")
    parts.append("Reply with ONLY the JSON object.")
    return "\n\n".join(parts)


def _persist_call(rd: RunDir, label: str, prompt: str, images: list[str], result) -> None:
    write_json(rd.calls_dir / f"{label}_request.json",
               {"prompt": prompt, "images": images})
    write_json(rd.calls_dir / f"{label}_response.json",
               {"data": result.data, "cost_usd": result.cost_usd,
                "duration_s": result.duration_s, "raw": result.raw})


def run_synthesize(rd: RunDir, meta: dict, cfg: RunConfig, backend: LLMBackend) -> dict:
    transcript = read_json(rd.transcript_path)
    slides_doc = read_json(rd.slides_json)
    alignment = read_json(rd.alignment_path)
    segments = transcript["segments"]
    windows = alignment["windows"]
    slides_by_id = {s["id"]: s for s in slides_doc["slides"]}

    routing = {sid: route_slide(s, cfg) for sid, s in slides_by_id.items()}
    # image budget: per call, largest-on-screen image slides win; overflow falls back
    for w in windows:
        image_ids = [sid for sid in w["primary_slide_ids"] if routing[sid] == "image"]
        if len(image_ids) > cfg.max_images:
            image_ids.sort(key=lambda sid: slides_by_id[sid]["on_screen_total_s"], reverse=True)
            for sid in image_ids[cfg.max_images:]:
                routing[sid] = "text"  # weak OCR text beats not being seen at all
            log.warning(
                "%s: %d image slides over the %d budget — overflow sent as OCR text",
                w["id"], len(image_ids) - cfg.max_images, cfg.max_images,
            )

    outline = "\n".join(
        f"{w['id']} [{hms(w['start_s'])}] {w['chapter_title'] or ''}".rstrip()
        for w in windows
    )

    def do_map(window: dict) -> tuple[str, dict]:
        prompt, images = build_map_prompt(
            window, slides_by_id, segments, meta, outline, routing, cfg.lang
        )
        req = LLMRequest(
            prompt=prompt, schema=MAP_OUTPUT, workdir=rd.root, image_paths=images,
            model=cfg.model, max_budget_usd=cfg.max_budget_usd,
            timeout_s=cfg.llm_timeout_s, label=f"map_{window['id']}",
        )
        result = backend.generate_json(req)
        _persist_call(rd, req.label, prompt, images, result)
        log.info("synthesize: %s done (%d slides)", window["id"], len(result.data["slides"]))
        return window["id"], result

    results: dict[str, dict] = {}
    costs: list[float] = []
    with ThreadPoolExecutor(max_workers=cfg.concurrency) as pool:
        for wid, result in pool.map(do_map, windows):
            results[wid] = result.data
            if result.cost_usd is not None:
                costs.append(result.cost_usd)

    reduce_prompt = build_reduce_prompt(results, segments, meta, windows, cfg.lang)
    reduce_req = LLMRequest(
        prompt=reduce_prompt, schema=REDUCE_OUTPUT, workdir=rd.root,
        model=cfg.model, max_budget_usd=cfg.max_budget_usd,
        timeout_s=cfg.llm_timeout_s, label="reduce",
    )
    reduce_result = backend.generate_json(reduce_req)
    _persist_call(rd, "reduce", reduce_prompt, [], reduce_result)
    if reduce_result.cost_usd is not None:
        costs.append(reduce_result.cost_usd)

    slide_entries: list[dict] = []
    mapped: dict[str, dict] = {}
    for out in results.values():
        for entry in out["slides"]:
            mapped[entry["slide_id"]] = entry
    for s in slides_doc["slides"]:
        if s["id"] in mapped:
            slide_entries.append(mapped[s["id"]])
        else:
            log.warning("synthesize: model skipped %s — placeholder entry", s["id"])
            first_line = (s["ocr_text"].splitlines() or [""])[0]
            slide_entries.append({
                "slide_id": s["id"],
                "heading": first_line or f"Slide {s['index']}",
                "what_it_shows": "",
                "speaker_points": [],
                "significance": "",
                "not_said_aloud": None,
            })

    digest = {
        "schema_version": 1,
        "lang": cfg.lang,
        "video": {
            "id": meta["id"],
            "url": meta.get("url", ""),
            "title": meta.get("title", ""),
            "channel": meta.get("channel"),
            "duration_s": meta.get("duration_s") or 0.0,
        },
        "overview": reduce_result.data,
        "slides": slide_entries,
        "windows": [
            {"id": wid, "summary": results[wid]["window_summary"],
             "points": results[wid]["window_points"]}
            for wid in sorted(results)
        ],
        "model": {
            "backend": backend.name,
            "model": cfg.model,
            "calls": len(windows) + 1,
            "cost_usd": round(sum(costs), 4) if costs else None,
        },
    }
    validate("digest", digest)
    write_json(rd.digest_path, digest)
    log.info(
        "synthesize: %d windows + reduce, cost %s",
        len(windows), f"${sum(costs):.2f}" if costs else "n/a",
    )
    return digest
