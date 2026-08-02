"""OCR ladder: Apple Vision (via ocrmac) → tesseract → none.

Measured background: Apple Vision beats tesseract by 2.1–2.6× on junk-token rate and
preserves column reading order. Neither preserves code indentation — which is why
code-looking slides are always routed to the model as IMAGES, never as OCR text
(see synthesize.py). Vision also does not read Hebrew: on Hebrew slides it returns
confident Latin-looking garbage rather than failing — another reason low/empty OCR
routes a slide to the image channel instead of trusting the text.

The engine that actually RAN is recorded per slide; "installed" and "used" are
different facts and conflating them once cost a real investigation.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from .util import run_cmd

log = logging.getLogger("talkbrief")

_VISION_STATE: dict[str, bool] = {}


@dataclass
class OcrResult:
    text: str
    engine: str  # vision | tesseract | none
    vision_available: bool


def _vision_usable() -> bool:
    if "ok" not in _VISION_STATE:
        try:
            import ocrmac  # noqa: F401

            _VISION_STATE["ok"] = True
        except Exception:
            _VISION_STATE["ok"] = False
    return _VISION_STATE["ok"]


def _read_vision(image: Path) -> str:
    from ocrmac import ocrmac as _ocrmac

    annotations = _ocrmac.OCR(str(image), recognition_level="accurate").recognize()
    # Vision coordinates are normalized with a BOTTOM-LEFT origin: top-to-bottom
    # reading order = descending y. Group lines by rounded y, then left-to-right.
    lines: dict[float, list[tuple[float, str]]] = {}
    for text, _conf, bbox in annotations:
        x, y = float(bbox[0]), float(bbox[1])
        key = round(y, 2)
        lines.setdefault(key, []).append((x, text))
    ordered = []
    for y in sorted(lines, reverse=True):
        ordered.append(" ".join(t for _x, t in sorted(lines[y])))
    return "\n".join(ordered).strip()


def _read_tesseract(image: Path) -> str:
    res = run_cmd(
        ["tesseract", str(image), "stdout", "--psm", "6"],
        timeout=120,
    )
    return res.stdout.strip() if res.returncode == 0 else ""


def read_image(image: Path) -> OcrResult:
    vision_available = _vision_usable()
    if vision_available:
        try:
            return OcrResult(_read_vision(image), "vision", True)
        except Exception as e:  # degrade, never crash the pipeline over one frame
            log.debug("vision OCR failed on %s: %s", image.name, e)
    if shutil.which("tesseract"):
        text = _read_tesseract(image)
        if text or not vision_available:
            return OcrResult(text, "tesseract", vision_available)
    return OcrResult("", "none", vision_available)
