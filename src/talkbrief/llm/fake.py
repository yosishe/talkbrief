"""FakeBackend — deterministic canned replies for tests and offline pipeline runs.

The default handler reads the structure synthesize.py naturally puts in its prompts
(`WINDOW wNN` headers, `SLIDE sNNN` blocks, `[HH:MM:SS]`-prefixed transcript lines)
and produces schema-valid map/reduce outputs — with quotes lifted VERBATIM from the
transcript lines, so verify.py grounds them. The ENTIRE pipeline (including render)
runs with no model.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .backend import LLMBackend, LLMRequest, LLMResult

_WINDOW_RE = re.compile(r"\bWINDOW (w\d+)\b")
_SLIDE_RE = re.compile(r"\bSLIDE (s\d+)\b")
_TRANSCRIPT_LINE_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] (.+)$", re.MULTILINE)


def default_fake_handler(request: LLMRequest) -> dict:
    props = request.schema.get("properties", {})
    lines = _TRANSCRIPT_LINE_RE.findall(request.prompt)
    quote = " ".join(lines[0].split()[:6]) if lines else None
    if "window_id" in props:  # map call
        window = _WINDOW_RE.search(request.prompt)
        slide_ids = list(dict.fromkeys(_SLIDE_RE.findall(request.prompt)))
        return {
            "window_id": window.group(1) if window else "w01",
            "slides": [
                {
                    "slide_id": sid,
                    "heading": f"Heading for {sid}",
                    "what_it_shows": f"A synthetic description of {sid}.",
                    "speaker_points": [
                        {"text": f"A point made while {sid} was on screen.", "quote": quote}
                    ],
                    "significance": "Why this slide matters (synthetic).",
                    "not_said_aloud": None,
                }
                for sid in slide_ids
            ],
            "window_points": (
                [] if slide_ids else [{"text": "A window-level point.", "quote": quote}]
            ),
            "window_summary": "Synthetic summary of this window.",
        }
    return {  # reduce call
        "tldr": "Synthetic TLDR of the whole talk.",
        "narrative": ["First synthetic narrative paragraph.", "Second paragraph."],
        "key_takeaways": [{"text": "Synthetic takeaway.", "quote": quote}],
        "glossary": [{"term": "term", "definition": "a synthetic definition", "quote": None}],
        "chapters": [{"title": "Opening", "one_liner": "How it starts.", "quote": quote}],
        "numbers_and_names": [],
    }


class FakeBackend(LLMBackend):
    name = "fake"

    def __init__(self, handler: Callable[[LLMRequest], dict] | None = None):
        self.handler = handler or default_fake_handler
        self.requests: list[LLMRequest] = []

    def preflight(self) -> list[str]:
        return []

    def generate_json(self, request: LLMRequest) -> LLMResult:
        import jsonschema

        self.requests.append(request)
        data = self.handler(request)
        jsonschema.validate(data, request.schema)
        return LLMResult(data=data, cost_usd=0.0, duration_s=0.0, raw={"fake": True})
