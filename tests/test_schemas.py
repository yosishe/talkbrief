import pytest

from talkbrief.schemas import SchemaError, validate

MAP_OK = {
    "window_id": "w01",
    "slides": [{
        "slide_id": "s001", "heading": "h", "what_it_shows": "w",
        "speaker_points": [{"text": "t", "quote": "a b c d"}],
        "significance": "s", "not_said_aloud": None,
    }],
    "window_points": [],
    "window_summary": "sum",
}

REDUCE_OK = {
    "tldr": "t", "narrative": ["p"],
    "key_takeaways": [{"text": "t", "quote": None}],
    "glossary": [{"term": "x", "definition": "y", "quote": None}],
    "chapters": [{"title": "c", "one_liner": "o", "quote": "q u o t e"}],
    "numbers_and_names": [{"item": "40 ms", "quote": "40 ms", "source": "speech"}],
}


def test_map_output_valid():
    validate("map_output", MAP_OK)


def test_map_output_rejects_unknown_key():
    bad = {**MAP_OK, "extra": 1}
    with pytest.raises(SchemaError):
        validate("map_output", bad)


def test_map_output_rejects_model_written_timestamp_field():
    bad = dict(MAP_OK)
    bad["slides"] = [dict(MAP_OK["slides"][0], timestamp=12.0)]
    with pytest.raises(SchemaError):
        validate("map_output", bad)


def test_reduce_output_valid_and_strict():
    validate("reduce_output", REDUCE_OK)
    with pytest.raises(SchemaError):
        validate("reduce_output", {**REDUCE_OK, "chapters": [{"title": "c"}]})


def test_transcript_schema_roundtrip():
    doc = {
        "schema_version": 1, "language": "en", "source": "captions",
        "provenance": {"kind": "manual", "track": "en", "cue_count": 2, "asr_model": None},
        "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}],
        "coverage": {"ok": True, "spoken_fraction": 1.0,
                     "largest_internal_gap_seconds": 0.0, "gaps": []},
    }
    validate("transcript", doc)
    doc["provenance"]["kind"] = "guessed"
    with pytest.raises(SchemaError):
        validate("transcript", doc)
