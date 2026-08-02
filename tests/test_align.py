from talkbrief.align import assign_slides, build_windows


def _segments(n=100, step=10.0, words=20):
    return [
        {"start": i * step, "end": (i + 1) * step, "text": "word " * words}
        for i in range(n)
    ]


def test_windows_by_word_target_without_chapters():
    windows = build_windows(_segments(), [], 1000.0, target_words=200)
    assert len(windows) >= 5
    assert windows[0]["start_s"] == 0.0
    assert windows[-1]["end_s"] == 1000.0
    assert all(w["word_count"] > 0 for w in windows)


def test_windows_follow_chapters():
    chapters = [
        {"title": "Intro", "start_s": 0.0, "end_s": 300.0},
        {"title": "Body", "start_s": 300.0, "end_s": 700.0},
        {"title": "Close", "start_s": 700.0, "end_s": 0.0},  # open-ended last chapter
    ]
    windows = build_windows(_segments(), chapters, 1000.0, target_words=100000)
    assert [w["chapter_title"] for w in windows] == ["Intro", "Body", "Close"]
    assert windows[-1]["end_s"] == 1000.0


def test_oversized_chapter_is_split():
    chapters = [
        {"title": "Tiny", "start_s": 0.0, "end_s": 100.0},
        {"title": "Huge", "start_s": 100.0, "end_s": 1000.0},
    ]
    windows = build_windows(_segments(), chapters, 1000.0, target_words=300)
    huge_parts = [w for w in windows if w["chapter_title"] and "Huge" in w["chapter_title"]]
    assert len(huge_parts) >= 3
    assert all(w["word_count"] <= 1.7 * 300 for w in huge_parts)


def test_windows_time_fallback_without_transcript():
    windows = build_windows([], [], 900.0, target_words=2200)
    assert len(windows) == 3
    assert windows[-1]["end_s"] == 900.0


def _slide(sid, spans):
    total = sum(e - s for s, e in spans)
    return {
        "id": sid, "first_seen_s": spans[0][0],
        "on_screen": [{"start_s": s, "end_s": e} for s, e in spans],
        "on_screen_total_s": total,
    }


def test_assign_primary_and_context():
    windows = build_windows(_segments(), [], 1000.0, target_words=400)
    slides = [
        _slide("s001", [(0.0, 150.0)]),
        _slide("s002", [(150.0, 190.0), (600.0, 640.0)]),  # returns later → context there
    ]
    assign_slides(windows, slides)
    primaries = [w for w in windows if "s001" in w["primary_slide_ids"]]
    assert len(primaries) == 1  # a slide is written about exactly once
    all_primary = [sid for w in windows for sid in w["primary_slide_ids"]]
    assert sorted(all_primary) == ["s001", "s002"]
    context_hits = [w["id"] for w in windows if "s002" in w["context_slide_ids"]]
    assert context_hits, "the return visit should be at least context somewhere"


def test_assign_handles_no_slides():
    windows = build_windows(_segments(), [], 1000.0, target_words=400)
    assign_slides(windows, [])
    assert all(w["primary_slide_ids"] == [] for w in windows)
