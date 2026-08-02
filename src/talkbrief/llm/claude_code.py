"""ClaudeCodeBackend — rides the local, already-authenticated Claude Code CLI.

No API key. The invocation is locked down: no session persistence, no slash commands,
no MCP servers, permission mode that denies anything interactive, and the Read tool
enabled ONLY when the call needs to look at slide images (the CLI's Read tool renders
images to the model; files are passed as cwd-relative paths, never base64 — one slide
measured 72 KB as base64 vs a filename as a path).

Envelope parsing is written against the MEASURED payload, not the field names
(a live probe returned `"subtype": "success"` together with `"is_error": true`):
success is judged by `is_error` alone, and the OAuth failure string is detected
specifically so users get remediation instead of a fake model error.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time

from .backend import BackendAuthError, BackendError, LLMBackend, LLMRequest, LLMResult

log = logging.getLogger("talkbrief")

_AUTH_REMEDIATION = (
    "The `claude` CLI cannot authenticate in headless mode. Fix (one of):\n"
    "  1. Run `claude` interactively once and complete login, then retry.\n"
    "  2. Run `claude auth login` (older CLIs: `/login` inside claude).\n"
    "  3. For long-lived headless use, run `claude setup-token`.\n"
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if m := _FENCE_RE.search(text):
        return json.loads(m.group(1))
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        return json.loads(text[start : end + 1])
    raise json.JSONDecodeError("no JSON object found", text[:80], 0)


class ClaudeCodeBackend(LLMBackend):
    name = "claude-code"

    def __init__(self, claude_bin: str = "claude"):
        self.claude_bin = claude_bin

    def _base_cmd(self, request: LLMRequest) -> list[str]:
        cmd = [
            self.claude_bin,
            "-p",
            "--output-format", "json",
            # inline JSON only — passing a file path fails with "Unrecognized token '/'"
            "--json-schema", json.dumps(request.schema),
            "--tools", "Read" if request.image_paths else "",
            "--permission-mode", "dontAsk",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--max-budget-usd", f"{request.max_budget_usd:.2f}",
        ]
        if request.model:
            cmd += ["--model", request.model]
        return cmd

    def preflight(self) -> list[str]:
        if not shutil.which(self.claude_bin):
            return [f"`{self.claude_bin}` CLI not found on PATH — install Claude Code first."]
        probe = LLMRequest(
            prompt="Reply with a JSON object exactly matching the schema. Set ok to true.",
            schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
            workdir=None,  # type: ignore[arg-type]
            max_budget_usd=0.10,
            timeout_s=120,
            label="preflight",
        )
        try:
            self._call_once(probe, cwd=None)
            return []
        except BackendAuthError as e:
            return [str(e)]
        except Exception as e:
            return [f"claude -p probe failed: {e}"]

    def _call_once(self, request: LLMRequest, cwd) -> tuple[dict, dict, float]:
        t0 = time.monotonic()
        proc = subprocess.run(
            self._base_cmd(request),
            input=request.prompt,
            capture_output=True,
            text=True,
            timeout=request.timeout_s,
            cwd=str(cwd) if cwd else None,
        )
        duration = time.monotonic() - t0
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise BackendError(
                f"claude -p returned non-JSON (exit {proc.returncode}): "
                f"{(proc.stdout or proc.stderr)[:300]!r}"
            ) from e
        if envelope.get("is_error"):
            result_text = str(envelope.get("result", ""))
            if "authenticate" in result_text.lower() or "oauth" in result_text.lower():
                raise BackendAuthError(f"{result_text}\n{_AUTH_REMEDIATION}")
            raise BackendError(
                f"claude -p error ({envelope.get('terminal_reason')}): {result_text[:300]}"
            )
        structured = envelope.get("structured_output")
        payload = structured if isinstance(structured, dict) else _extract_json(
            str(envelope.get("result", ""))
        )
        return payload, envelope, duration

    def generate_json(self, request: LLMRequest) -> LLMResult:
        import jsonschema

        prompt = request.prompt
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                attempt_req = LLMRequest(**{**request.__dict__, "prompt": prompt})
                payload, envelope, duration = self._call_once(attempt_req, cwd=request.workdir)
                jsonschema.validate(payload, request.schema)
                return LLMResult(
                    data=payload,
                    cost_usd=envelope.get("total_cost_usd"),
                    duration_s=round(duration, 1),
                    raw=envelope,
                )
            except BackendAuthError:
                raise  # a human must act; retrying is noise
            except jsonschema.ValidationError as e:
                last_error = e
                prompt = (
                    request.prompt
                    + "\n\nYour previous reply did not match the required JSON schema. "
                    + f"Validator said: {e.message[:300]}. Reply again with ONLY a valid JSON object."
                )
                log.warning("%s: schema-invalid reply, retrying (%s)", request.label, e.message[:120])
            except (BackendError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
                last_error = e
                log.warning("%s: %s — retrying", request.label, str(e)[:200])
                time.sleep(5 * (attempt + 1))
        raise BackendError(f"{request.label}: giving up after 3 attempts: {last_error}")
