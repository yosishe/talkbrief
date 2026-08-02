"""AnthropicAPIBackend — documented v2 stub.

The v2 mapping from the seam (kept here so no refactor is needed when it lands):

- ``LLMRequest.prompt``        → ``messages=[{"role": "user", "content": [...]}]``
- ``LLMRequest.schema``        → structured outputs:
  ``output_config={"format": {"type": "json_schema", "schema": schema}}``
  (or the SDK's ``client.messages.parse`` helper)
- ``LLMRequest.image_paths``   → base64 ``{"type": "image"}`` content blocks placed
  BEFORE the text block
- ``LLMRequest.max_budget_usd``→ a pre-flight ``count_tokens`` guard
- ``LLMRequest.model``         → e.g. ``claude-sonnet-5`` / ``claude-opus-5``
- auth                         → ``ANTHROPIC_API_KEY`` env var
"""

from __future__ import annotations

from .backend import BackendError, LLMBackend, LLMRequest, LLMResult


class AnthropicAPIBackend(LLMBackend):
    name = "api"

    def preflight(self) -> list[str]:
        return ["the Anthropic API backend is planned for v2 — use the default claude-code backend"]

    def generate_json(self, request: LLMRequest) -> LLMResult:
        raise BackendError(
            "the Anthropic API backend is a v2 stub — run with the default claude-code backend"
        )
