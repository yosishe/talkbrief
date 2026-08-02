"""talkbrief command line: run / batch / resume / render / doctor."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import STAGES, RunConfig
from .fetch import FetchError
from .llm import BackendAuthError, BackendError, get_backend
from .pipeline import run_batch, run_url
from .preflight import print_doctor, run_doctor
from .render.html import render_report
from .render.pdf import render_pdf
from .rundir import RunDir
from .util import read_json, setup_logging

_BROWSERS = ("chrome", "safari", "firefox", "brave", "edge")


def _add_shared(p: argparse.ArgumentParser) -> None:
    p.add_argument("--outdir", type=Path, default=Path("./talkbrief-runs"))
    p.add_argument("--lang", choices=("en", "he"), default="en",
                   help="output language of the brief (he = full RTL report)")
    p.add_argument("--pdf", action="store_true", help="also export report.pdf (needs [pdf] extra)")
    p.add_argument("--asr", choices=("off", "auto", "force"), default="off",
                   help="local transcription: auto = only when no captions (needs [asr] extra)")
    p.add_argument("--asr-model", default="small", help="faster-whisper model id")
    p.add_argument("--model", default=None, help="passed through to `claude --model`")
    p.add_argument("--backend", default="claude-code", help=argparse.SUPPRESS)
    p.add_argument("--max-budget-usd", type=float, default=3.0, help="per LLM call cap")
    p.add_argument("--max-images", type=int, default=24, help="image attachments per LLM call")
    p.add_argument("--interval", type=float, default=2.0, help="frame sampling interval (s)")
    p.add_argument("--threshold", type=float, default=0.08, help="dhash new-slide distance")
    p.add_argument("--stability", type=float, default=0.05, help="settled-frame distance")
    p.add_argument("--floor-seconds", type=float, default=45.0,
                   help="fixed-interval union floor; 0 disables (not recommended)")
    p.add_argument("--cookies-from", choices=_BROWSERS, default=None,
                   help="explicit opt-in: read cookies from this browser for gated videos")
    p.add_argument("--embed", choices=("auto", "always", "never"), default="auto",
                   help="single-file report (embed images) vs assets/ folder")
    p.add_argument("--only", default="", metavar="STAGES", help=f"comma list of {','.join(STAGES)}")
    p.add_argument("--force", default="", metavar="STAGES", help="re-run these stages")
    p.add_argument("--verbose", action="store_true")


def _stages_arg(raw: str) -> tuple[str, ...]:
    stages = tuple(s.strip() for s in raw.split(",") if s.strip())
    for s in stages:
        if s not in STAGES:
            raise SystemExit(f"unknown stage {s!r} — stages are: {', '.join(STAGES)}")
    return stages


def _cfg_from(args: argparse.Namespace) -> RunConfig:
    return RunConfig(
        outdir=args.outdir, lang=args.lang, pdf=args.pdf,
        asr=args.asr, asr_model=args.asr_model, model=args.model, backend=args.backend,
        max_budget_usd=args.max_budget_usd, max_images=args.max_images,
        interval=args.interval, threshold=args.threshold, stability=args.stability,
        floor_seconds=args.floor_seconds, cookies_from=args.cookies_from,
        embed=args.embed, only_stages=_stages_arg(args.only),
        force_stages=_stages_arg(args.force), verbose=args.verbose,
    )


def _make_backend(cfg: RunConfig, needs_llm: bool):
    backend = get_backend(cfg.backend)
    if needs_llm and backend.name != "fake":
        problems = backend.preflight()
        if problems:
            raise BackendAuthError("\n".join(problems))
    return backend


def _needs_llm(cfg: RunConfig) -> bool:
    return not cfg.only_stages or "synthesize" in cfg.only_stages


def cmd_run(args: argparse.Namespace) -> int:
    cfg = _cfg_from(args)
    setup_logging(cfg.verbose)
    backend = _make_backend(cfg, _needs_llm(cfg))
    failures = 0
    for url in args.url:
        try:
            rd = run_url(url, cfg, backend)
            print(f"\n→ {rd.report_html}")
        except FetchError as e:
            failures += 1
            print(f"✗ {url}: {e} [{e.error_class}]", file=sys.stderr)
    return 1 if failures else 0


def cmd_batch(args: argparse.Namespace) -> int:
    cfg = _cfg_from(args)
    setup_logging(cfg.verbose)
    lines = Path(args.file).read_text(encoding="utf-8").splitlines()
    urls = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    if not urls:
        print("no URLs in batch file", file=sys.stderr)
        return 1
    backend = _make_backend(cfg, _needs_llm(cfg))
    manifest = run_batch(urls, cfg, backend)
    done = sum(1 for r in manifest["items"].values() if r.get("status") == "done")
    return 0 if done == len(manifest["items"]) else 2


def cmd_resume(args: argparse.Namespace) -> int:
    cfg = _cfg_from(args)
    setup_logging(cfg.verbose)
    path = Path(args.dir)
    if (path / "manifest.json").exists():
        url = read_json(path / "manifest.json").get("url")
        if not url:
            print("manifest has no url", file=sys.stderr)
            return 1
        cfg.outdir = path.parent
        backend = _make_backend(cfg, _needs_llm(cfg))
        rd = run_url(url, cfg, backend)
        print(f"\n→ {rd.report_html}")
        return 0
    if (path / "MANIFEST.json").exists():
        cfg.outdir = path
        items = read_json(path / "MANIFEST.json")["items"]
        urls = [u for u, r in items.items() if r.get("status") != "done"
                and r.get("error_class") != "FAILED_FINAL"]
        if not urls:
            print("nothing to resume")
            return 0
        backend = _make_backend(cfg, _needs_llm(cfg))
        run_batch(urls, cfg, backend)
        return 0
    print(f"{path} is neither a run dir nor a batch outdir", file=sys.stderr)
    return 1


def cmd_render(args: argparse.Namespace) -> int:
    cfg = _cfg_from(args)
    setup_logging(cfg.verbose)
    rd = RunDir(Path(args.dir))
    if not rd.verified_path.exists():
        print(f"no verify/verified.json under {rd.root} — run the pipeline first", file=sys.stderr)
        return 1
    meta = read_json(rd.meta_path)
    render_report(rd, meta, cfg)
    if cfg.pdf:
        render_pdf(rd.report_html, rd.report_pdf)
    print(f"→ {rd.report_html}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = _cfg_from(args)
    setup_logging(cfg.verbose)
    ok = print_doctor(run_doctor(cfg, probe_llm=not args.no_probe))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="talkbrief",
        description="Turn a YouTube talk into a grounded, slide-by-slide interactive brief.",
    )
    parser.add_argument("--version", action="version", version=f"talkbrief {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="full pipeline for one or more URLs")
    p.add_argument("url", nargs="+")
    _add_shared(p)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("batch", help="process a file of URLs (one per line, # comments)")
    p.add_argument("file")
    _add_shared(p)
    p.set_defaults(fn=cmd_batch)

    p = sub.add_parser("resume", help="re-run incomplete/failed stages of a run or batch dir")
    p.add_argument("dir")
    _add_shared(p)
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("render", help="re-render the report from existing artifacts")
    p.add_argument("dir")
    _add_shared(p)
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("doctor", help="preflight all external dependencies")
    p.add_argument("--no-probe", action="store_true", help="skip the paid claude -p probe (~$0.01)")
    _add_shared(p)
    p.set_defaults(fn=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except BackendAuthError as e:
        print(f"\n✗ LLM backend not ready:\n{e}", file=sys.stderr)
        return 3
    except BackendError as e:
        print(f"\n✗ LLM backend error: {e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
