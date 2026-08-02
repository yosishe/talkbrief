from talkbrief.verify import TranscriptIndex, anchor_quote, coverage_recall

SEGMENTS = [
    {"start": 10.0, "end": 14.0, "text": "we reduced latency from 40 ms to 4 ms using the new cache"},
    {"start": 14.0, "end": 18.0, "text": "the model was trained on twelve billion tokens total"},
    {"start": 18.0, "end": 22.0,
     "text": "again and again and again and again and again it just works"},
]
SLIDES = [{
    "id": "s001", "first_seen_s": 55.0,
    "ocr_text": "Kimi K2.6 architecture overview\nlatency budget table",
}]


def _anchor(quote):
    return anchor_quote(quote, TranscriptIndex(SEGMENTS), SLIDES)


def test_exact_match_stamps_segment_time():
    t, ok, src = _anchor("reduced latency from 40 ms")
    assert (t, ok, src) == (10.0, True, "speech")


def test_ellipsis_fragments_in_order():
    t, ok, src = _anchor("we reduced latency … using the new cache")
    assert (t, ok, src) == (10.0, True, "speech")


def test_fuzzy_match_passes_with_equal_digits():
    t, ok, src = _anchor("the model was trained on twelve billion token")
    assert ok and src == "speech" and t == 14.0


def test_fuzzy_match_rejects_digit_mismatch():
    # fuzzy 0.90 would happily accept this — the digit gate must not
    t, ok, _ = _anchor("we reduced latency from 40 ms to 5 ms using the new cache")
    assert not ok and t is None


def test_short_distinctive_quote_passes():
    t, ok, src = _anchor("new cache")
    assert ok and t == 10.0 and src == "speech"


def test_short_ambiguous_quote_fails():
    t, ok, _ = _anchor("again and")  # pins 4 locations — a stamp would be a guess
    assert not ok


def test_slide_ocr_fallback():
    t, ok, src = _anchor("Kimi K2.6")
    assert (t, ok, src) == (55.0, True, "slide")


def test_fabricated_quote_fails_everywhere():
    _t, ok, src = _anchor("we achieved a 99 percent accuracy improvement overnight")
    assert not ok and src is None


def test_coverage_recall_min_count_applies_to_both_sides():
    transcript = "we shipped v2.4.1 with 40 ms latency, v2.4.1 again at 40 ms; IBM and IBM. once-only"
    brief = "the release v2.4.1 was discussed with IBM"
    recall, missing = coverage_recall(transcript, brief)
    assert recall is not None
    assert "40 ms" in missing            # appeared twice, absent from brief → counted missing
    assert "once-only" not in missing    # appeared once → excluded from BOTH sides
    assert abs(recall - 2 / 3) < 0.01


def test_coverage_recall_empty_when_no_hard_tokens():
    recall, missing = coverage_recall("just plain words here", "brief")
    assert recall is None and missing == []
