"""Read slide-ids from a PDF text layer and rasterize pages to PNG.

Slide-ids are stamped by ``slidesonnet.sty`` as invisible ``SSID:<id>`` markers
(one per emitted page). :func:`read_page_ids` recovers them via PyMuPDF;
:func:`rasterize` renders page images via ``pdftoppm`` (parity with the
FFmpeg composer's expected inputs).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import fitz  # PyMuPDF

from slidesonnet.exceptions import ParserError
from slidesonnet.proc import run_tool

logger = logging.getLogger(__name__)

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


#: Records which PDF a directory of page images was rendered from, so an
#: unchanged deck can reuse them instead of re-running pdftoppm.
RENDER_STAMP_NAME = ".render-stamp.json"


def _render_identity(pdf_path: Path, *, dpi: int, prefix: str) -> dict[str, object]:
    """What a render is *of*: the exact PDF bytes, and how they were rendered.

    Mtime and size together, as elsewhere in the codebase: a coarse filesystem
    clock (WSL on a Windows mount reports whole seconds) can hide a recompile
    that lands within the same second, and a size change catches those.
    """
    st = pdf_path.stat()
    return {"mtime_ns": st.st_mtime_ns, "size": st.st_size, "dpi": dpi, "prefix": prefix}


def write_render_stamp(pdf_path: Path, out_dir: Path, *, dpi: int, prefix: str, count: int) -> None:
    """Record that *out_dir* holds *count* page images rendered from *pdf_path*."""
    stamp = {**_render_identity(pdf_path, dpi=dpi, prefix=prefix), "count": count}
    try:
        (out_dir / RENDER_STAMP_NAME).write_text(json.dumps(stamp), encoding="utf-8")
    except OSError as exc:  # a missing stamp only costs a re-render
        logger.debug("could not write render stamp in %s: %s", out_dir, exc)


def cached_pages(
    pdf_path: Path, out_dir: Path, *, dpi: int = 150, prefix: str = "page"
) -> list[Path] | None:
    """Page images already rendered from *pdf_path*, or ``None`` to render again.

    ``None`` whenever anything is uncertain — no stamp, a recompiled PDF, a
    different dpi, missing images, an unreadable stamp — because rendering again
    costs seconds while showing another deck's (or an older build's) slides is a
    correctness bug.
    """
    try:
        raw = (out_dir / RENDER_STAMP_NAME).read_text(encoding="utf-8")
        stamp = json.loads(raw)
        wanted = _render_identity(pdf_path, dpi=dpi, prefix=prefix)
    except (OSError, ValueError):
        return None
    if not isinstance(stamp, dict) or any(stamp.get(k) != v for k, v in wanted.items()):
        return None
    pages = sorted(out_dir.glob(f"{prefix}-*.png"), key=_numeric_suffix)
    if not pages or len(pages) != stamp.get("count"):
        return None
    return pages


def rasterize(
    pdf_path: Path,
    out_dir: Path,
    *,
    dpi: int = 150,
    prefix: str = "page",
    reuse: bool = False,
) -> list[Path]:
    """Rasterize every PDF page to ``<out_dir>/<prefix>-N.png`` via pdftoppm.

    With *reuse*, an existing render of the same PDF at the same dpi is returned
    as-is — pdftoppm costs seconds on a large deck, and the editor opens a deck
    every time you switch to one. Returns the page PNGs in page order. Raises
    :class:`ParserError` if ``pdftoppm`` is missing or fails.
    """
    if not pdf_path.exists():
        raise ParserError(f"PDF not found: {pdf_path}")

    if reuse:
        existing = cached_pages(pdf_path, out_dir, dpi=dpi, prefix=prefix)
        if existing is not None:
            return existing

    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear any stale page images (and the stamp describing them) so the
    # returned list — and what the stamp claims — is exactly this render.
    (out_dir / RENDER_STAMP_NAME).unlink(missing_ok=True)
    for stale in out_dir.glob(f"{prefix}-*.png"):
        stale.unlink()

    cmd = ["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(out_dir / prefix)]
    run_tool(
        cmd, error_cls=ParserError, install_hint="poppler-utils", fail_message="pdftoppm failed"
    )

    pages = sorted(out_dir.glob(f"{prefix}-*.png"), key=_numeric_suffix)
    if not pages:
        raise ParserError(f"pdftoppm produced no images for {pdf_path}")
    write_render_stamp(pdf_path, out_dir, dpi=dpi, prefix=prefix, count=len(pages))
    return pages
