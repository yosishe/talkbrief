"""Pipeline orchestration: fetch → slides → transcript → align → synthesize → verify → render.

Each stage is checkpointed in the run's manifest; a completed stage with unchanged
parameters is never re-run. Batch runs classify failures FINAL vs RETRYABLE so a dead
link is never retried and a transient one never poisons the manifest.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from .align import run_align
from .config import RunConfig
from .fetch import FetchError, extract_video_id, run_fetch
from .llm import LLMBackend
from .render.html import render_report
from .render.pdf import render_pdf
from .rundir import FAILED_UNKNOWN, RunDir
from .slides import run_slides
from .synthesize import run_synthesize
from .transcript import run_transcript
from .util import read_json, run_cmd, setup_logging, write_json
from .verify import run_verify

log = logging.getLogger("talkbrief")


def tool_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name, cmd in {
        "ffmpeg": ["ffmpeg", "-version"],
        "yt-dlp": ["yt-dlp", "--version"],
        "deno": ["deno", "--version"],
        "claude": ["claude", "--version"],
    }.items():
        try:
            res = run_cmd(cmd, timeout=15)
            out[name] = res.stdout.splitlines()[0].strip() if res.returncode == 0 else None
        except Exception:
            out[name] = None
    return out


def find_existing_rundir(outdir: Path, video_id: str | None) -> RunDir | None:
    if not video_id:
        return None
    hits = sorted(Path(outdir).glob(f"{video_id}__*"))
    return RunDir(hits[0]) if hits else None


def _stage(rd: RunDir, cfg: RunConfig, name: str, fn: Callable[[], object]) -> None:
    if cfg.only_stages and name not in cfg.only_stages:
        return
    if not rd.should_run(name, cfg):
        log.info("%s: cached, skipping", name)
        return
    t0 = time.monotonic()
    try:
        fn()
    except Exception as e:
        rd.mark(name, "failed", seconds=time.monotonic() - t0, error=str(e))
        raise
    rd.mark(name, "done", seconds=time.monotonic() - t0, config_hash=cfg.stage_hash(name))


def run_url(url: str, cfg: RunConfig, backend: LLMBackend) -> RunDir:
    video_id = extract_video_id(url)
    rd = find_existing_rundir(cfg.outdir, video_id)

    if rd is None or rd.should_run("fetch", cfg):
        t0 = time.monotonic()
        try:
            rd, meta = run_fetch(url, cfg, rd)
        except FetchError:
            raise
        rd.init_manifest(url, meta["id"], cfg, tool_versions())
        rd.mark("fetch", "done", seconds=time.monotonic() - t0,
                config_hash=cfg.stage_hash("fetch"))
    else:
        meta = read_json(rd.meta_path)
        rd.init_manifest(url, meta["id"], cfg, tool_versions())
        log.info("fetch: cached, skipping")

    setup_logging(cfg.verbose, rd.log_path)
    log.info("run: %s -> %s", url, rd.root)

    _stage(rd, cfg, "slides", lambda: run_slides(rd, meta, cfg))
    _stage(rd, cfg, "transcript", lambda: run_transcript(rd, meta, cfg))
    _stage(rd, cfg, "align", lambda: run_align(rd, meta, cfg))
    _stage(rd, cfg, "synthesize", lambda: run_synthesize(rd, meta, cfg, backend))
    _stage(rd, cfg, "verify", lambda: run_verify(rd, cfg))

    def _render() -> None:
        render_report(rd, meta, cfg)
        if cfg.pdf:
            render_pdf(rd.report_html, rd.report_pdf)

    _stage(rd, cfg, "render", _render)
    return rd


def run_batch(urls: list[str], cfg: RunConfig, backend: LLMBackend) -> dict:
    manifest_path = Path(cfg.outdir) / "MANIFEST.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {"items": {}}
    for url in urls:
        row = manifest["items"].get(url, {})
        if row.get("error_class") == "FAILED_FINAL":
            log.info("batch: skipping (final failure recorded): %s", url)
            continue
        try:
            rd = run_url(url, cfg, backend)
            manifest["items"][url] = {"status": "done", "run_dir": str(rd.root)}
        except FetchError as e:
            log.error("batch: %s -> %s (%s)", url, e, e.error_class)
            manifest["items"][url] = {
                "status": "failed", "error": str(e)[-500:], "error_class": e.error_class,
            }
        except Exception as e:
            log.error("batch: %s -> %s", url, e)
            manifest["items"][url] = {
                "status": "failed", "error": str(e)[-500:], "error_class": FAILED_UNKNOWN,
            }
        write_json(manifest_path, manifest)
    done = sum(1 for r in manifest["items"].values() if r.get("status") == "done")
    log.info("batch: %d/%d done (manifest: %s)", done, len(manifest["items"]), manifest_path)
    return manifest
