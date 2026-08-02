"""Detector tests: golden regression on the synthetic fixture + unit tests."""

from __future__ import annotations

import numpy as np

from talkbrief.config import RunConfig
from talkbrief.slides import (
    collapse_builds,
    dhash_bits,
    pick_keyframes,
    run_slides,
    union_floor,
)


def _cfg(tmp_path) -> RunConfig:
    return RunConfig(outdir=tmp_path, interval=1.0, floor_seconds=45.0)


def test_dhash_shapes_and_determinism():
    rng = np.random.default_rng(1)
    frames = rng.integers(0, 255, size=(4, 32, 32), dtype=np.uint8)
    bits = dhash_bits(frames)
    assert bits.shape == (4, 32, 31)
    assert (bits == dhash_bits(frames)).all()


def test_pick_keyframes_on_handbuilt_hashes():
    # 3 stable blocks A A A B B B A A → two candidates, A with two spans
    a = np.zeros((32, 31), dtype=bool)
    b = np.ones((32, 31), dtype=bool)
    bits = np.stack([a, a, a, b, b, b, a, a])
    kept = pick_keyframes(bits, threshold=0.08, stability=0.05)
    assert len(kept) == 2
    assert len(kept[0].spans) == 2  # A returned
    assert len(kept[1].spans) == 1


def test_unsettled_frames_never_become_candidates():
    rng = np.random.default_rng(2)
    bits = rng.random((10, 32, 31)) > 0.5  # every consecutive pair is far apart
    kept = pick_keyframes(bits, threshold=0.08, stability=0.05)
    assert kept == []


def test_union_floor_guarantee_long_slide_survives():
    """A ≥90 s slide invisible to the hash detector MUST still yield a candidate."""
    rng = np.random.default_rng(3)
    bits = rng.random((120, 32, 31)) > 0.5  # unstable everywhere → hash-blind
    kept = pick_keyframes(bits, threshold=0.08, stability=0.05)
    out = union_floor(kept, bits, interval=1.0, floor_seconds=45.0, stability=0.05)
    assert any(c.source == "floor" for c in out)
    assert len(out) >= 2  # ticks at 45 and 90


def test_union_floor_merges_identical_frames():
    a = np.zeros((32, 31), dtype=bool)
    bits = np.stack([a] * 100)
    kept = pick_keyframes(bits, threshold=0.08, stability=0.05)
    out = union_floor(kept, bits, interval=1.0, floor_seconds=45.0, stability=0.05)
    assert len(out) == 1  # floor ticks fold into the existing identical candidate


def _slide(sid, text, spans, first=None):
    return {
        "id": sid, "index": int(sid[1:]), "file": f"slide_{sid[1:]}.jpg",
        "first_seen_s": first if first is not None else spans[0][0],
        "hms": "00:00:00",
        "on_screen": [{"start_s": s, "end_s": e} for s, e in spans],
        "on_screen_total_s": 0.0, "times_returned": 0,
        "ocr_text": text, "ocr_chars": len(text), "ocr_engine": "none",
        "builds_collapsed": 0, "source": "hash",
    }


def test_collapse_builds_keeps_final_build():
    slides = [
        _slide("s001", "intro agenda first", [(0, 10)]),
        _slide("s002", "intro agenda first second", [(10, 20)]),
        _slide("s003", "intro agenda first second third point", [(20, 30)]),
    ]
    out = collapse_builds(slides)
    assert len(out) == 1
    final = out[0]
    assert "third" in final["ocr_text"]  # the FINAL build survives
    assert final["builds_collapsed"] == 2
    assert final["first_seen_s"] == 0
    assert final["on_screen_total_s"] == 30.0


def test_collapse_dedups_floor_duplicates():
    slides = [
        _slide("s001", "architecture diagram of the system pipeline", [(0, 50)]),
        _slide("s002", "totally different content here entirely", [(50, 60)]),
        _slide("s003", "architecture diagram of the system pipeline", [(60, 70)]),
    ]
    out = collapse_builds(slides)
    assert len(out) == 2
    merged = next(s for s in out if "architecture" in s["ocr_text"])
    assert merged["times_returned"] == 1  # two spans after merge


def test_golden_fixture_detection(run_dir, tmp_path):
    rd, meta = run_dir
    doc = run_slides(rd, meta, _cfg(tmp_path))
    slides = doc["slides"]
    # S1, S2, S4, S5 from the hash detector; the jitter slide only via the floor
    assert 5 <= len(slides) <= 7, [s["first_seen_s"] for s in slides]
    assert any(s["source"] == "floor" for s in slides), "union floor missed the jitter slide"
    s1 = slides[0]
    assert s1["first_seen_s"] <= 2.0
    assert s1["times_returned"] >= 1, "A→B→A return span was lost"
    s2 = next(s for s in slides if 18 <= s["first_seen_s"] <= 23)
    assert s2["on_screen_total_s"] >= 85, "the 95 s hold was truncated"
    floor_slide = next(s for s in slides if s["source"] == "floor")
    assert 150 <= floor_slide["first_seen_s"] <= 215
    assert (rd.slides_dir / slides[0]["file"]).exists()
