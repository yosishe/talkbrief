"""ClaudeCodeBackend tests against RECORDED envelopes — including the real error
envelope captured live on 2026-08-03, whose `"subtype": "success"` next to
`"is_error": true` is exactly the gotcha these tests pin down."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from talkbrief.llm import BackendAuthError, BackendError
from talkbrief.llm.backend import LLMRequest
from talkbrief.llm.claude_code import ClaudeCodeBackend, _extract_json

# recorded verbatim from a live `claude -p` probe on this machine (2026-08-03)
AUTH_ERROR_ENVELOPE = {
    "type": "result", "subtype": "success", "is_error": True, "api_error_status": None,
    "duration_ms": 57, "duration_api_ms": 0, "num_turns": 1,
    "result": "Failed to authenticate: OAuth session expired and could not be refreshed",
    "stop_reason": "stop_sequence", "session_id": "5bbe0bb3", "total_cost_usd": 0,
    "usage": {}, "modelUsage": {}, "permission_denials": [],
    "terminal_reason": "api_error", "fast_mode_state": "off", "uuid": "f7f333ee",
}

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["ok"], "properties": {"ok": {"type": "boolean"}},
}


class _Proc:
    def __init__(self, envelope):
        self.returncode = 0
        self.stdout = json.dumps(envelope)
        self.stderr = ""


def _req(**kw) -> LLMRequest:
    defaults = dict(prompt="p", schema=SCHEMA, workdir=Path("."), label="t")
    defaults.update(kw)
    return LLMRequest(**defaults)


def _patch_run(monkeypatch, envelopes: list[dict], calls: list):
    it = iter(envelopes)

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _Proc(next(it))

    monkeypatch.setattr("talkbrief.llm.claude_code.subprocess.run", fake_run)


def test_success_via_fenced_result(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, [
        {"is_error": False, "result": "```json\n{\"ok\": true}\n```", "total_cost_usd": 0.012}
    ], calls)
    result = ClaudeCodeBackend().generate_json(_req())
    assert result.data == {"ok": True}
    assert result.cost_usd == 0.012
    cmd, kwargs = calls[0]
    assert "--json-schema" in cmd
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA  # inline, never a path
    assert cmd[cmd.index("--tools") + 1] == ""  # no images → no tools at all
    assert kwargs["input"] == "p"


def test_success_via_structured_output(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, [{"is_error": False, "structured_output": {"ok": False},
                              "result": "ignored"}], calls)
    result = ClaudeCodeBackend().generate_json(_req())
    assert result.data == {"ok": False}


def test_images_enable_read_tool(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, [{"is_error": False, "result": '{"ok": true}'}], calls)
    ClaudeCodeBackend().generate_json(_req(image_paths=["slides/slide_001.jpg"]))
    cmd, _ = calls[0]
    assert cmd[cmd.index("--tools") + 1] == "Read"


def test_recorded_auth_error_raises_auth_not_retry(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, [AUTH_ERROR_ENVELOPE] * 3, calls)
    with pytest.raises(BackendAuthError) as e:
        ClaudeCodeBackend().generate_json(_req())
    assert "setup-token" in str(e.value)
    assert len(calls) == 1  # auth failure must NOT be retried


def test_is_error_true_despite_subtype_success(monkeypatch):
    """The measured gotcha: never judge success by `subtype`."""
    envelope = dict(AUTH_ERROR_ENVELOPE, result="model exploded")  # non-auth error text
    _patch_run(monkeypatch, [envelope] * 3, [])
    monkeypatch.setattr("talkbrief.llm.claude_code.time.sleep", lambda s: None)
    with pytest.raises(BackendError):
        ClaudeCodeBackend().generate_json(_req())


def test_schema_invalid_reply_retried_with_correction(monkeypatch):
    calls: list = []
    _patch_run(monkeypatch, [
        {"is_error": False, "result": '{"ok": "yes"}'},   # wrong type
        {"is_error": False, "result": '{"ok": true}'},
    ], calls)
    result = ClaudeCodeBackend().generate_json(_req())
    assert result.data == {"ok": True}
    assert len(calls) == 2
    assert "did not match" in calls[1][1]["input"]


def test_extract_json_variants():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('noise before {"a": {"b": 2}} noise after') == {"a": {"b": 2}}
