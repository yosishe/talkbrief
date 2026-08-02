from talkbrief.transcript import coverage_report, flatten_json3


def test_flatten_json3_basic():
    raw = {"events": [
        {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "hello "}, {"utf8": "world"}]},
        {"tStartMs": 2500, "dDurationMs": 1500, "segs": [{"utf8": "\n"}]},  # empty → dropped
        {"tStartMs": 4000, "dDurationMs": 2000, "segs": [{"utf8": "second cue"}]},
    ]}
    segs = flatten_json3(raw)
    assert [s["text"] for s in segs] == ["hello world", "second cue"]
    assert segs[0]["start"] == 0.0 and segs[0]["end"] == 2.0


def test_flatten_json3_dedupes_rolling_repeat():
    raw = {"events": [
        {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "same line"}]},
        {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "same line"}]},
    ]}
    segs = flatten_json3(raw)
    assert len(segs) == 1
    assert segs[0]["end"] == 3.0


def test_coverage_clean():
    segs = [{"start": float(t), "end": t + 50.0, "text": "x " * 10} for t in range(0, 550, 50)]
    cov = coverage_report(segs, 600.0)
    assert cov["ok"] is True
    assert cov["spoken_fraction"] == 1.0


def test_coverage_hole_detected():
    segs = [
        {"start": 0.0, "end": 60.0, "text": "intro"},
        {"start": 700.0, "end": 760.0, "text": "after the hole"},
    ]
    cov = coverage_report(segs, 800.0)
    assert cov["ok"] is False
    assert cov["largest_internal_gap_seconds"] == 640.0
    assert cov["gaps"] and cov["gaps"][0]["start_s"] == 60.0


def test_coverage_empty():
    cov = coverage_report([], 100.0)
    assert cov["ok"] is False and cov["spoken_fraction"] == 0.0
