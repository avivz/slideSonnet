"""Read slide-ids from a PDF text layer and rasterize pages to PNG.

Slide-ids are stamped by ``slidesonnet.sty`` as invisible ``SSID:<id>`` markers
(one per emitted page). :func:`read_page_ids` recovers them via PyMuPDF;
:func:`rasterize` renders page images via ``pdftoppm`` (parity with the
FFmpeg composer's expected inputs).
"""

from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

from slidesonnet.exceptions import ParserError
from slidesonnet.proc import run_tool

_SSID_RE = re.compile(r"SSID:(\S+)")


def read_page_ids(pdf_path: Path) -> list[str]:
    """Return the slide-id for each PDF page in order.

    A page with no ``SSID:`` marker yields an empty string (flagged later by
    diagnostics). If a page somehow carries more than one marker, the first is
    used.
    """
    if not pdf_path.exists():
        raise ParserError(f"PDF not found: {pdf_path}")
    ids: list[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            match = _SSID_RE.search(page.get_text())
            ids.append(match.group(1) if match else "")
    return ids


def page_count(pdf_path: Path) -> int:
    """Return the number of pages in *pdf_path*."""
    if not pdf_path.exists():
        raise ParserError(f"PDF not found: {pdf_path}")
    with fitz.open(pdf_path) as doc:
        return int(doc.page_count)


def page_aspect(pdf_path: Path) -> float:
    """Return the width/height ratio of the first page (e.g. 4:3 → 1.333)."""
    if not pdf_path.exists():
        raise ParserError(f"PDF not found: {pdf_path}")
    with fitz.open(pdf_path) as doc:
        rect = doc[0].rect
        return float(rect.width / rect.height)


def _numeric_suffix(path: Path) -> int:
    """Extract the trailing integer from a pdftoppm output filename."""
    m = re.search(r"(\d+)$", path.stem)
    return int(m.group(1)) if m else 0


def rasterize(
    pdf_path: Path,
    out_dir: Path,
    *,
    dpi: int = 150,
    prefix: str = "page",
) -> list[Path]:
    """Rasterize every PDF page to ``<out_dir>/<prefix>-N.png`` via pdftoppm.

    Returns the page PNGs in page order. Raises :class:`ParserError` if
    ``pdftoppm`` is missing or fails.
    """
    if not pdf_path.exists():
        raise ParserError(f"PDF not found: {pdf_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear any stale page images so the returned list is exactly this render.
    for stale in out_dir.glob(f"{prefix}-*.png"):
        stale.unlink()

    cmd = ["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(out_dir / prefix)]
    run_tool(
        cmd, error_cls=ParserError, install_hint="poppler-utils", fail_message="pdftoppm failed"
    )

    pages = sorted(out_dir.glob(f"{prefix}-*.png"), key=_numeric_suffix)
    if not pages:
        raise ParserError(f"pdftoppm produced no images for {pdf_path}")
    return pages
