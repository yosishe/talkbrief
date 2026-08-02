"""LLM backend registry. v1 ships claude-code; the seam exists so v2 can add an
Anthropic-API backend without touching call sites. Resolution failures are loud,
never silent downgrades."""

from __future__ import annotations

from .backend import BackendAuthError, BackendError, LLMBackend, LLMRequest, LLMResult


def get_backend(name: str, **kwargs) -> LLMBackend:
    if name == "claude-code":
        from .claude_code import ClaudeCodeBackend

        return ClaudeCodeBackend(**kwargs)
    if name == "fake":
        from .fake import FakeBackend

        return FakeBackend(**kwargs)
    if name == "api":
        from .anthropic_api import AnthropicAPIBackend

        return AnthropicAPIBackend(**kwargs)
    raise BackendError(f"unknown LLM backend: {name!r} (available: claude-code, fake, api)")


__all__ = [
    "BackendAuthError",
    "BackendError",
    "LLMBackend",
    "LLMRequest",
    "LLMResult",
    "get_backend",
]
