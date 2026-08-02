"""JSON Schema contracts for every on-disk artifact and every LLM reply.

LLM-facing schemas are strict (`additionalProperties: false`): an unknown key means the
model and the pipeline disagree about the shape, and that is a defect to surface, not to
absorb. The model NEVER writes a timestamp — it writes verbatim quotes; code stamps times.
"""

from __future__ import annotations

import jsonschema

_SPAN = {
    "type": "object",
    "additionalProperties": False,
    "required": ["start_s", "end_s"],
    "properties": {"start_s": {"type": "number"}, "end_s": {"type": "number"}},
}

_SEGMENT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["start", "end", "text"],
    "properties": {
        "start": {"type": "number"},
        "end": {"type": "number"},
        "text": {"type": "string"},
    },
}

TRANSCRIPT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "language", "source", "provenance", "segments", "coverage"],
    "properties": {
        "schema_version": {"const": 1},
        "language": {"type": ["string", "null"]},
        "source": {"enum": ["captions", "asr", "none"]},
        "provenance": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "track", "cue_count", "asr_model"],
            "properties": {
                "kind": {"enum": ["manual", "auto", "asr", "none"]},
                "track": {"type": ["string", "null"]},
                "cue_count": {"type": ["integer", "null"]},
                "asr_model": {"type": ["string", "null"]},
            },
        },
        "segments": {"type": "array", "items": _SEGMENT},
        "coverage": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ok", "spoken_fraction", "largest_internal_gap_seconds", "gaps"],
            "properties": {
                "ok": {"type": "boolean"},
                "spoken_fraction": {"type": "number"},
                "largest_internal_gap_seconds": {"type": "number"},
                "gaps": {"type": "array", "items": _SPAN},
            },
        },
    },
}

_SLIDE = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id", "index", "file", "first_seen_s", "hms", "on_screen",
        "on_screen_total_s", "times_returned", "ocr_text", "ocr_chars",
        "ocr_engine", "builds_collapsed", "source",
    ],
    "properties": {
        "id": {"type": "string"},
        "index": {"type": "integer"},
        "file": {"type": "string"},
        "first_seen_s": {"type": "number"},
        "hms": {"type": "string"},
        "on_screen": {"type": "array", "items": _SPAN, "minItems": 1},
        "on_screen_total_s": {"type": "number"},
        "times_returned": {"type": "integer"},
        "ocr_text": {"type": "string"},
        "ocr_chars": {"type": "integer"},
        "ocr_engine": {"enum": ["vision", "tesseract", "none"]},
        "builds_collapsed": {"type": "integer"},
        "source": {"enum": ["hash", "floor"]},
    },
}

SLIDES = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "params", "ocr", "slides", "stats"],
    "properties": {
        "schema_version": {"const": 1},
        "params": {"type": "object"},
        "ocr": {
            "type": "object",
            "additionalProperties": False,
            "required": ["engines_used", "vision_available"],
            "properties": {
                # counts what actually RAN per slide, never what is installed —
                # the measured "stats said tesseract while Vision did the work" bug.
                "engines_used": {"type": "object", "additionalProperties": {"type": "integer"}},
                "vision_available": {"type": "boolean"},
            },
        },
        "slides": {"type": "array", "items": _SLIDE},
        "stats": {"type": "object"},
    },
}

ALIGNMENT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "windows"],
    "properties": {
        "schema_version": {"const": 1},
        "windows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id", "start_s", "end_s", "chapter_title",
                    "word_count", "primary_slide_ids", "context_slide_ids",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "start_s": {"type": "number"},
                    "end_s": {"type": "number"},
                    "chapter_title": {"type": ["string", "null"]},
                    "word_count": {"type": "integer"},
                    "primary_slide_ids": {"type": "array", "items": {"type": "string"}},
                    "context_slide_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

# ---------------------------------------------------------------- LLM contracts

_QUOTED_POINT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "quote"],
    "properties": {
        "text": {"type": "string"},
        # verbatim words from the transcript (>= 4 words unless highly distinctive);
        # null when nothing quotable supports the point.
        "quote": {"type": ["string", "null"]},
    },
}

MAP_OUTPUT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["window_id", "slides", "window_points", "window_summary"],
    "properties": {
        "window_id": {"type": "string"},
        "slides": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "slide_id", "heading", "what_it_shows",
                    "speaker_points", "significance", "not_said_aloud",
                ],
                "properties": {
                    "slide_id": {"type": "string"},
                    "heading": {"type": "string"},
                    "what_it_shows": {"type": "string"},
                    "speaker_points": {"type": "array", "items": _QUOTED_POINT},
                    "significance": {"type": "string"},
                    "not_said_aloud": {"type": ["string", "null"]},
                },
            },
        },
        "window_points": {"type": "array", "items": _QUOTED_POINT},
        "window_summary": {"type": "string"},
    },
}

REDUCE_OUTPUT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "tldr", "narrative", "key_takeaways", "glossary", "chapters", "numbers_and_names",
    ],
    "properties": {
        "tldr": {"type": "string"},
        "narrative": {"type": "array", "items": {"type": "string"}},
        "key_takeaways": {"type": "array", "items": _QUOTED_POINT},
        "glossary": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["term", "definition", "quote"],
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string"},
                    "quote": {"type": ["string", "null"]},
                },
            },
        },
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "one_liner", "quote"],
                "properties": {
                    "title": {"type": "string"},
                    "one_liner": {"type": "string"},
                    "quote": {"type": ["string", "null"]},
                },
            },
        },
        "numbers_and_names": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item", "quote", "source"],
                "properties": {
                    "item": {"type": "string"},
                    "quote": {"type": ["string", "null"]},
                    "source": {"enum": ["speech", "slide"]},
                },
            },
        },
    },
}

# ------------------------------------------------------- assembled digest / verified


def _stamped(point_schema: dict) -> dict:
    """The same quoted-point shape after verify.py stamps it."""
    stamped = {k: (dict(v) if isinstance(v, dict) else v) for k, v in point_schema.items()}
    stamped = dict(point_schema)
    props = dict(stamped["properties"])
    props["t"] = {"type": ["number", "null"]}
    props["grounded"] = {"type": "boolean"}
    props["match_source"] = {"enum": ["speech", "slide", None]}
    stamped["properties"] = props
    return stamped


DIGEST = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "lang", "video", "overview", "slides", "windows", "model"],
    "properties": {
        "schema_version": {"const": 1},
        "lang": {"enum": ["en", "he"]},
        "video": {
            "type": "object",
            "required": ["id", "title", "duration_s"],
            "properties": {
                "id": {"type": "string"},
                "url": {"type": "string"},
                "title": {"type": "string"},
                "channel": {"type": ["string", "null"]},
                "duration_s": {"type": "number"},
            },
        },
        "overview": {"type": "object"},
        "slides": {"type": "array"},
        "windows": {"type": "array"},
        "model": {"type": "object"},
        "verification": {"type": "object"},
    },
}

VERIFIED = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version", "lang", "video", "overview", "slides", "windows",
        "model", "verification",
    ],
    "properties": dict(DIGEST["properties"])
    | {
        "verification": {
            "type": "object",
            "required": ["quotes_total", "quotes_grounded", "token_recall", "missing_tokens"],
            "properties": {
                "quotes_total": {"type": "integer"},
                "quotes_grounded": {"type": "integer"},
                "token_recall": {"type": ["number", "null"]},
                "missing_tokens": {"type": "array", "items": {"type": "string"}},
            },
        }
    },
}

SCHEMAS: dict[str, dict] = {
    "transcript": TRANSCRIPT,
    "slides": SLIDES,
    "alignment": ALIGNMENT,
    "map_output": MAP_OUTPUT,
    "reduce_output": REDUCE_OUTPUT,
    "digest": DIGEST,
    "verified": VERIFIED,
}


class SchemaError(ValueError):
    pass


def validate(name: str, data: dict) -> None:
    try:
        jsonschema.validate(data, SCHEMAS[name])
    except jsonschema.ValidationError as e:
        raise SchemaError(f"{name} artifact invalid at {list(e.absolute_path)}: {e.message}") from e
