"""Small shared helpers: time formatting, hashing, subprocess wrapper, logging."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("talkbrief")


def hms(seconds: float) -> str:
    """68.2 -> '00:01:08'."""
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "video"


def config_hash(params: dict) -> str:
    payload = json.dumps(params, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str


def run_cmd(
    cmd: list[str],
    *,
    timeout: float | None = None,
    cwd: Path | None = None,
    input_text: str | None = None,
    check: bool = False,
) -> CmdResult:
    """Run a subprocess, logging the exact command line (debug level)."""
    log.debug("exec: %s", " ".join(str(c) for c in cmd))
    proc = subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        input=input_text,
    )
    result = CmdResult(proc.returncode, proc.stdout, proc.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd[:4])}…\n{proc.stderr[-2000:]}"
        )
    return result


def setup_logging(verbose: bool, logfile: Path | None = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger("talkbrief")
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)
    if logfile is not None:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(fh)
