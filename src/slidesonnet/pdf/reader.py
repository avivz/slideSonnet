"""Read slide-ids from a PDF text layer and rasterize pages to PNG.

Slide-ids are stamped by ``slidesonnet.sty`` as invisible ``SSID:<id>`` markers
(one per emitted page). :func:`read_page_ids` recovers them via PyMuPDF;
:func:`rasterize` renders page images via ``pdftoppm`` (parity with the
FFmpeg composer's expected inputs).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

import pymupdf

from slidesonnet.exceptions import ParserError
from slidesonnet.proc import run_tool

logger = logging.getLogger(__name__)

_SSID_RE = re.compile(r"SSID:(\S+)")
_FINAL_MARKER = "SSFINAL"
_PLAIN_MARKER = "SSPLAIN"


def read_page_ids(pdf_path: Path) -> list[str]:
    """Return the slide-id for each PDF page in order.

    A page with no ``SSID:`` marker yields an empty string (flagged later by
    diagnostics). If a page somehow carries more than one marker, the first is
    used.
    """
    if not pdf_path.exists():
        raise ParserError(f"PDF not found: {pdf_path}")
    ids: list[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            match = _SSID_RE.search(page.get_text())
            ids.append(match.group(1) if match else "")
    return ids


def is_final_build(pdf_path: Path) -> bool:
    """True when *pdf_path* was compiled as a final build (``\\ssfinal``).

    ``slidesonnet.sty`` hides position-dependent decorations (page numbers,
    navigation, progress bars) in an ordinary *plain* compile and shows them
    only in a final build, which it stamps with an invisible ``SSFINAL`` marker
    next to each page's ``SSID``. The first page decides.
    """
    return _build_marker(pdf_path) == _FINAL_MARKER


def is_plain_build(pdf_path: Path) -> bool:
    """True when *pdf_path* is a plain build from the current ``slidesonnet.sty``.

    Plain builds are stamped ``SSPLAIN``; a PDF from an older ``.sty`` carries
    neither marker and is neither plain nor final.
    """
    return _build_marker(pdf_path) == _PLAIN_MARKER


def _build_marker(pdf_path: Path) -> str | None:
    if not pdf_path.exists():
        raise ParserError(f"PDF not found: {pdf_path}")
    with pymupdf.open(pdf_path) as doc:
        if doc.page_count == 0:
            return None
        words = doc[0].get_text().split()
    return next((w for w in words if w in (_FINAL_MARKER, _PLAIN_MARKER)), None)


def page_count(pdf_path: Path) -> int:
    """Return the number of pages in *pdf_path*."""
    if not pdf_path.exists():
        raise ParserError(f"PDF not found: {pdf_path}")
    with pymupdf.open(pdf_path) as doc:
        return int(doc.page_count)


def page_aspect(pdf_path: Path) -> float:
    """Return the width/height ratio of the first page (e.g. 4:3 → 1.333)."""
    if not pdf_path.exists():
        raise ParserError(f"PDF not found: {pdf_path}")
    with pymupdf.open(pdf_path) as doc:
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
    # The stamp goes first (the old images no longer describe this PDF); the old
    # images stay up until the new ones replace them, and any extra go after, so
    # the returned list — and what the stamp claims — is exactly this render.
    (out_dir / RENDER_STAMP_NAME).unlink(missing_ok=True)
    fresh = set(_pdftoppm(["-r", str(dpi), str(pdf_path)], out_dir, prefix))
    for stale in out_dir.glob(f"{prefix}-*.png"):
        if stale not in fresh:
            stale.unlink()

    pages = sorted(fresh, key=_numeric_suffix)
    if not pages:
        raise ParserError(f"pdftoppm produced no images for {pdf_path}")
    write_render_stamp(pdf_path, out_dir, dpi=dpi, prefix=prefix, count=len(pages))
    return pages


def _page_files(out_dir: Path, prefix: str) -> dict[int, Path]:
    """Page images in *out_dir*, by 0-based page index (pdftoppm names are 1-based)."""
    return {_numeric_suffix(p) - 1: p for p in out_dir.glob(f"{prefix}-*.png")}


def open_render(
    pdf_path: Path, out_dir: Path, *, page_count: int, dpi: int = 150, prefix: str = "page"
) -> dict[int, Path]:
    """The page images already rendered from *pdf_path*, for filling in the rest.

    Unlike :func:`cached_pages` this accepts a partial render: the editor shows
    a deck at once and renders its pages in the background, a few at a time.
    Images from another build (or dpi) are deleted and the render restarts.
    """
    try:
        stamp = json.loads((out_dir / RENDER_STAMP_NAME).read_text(encoding="utf-8"))
        wanted = _render_identity(pdf_path, dpi=dpi, prefix=prefix)
        same = isinstance(stamp, dict) and all(stamp.get(k) == v for k, v in wanted.items())
    except (OSError, ValueError):
        same = False
    if same:
        return _page_files(out_dir, prefix)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / RENDER_STAMP_NAME).unlink(missing_ok=True)
    for stale in out_dir.glob(f"{prefix}-*.png"):
        stale.unlink(missing_ok=True)
    write_render_stamp(pdf_path, out_dir, dpi=dpi, prefix=prefix, count=page_count)
    return {}


def render_page_range(
    pdf_path: Path, out_dir: Path, first: int, last: int, *, dpi: int = 150, prefix: str = "page"
) -> dict[int, Path]:
    """Render pages *first*..*last* (0-based, inclusive) into *out_dir* via pdftoppm.

    File names match a whole-deck :func:`rasterize` (pdftoppm pads page numbers
    to the document's page count), so the two can fill the same directory.
    """
    args = ["-r", str(dpi), "-f", str(first + 1), "-l", str(last + 1), str(pdf_path)]
    _pdftoppm(args, out_dir, prefix)
    return {i: p for i, p in _page_files(out_dir, prefix).items() if first <= i <= last}


def _pdftoppm(args: list[str], out_dir: Path, prefix: str) -> list[Path]:
    """Run pdftoppm into a scratch dir, then move each image into *out_dir* whole.

    The editor serves *out_dir* while it renders (a recompile re-renders every
    page): an image pdftoppm is still writing must never be sent. A rename in
    the same directory tree replaces a file in one step.
    """
    scratch = Path(tempfile.mkdtemp(dir=out_dir, prefix=".render-"))
    try:
        run_tool(
            ["pdftoppm", "-png", *args, str(scratch / prefix)],
            error_cls=ParserError,
            install_hint="poppler-utils",
            fail_message="pdftoppm failed",
        )
        placed = []
        for image in scratch.glob(f"{prefix}-*.png"):
            os.replace(image, out_dir / image.name)
            placed.append(out_dir / image.name)
        return placed
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
