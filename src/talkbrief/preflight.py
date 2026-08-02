"""`talkbrief doctor` — preflight every external dependency BEFORE any expensive work.

The most important check is the claude CLI auth probe: headless `claude -p` can be
broken (OAuth expired) while the interactive session works fine, and discovering that
after a 40-minute download is the failure mode this command exists to prevent.
"""

from __future__ import annotations

import datetime as _dt
import shutil

from .config import RunConfig
from .util import run_cmd

OK, WARN, FAIL = "ok", "warn", "fail"
_MARK = {OK: "✓", WARN: "⚠", FAIL: "✗"}


def _version_of(cmd: list[str]) -> str | None:
    try:
        res = run_cmd(cmd, timeout=15)
        return res.stdout.splitlines()[0].strip() if res.returncode == 0 else None
    except Exception:
        return None


def _check_ytdlp() -> tuple[str, str]:
    v = _version_of(["yt-dlp", "--version"])
    if not v:
        return FAIL, "yt-dlp not found — pip install yt-dlp"
    try:
        released = _dt.datetime.strptime(v.split(".post")[0], "%Y.%m.%d")
        age = (_dt.datetime.now() - released).days
        if age > 60:
            return WARN, f"{v} is {age} days old — YouTube churn is weekly-scale, upgrade if fetch fails"
    except ValueError:
        pass
    return OK, v


def _check_import(module: str, hint: str) -> tuple[str, str]:
    try:
        __import__(module)
        return OK, "installed"
    except ImportError:
        return WARN, hint


def run_doctor(cfg: RunConfig, probe_llm: bool = True) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []

    for tool in ("ffmpeg", "ffprobe"):
        v = _version_of([tool, "-version"])
        rows.append((tool, OK if v else FAIL, v or f"{tool} not found — install ffmpeg"))

    rows.append(("yt-dlp", *_check_ytdlp()))

    deno = _version_of(["deno", "--version"])
    rows.append((
        "deno", OK if deno else WARN,
        deno or "not found — current yt-dlp needs an external JS runtime for YouTube",
    ))

    if not shutil.which("claude"):
        rows.append(("claude", FAIL, "claude CLI not found — install Claude Code (v1 backend)"))
    elif probe_llm:
        from .llm.claude_code import ClaudeCodeBackend

        problems = ClaudeCodeBackend().preflight()
        rows.append((
            "claude -p", OK if not problems else FAIL,
            "headless call + JSON schema verified" if not problems else problems[0].split("\n")[0],
        ))
        if problems and len(problems[0].split("\n")) > 1:
            for line in problems[0].split("\n")[1:]:
                if line.strip():
                    rows.append(("", "", line.rstrip()))
    else:
        rows.append(("claude", OK, _version_of(["claude", "--version"]) or "present"))

    try:
        import ocrmac  # noqa: F401

        rows.append(("ocr", OK, "Apple Vision via ocrmac (2.1–2.6× cleaner than tesseract)"))
    except ImportError:
        if shutil.which("tesseract"):
            rows.append(("ocr", OK, "tesseract (install 'talkbrief[ocr]' on macOS for Apple Vision)"))
        else:
            rows.append(("ocr", WARN, "no OCR engine — slides will route as images (slower, costlier)"))

    rows.append(("asr", *_check_import(
        "faster_whisper", "optional — pip install 'talkbrief[asr]' for --asr"
    )))
    rows.append(("pdf", *_check_import(
        "weasyprint", "optional — pip install 'talkbrief[pdf]' for --pdf"
    )))
    return rows


def print_doctor(rows: list[tuple[str, str, str]]) -> bool:
    width = max((len(r[0]) for r in rows), default=8) + 2
    ok = True
    for name, status, detail in rows:
        if not name:
            print(" " * (width + 2) + detail)
            continue
        ok = ok and status != FAIL
        print(f"{_MARK.get(status, ' ')} {name.ljust(width)} {detail}")
    return ok
