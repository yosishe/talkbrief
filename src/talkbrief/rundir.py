"""Per-video run directory: layout, manifest, stage marking, resume rules.

A stage is skipped on resume iff its manifest status is "done" AND the hash of the
parameters that feed it is unchanged. `--force <stage>` overrides.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from .config import STAGES, RunConfig
from .util import read_json, slugify, write_json

FAILED_FINAL = "FAILED_FINAL"  # never retried (private video, deleted, geo-blocked)
FAILED_RETRYABLE = "FAILED_RETRYABLE"  # replaced on retry, never duplicated
FAILED_UNKNOWN = "FAILED_UNKNOWN"


class RunDir:
    def __init__(self, root: Path):
        self.root = Path(root)

    @classmethod
    def create(cls, outdir: Path, video_id: str, title: str) -> RunDir:
        return cls(Path(outdir) / f"{video_id}__{slugify(title)}")

    # ------------------------------------------------------------------ layout
    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def meta_path(self) -> Path:
        return self.root / "meta.json"

    @property
    def media_dir(self) -> Path:
        return self.root / "media"

    @property
    def video_path(self) -> Path:
        return self.media_dir / "video.mp4"

    @property
    def audio_path(self) -> Path:
        return self.media_dir / "audio.m4a"

    @property
    def captions_dir(self) -> Path:
        return self.root / "captions"

    @property
    def transcript_path(self) -> Path:
        return self.root / "transcript" / "transcript.json"

    @property
    def slides_dir(self) -> Path:
        return self.root / "slides"

    @property
    def slides_json(self) -> Path:
        return self.slides_dir / "slides.json"

    @property
    def alignment_path(self) -> Path:
        return self.root / "align" / "alignment.json"

    @property
    def digest_dir(self) -> Path:
        return self.root / "digest"

    @property
    def digest_path(self) -> Path:
        return self.digest_dir / "digest.json"

    @property
    def calls_dir(self) -> Path:
        return self.digest_dir / "calls"

    @property
    def verified_path(self) -> Path:
        return self.root / "verify" / "verified.json"

    @property
    def report_dir(self) -> Path:
        return self.root / "report"

    @property
    def report_html(self) -> Path:
        return self.report_dir / "report.html"

    @property
    def report_pdf(self) -> Path:
        return self.report_dir / "report.pdf"

    @property
    def log_path(self) -> Path:
        return self.root / "run.log"

    def ensure(self) -> None:
        for p in (
            self.root, self.media_dir, self.captions_dir, self.slides_dir,
            self.transcript_path.parent, self.alignment_path.parent,
            self.digest_dir, self.calls_dir, self.verified_path.parent, self.report_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- manifest
    def load_manifest(self) -> dict:
        if self.manifest_path.exists():
            return read_json(self.manifest_path)
        return {}

    def init_manifest(self, url: str, video_id: str, cfg: RunConfig, tool_versions: dict) -> dict:
        manifest = self.load_manifest()
        if not manifest:
            manifest = {
                "schema_version": 1,
                "url": url,
                "video_id": video_id,
                "created_at": _dt.datetime.now(_dt.UTC).isoformat(),
                "stages": {},
            }
        manifest["tool_versions"] = tool_versions
        manifest["stage_config_hashes"] = {s: cfg.stage_hash(s) for s in STAGES}
        write_json(self.manifest_path, manifest)
        return manifest

    def mark(
        self,
        stage: str,
        status: str,
        *,
        seconds: float | None = None,
        error: str | None = None,
        error_class: str | None = None,
        config_hash: str | None = None,
    ) -> None:
        manifest = self.load_manifest()
        rec: dict = {"status": status}
        if seconds is not None:
            rec["seconds"] = round(seconds, 1)
        if error is not None:
            rec["error"] = error[-1000:]
        if error_class is not None:
            rec["error_class"] = error_class
        if config_hash is not None:
            rec["config_hash"] = config_hash
        if status == "done":
            rec["completed_at"] = _dt.datetime.now(_dt.UTC).isoformat()
        manifest.setdefault("stages", {})[stage] = rec
        write_json(self.manifest_path, manifest)

    def should_run(self, stage: str, cfg: RunConfig, force: bool = False) -> bool:
        if force or stage in cfg.force_stages:
            return True
        rec = self.load_manifest().get("stages", {}).get(stage)
        if not rec or rec.get("status") != "done":
            return True
        return rec.get("config_hash") != cfg.stage_hash(stage)

    def invalidate_downstream(self, stage: str) -> None:
        """A stage that re-ran makes every LATER stage's artifacts stale — config
        hashes alone can't see upstream-data changes."""
        manifest = self.load_manifest()
        stages = manifest.get("stages", {})
        idx = STAGES.index(stage) + 1 if stage in STAGES else len(STAGES)
        changed = False
        for later in STAGES[idx:]:
            rec = stages.get(later)
            if rec and rec.get("status") == "done":
                rec["status"] = "stale"
                changed = True
        if changed:
            write_json(self.manifest_path, manifest)
