"""PDF export via weasyprint (the `[pdf]` extra) — the one proven bidi-correct path
for Hebrew RTL output. The print stylesheet inside the report drives the layout."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("talkbrief")

_PAGE_CSS = """
@page { size: A4; margin: 14mm 12mm; }
"""


def render_pdf(report_html: Path, target: Path) -> Path:
    try:
        from weasyprint import CSS, HTML
    except ImportError as e:
        raise RuntimeError(
            "PDF export needs weasyprint — pip install 'talkbrief[pdf]' "
            "(or print the HTML report to PDF from your browser)"
        ) from e
    HTML(filename=str(report_html)).write_pdf(
        str(target), stylesheets=[CSS(string=_PAGE_CSS)]
    )
    log.info("pdf: %s (%.1f MB)", target, target.stat().st_size / 1e6)
    return target
