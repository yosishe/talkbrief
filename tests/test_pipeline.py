"""Offline end-to-end: fixture video + synthetic captions through EVERY stage after
fetch, with the FakeBackend standing in for the model. This is the test that proves
the stages actually compose — including the RTL Hebrew render."""

from __future__ import annotations

from talkbrief.align import run_align
from talkbrief.config import RunConfig
from talkbrief.llm.fake import FakeBackend
from talkbrief.render.html import render_report
from talkbrief.slides import run_slides
from talkbrief.synthesize import run_synthesize
from talkbrief.transcript import run_transcript
from talkbrief.util import read_json
from talkbrief.verify import run_verify


def _cfg(tmp_path, **kw) -> RunConfig:
    base = dict(
        outdir=tmp_path, interval=1.0, floor_seconds=45.0, backend="fake",
        target_window_words=120, concurrency=2,
    )
    base.update(kw)
    return RunConfig(**base)


def _through_verify(rd, meta, cfg):
    run_slides(rd, meta, cfg)
    run_transcript(rd, meta, cfg)
    run_align(rd, meta, cfg)
    run_synthesize(rd, meta, cfg, FakeBackend())
    return run_verify(rd, cfg)


def test_full_pipeline_offline(run_dir, tmp_path):
    rd, meta = run_dir
    cfg = _cfg(tmp_path)
    verified = _through_verify(rd, meta, cfg)

    transcript = read_json(rd.transcript_path)
    assert transcript["source"] == "captions"
    assert transcript["provenance"]["kind"] == "manual"
    assert len(transcript["segments"]) > 30

    alignment = read_json(rd.alignment_path)
    assert len(alignment["windows"]) >= 3

    ver = verified["verification"]
    assert ver["quotes_total"] >= 3
    assert ver["quotes_grounded"] == ver["quotes_total"], (
        "fake quotes are lifted verbatim from the transcript — all must ground"
    )
    stamped = [
        p for s in verified["slides"] for p in s["speaker_points"] if p.get("t") is not None
    ]
    assert stamped, "at least one speaker point must carry a stamped time"

    html_path = render_report(rd, meta, cfg)
    html = html_path.read_text(encoding="utf-8")
    assert html.count("slide-card") >= len(verified["slides"])
    assert "https://youtu.be/abcdefghijk?t=" in html
    assert "data:image/jpeg;base64," in html  # embed mode
    assert 'dir="ltr"' in html
    assert "✓" in html  # grounding badge


def test_hebrew_render_is_rtl(run_dir, tmp_path):
    rd, meta = run_dir
    cfg = _cfg(tmp_path, lang="he")
    _through_verify(rd, meta, cfg)
    html = render_report(rd, meta, cfg).read_text(encoding="utf-8")
    assert '<html lang="he" dir="rtl">' in html
    assert "מבט-על" in html            # Hebrew chrome strings
    assert "<bdi>" in html             # LTR runs isolated inside RTL prose
    assert "margin-inline-start" in html or "border-inline-start" in html


def test_transcript_only_mode_never_crashes(run_dir, tmp_path):
    """Speaker-only video simulation: empty slides doc → transcript-only brief."""
    from talkbrief.schemas import validate
    from talkbrief.util import write_json

    rd, meta = run_dir
    cfg = _cfg(tmp_path)
    slides_doc = {
        "schema_version": 1, "params": {}, "ocr": {"engines_used": {}, "vision_available": False},
        "slides": [], "stats": {},
    }
    validate("slides", slides_doc)
    write_json(rd.slides_json, slides_doc)
    run_transcript(rd, meta, cfg)
    run_align(rd, meta, cfg)
    run_synthesize(rd, meta, cfg, FakeBackend())
    run_verify(rd, cfg)
    html = render_report(rd, meta, cfg).read_text(encoding="utf-8")
    assert "transcript-only" in html or "מבוסס-תמליל" in html
