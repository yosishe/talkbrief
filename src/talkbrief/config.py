"""Run configuration and per-stage parameter hashing (drives resume/invalidation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .util import config_hash

STAGES = ("fetch", "slides", "transcript", "align", "synthesize", "verify", "render")


@dataclass
class RunConfig:
    outdir: Path = Path("./talkbrief-runs")
    lang: str = "en"  # output language of the brief: en | he
    pdf: bool = False
    asr: str = "off"  # off | auto (only when no captions) | force
    asr_model: str = "small"
    model: str | None = None  # passed through to `claude --model`
    backend: str = "claude-code"  # claude-code | fake (tests) | api (v2)
    max_budget_usd: float = 3.0  # per LLM call
    max_images: int = 24  # per LLM call; the claude CLI hard ceiling is 100
    llm_timeout_s: int = 900
    concurrency: int = 2

    # slide detector — every default carries a measurement (see slides.py)
    interval: float = 2.0
    threshold: float = 0.08
    stability: float = 0.05
    floor_seconds: float = 45.0
    max_slides: int = 400

    caption_langs: tuple[str, ...] = ("en",)
    cookies_from: str | None = None

    target_window_words: int = 2200
    min_ocr_chars_for_text_route: int = 200

    embed: str = "auto"  # auto | always | never
    embed_max_mb: float = 25.0

    only_stages: tuple[str, ...] = ()
    force_stages: tuple[str, ...] = ()
    verbose: bool = False
    extra: dict = field(default_factory=dict)

    def stage_params(self, stage: str) -> dict:
        """The parameters that feed a stage; changing any of them re-runs the stage."""
        table: dict[str, dict] = {
            "fetch": {
                "caption_langs": list(self.caption_langs),
                "cookies_from": self.cookies_from,
            },
            "slides": {
                "interval": self.interval,
                "threshold": self.threshold,
                "stability": self.stability,
                "floor_seconds": self.floor_seconds,
                "max_slides": self.max_slides,
            },
            "transcript": {
                "asr": self.asr,
                "asr_model": self.asr_model,
                "caption_langs": list(self.caption_langs),
            },
            "align": {"target_window_words": self.target_window_words},
            "synthesize": {
                "lang": self.lang,
                "model": self.model,
                "backend": self.backend,
                "max_images": self.max_images,
                "min_ocr_chars_for_text_route": self.min_ocr_chars_for_text_route,
            },
            "verify": {"algo": "anchor-v1"},
            "render": {
                "lang": self.lang,
                "embed": self.embed,
                "embed_max_mb": self.embed_max_mb,
            },
        }
        return table[stage]

    def stage_hash(self, stage: str) -> str:
        return config_hash(self.stage_params(stage))
