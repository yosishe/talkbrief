"""The LLM seam: a minimal request/response contract every backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


class BackendError(RuntimeError):
    pass


class BackendAuthError(BackendError):
    """Authentication is broken; retrying will not help — a human must act."""


@dataclass
class LLMRequest:
    prompt: str
    schema: dict  # JSON Schema the reply must satisfy
    workdir: Path
    image_paths: list[str] = field(default_factory=list)  # relative to workdir
    model: str | None = None
    max_budget_usd: float = 3.0
    timeout_s: int = 900
    label: str = "call"


@dataclass
class LLMResult:
    data: dict  # schema-validated payload
    cost_usd: float | None
    duration_s: float
    raw: dict  # full backend envelope, persisted for debugging


class LLMBackend(ABC):
    name: str = "abstract"

    @abstractmethod
    def preflight(self) -> list[str]:
        """Human-readable problems; empty list means ready. Runs BEFORE any expensive
        pipeline compute so a broken backend costs zero minutes of download/OCR."""

    @abstractmethod
    def generate_json(self, request: LLMRequest) -> LLMResult: ...
