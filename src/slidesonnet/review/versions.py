"""A deck *version*: per slide id, what the page looks like and says.

A version is captured from the PDF + sidecar on disk. Two versions — the stored
base and the current files — are compared slide by slide (see
:mod:`slidesonnet.review.diff`). Page images are compared by a hash of their
decoded pixels at a fixed resolution, so a recompile that changes nothing
visible (timestamps, PDF object ids) hashes the same. LaTeX also re-lays a
frame out by a few hundredths of a point when its neighbours change (moving a
frame is enough), which flips anti-aliased pixels; a capture given the base's
images therefore keeps the base hash for a page that only differs that way
(see :func:`same_picture`) — but not one with faint new ink (pale text, a
translucent highlighter, a grown arrowhead), which a pure level tolerance misses.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf
from numpy.typing import NDArray

from slidesonnet.deck import dedupe_page_ids, load_deck
from slidesonnet.narration.format import serialize_block
from slidesonnet.narration.model import PageNarration
from slidesonnet.pdf.reader import read_page_ids

#: Raster resolution for pixel hashes and stored base images.
DIFF_DPI = 150

#: Two renders are the same picture when every pixel of each has a match within
#: this many levels (0–255, per channel) somewhere in the other's 3×3
#: neighbourhood. Sub-pixel re-layout stays under ~40; the smallest real edit
#: (a period, one subscript digit) scores ~225.
_SAME_PICTURE_TOLERANCE = 80

#: Faint edits — pale text, a translucent highlighter, a grown arrowhead — stay
#: under that tolerance, so a render must also contain no 2×2 patch of
#: :func:`_unexplained` pixels, which this many levels separate from rasterization
#: phase effects.
_FAINT_TOLERANCE = 16

_MARKER_PREFIX = "SSID:"
_BUILD_MARKERS = frozenset({"SSFINAL", "SSPLAIN"})


@dataclass(frozen=True)
class SlideVersion:
    """One slide as it stood: pixel hash, visible text, narration block."""

    image_hash: str
    text: str
    narration: str  # the block's canonical sidecar text; "" when un-narrated

    @property
    def title(self) -> str:
        """First line of the visible text — usually the frame title."""
        return next((line for line in self.text.splitlines() if line.strip()), "")


@dataclass(frozen=True)
class DeckVersion:
    """Slide order plus each slide's version, keyed by slide id."""

    order: tuple[str, ...]
    slides: dict[str, SlideVersion]


def is_diffable_id(slide_id: str) -> bool:
    """Real ids only: blank (unmarked) and positional ``auto-p…`` ids aren't stable."""
    return bool(slide_id) and not slide_id.startswith("auto-p")


def page_text(page: pymupdf.Page) -> str:
    """The page's visible text, one line per text line, markers removed."""
    lines = []
    for line in page.get_text().splitlines():
        words = [
            w for w in line.split() if not w.startswith(_MARKER_PREFIX) and w not in _BUILD_MARKERS
        ]
        if words:
            lines.append(" ".join(words))
    return "\n".join(lines)


def _render(page: pymupdf.Page) -> pymupdf.Pixmap:
    return page.get_pixmap(dpi=DIFF_DPI, alpha=False)


def pixel_hash(pix: pymupdf.Pixmap) -> str:
    digest = hashlib.sha256(f"{pix.width}x{pix.height}x{pix.n}".encode())
    digest.update(pix.samples)
    return digest.hexdigest()[:24]


def _pixels(pix: pymupdf.Pixmap) -> NDArray[np.int16]:
    rgb = pix if pix.n == 3 and not pix.alpha else pymupdf.Pixmap(pymupdf.csRGB, pix, 0)
    return np.frombuffer(rgb.samples, np.uint8).reshape(rgb.height, rgb.width, 3).astype(np.int16)


def _nearest_miss(a: NDArray[np.int16], b: NDArray[np.int16]) -> NDArray[np.int16]:
    """Per pixel of *a*: the smallest difference to a pixel of *b* within one step."""
    h, w, _ = a.shape
    padded = np.pad(b, ((1, 1), (1, 1), (0, 0)), mode="edge")
    best: NDArray[np.int16] | None = None
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            diff = np.abs(a - padded[dy : dy + h, dx : dx + w]).max(axis=2)
            best = diff if best is None else np.minimum(best, diff)
    assert best is not None
    return best


def _unexplained(a: NDArray[np.int16], b: NDArray[np.int16]) -> NDArray[np.bool_]:
    """Pixels of *a* that no sub-pixel shift of *b* can produce.

    A shifted render blends neighbouring pixels, so each of its pixels stays
    within (per channel) the range of the other render's 3×3 neighbourhood — at
    most overshooting by that range where a thin stem or a seam changes phase.
    A pixel outside the range by more than the range itself plus
    :data:`_FAINT_TOLERANCE` is new ink where the other render had none nearby.
    """
    h, w, _ = a.shape
    padded = np.pad(b, ((1, 1), (1, 1), (0, 0)), mode="edge")
    shifts = [padded[dy : dy + h, dx : dx + w] for dy in (0, 1, 2) for dx in (0, 1, 2)]
    lo, hi = np.minimum.reduce(shifts), np.maximum.reduce(shifts)
    excess = np.maximum(np.maximum(a - hi, lo - a), 0) - (hi - lo)
    return np.asarray(excess.max(axis=2) > _FAINT_TOLERANCE)


def _has_patch(mask: NDArray[np.bool_]) -> bool:
    """True when *mask* holds a full 2×2 block (not just a one-pixel-thin line)."""
    return bool((mask[:-1, :-1] & mask[1:, :-1] & mask[:-1, 1:] & mask[1:, 1:]).any())


def same_picture(a: pymupdf.Pixmap, b: pymupdf.Pixmap) -> bool:
    """True when *a* and *b* differ only by sub-pixel re-layout (see module doc)."""
    pa, pb = _pixels(a), _pixels(b)
    if pa.shape != pb.shape:
        return False
    worst = max(int(_nearest_miss(pa, pb).max()), int(_nearest_miss(pb, pa).max()))
    if worst > _SAME_PICTURE_TOLERANCE:
        return False
    return not (_has_patch(_unexplained(pa, pb)) or _has_patch(_unexplained(pb, pa)))


def _canonical_hash(pix: pymupdf.Pixmap, reference: Path | None) -> str:
    """*pix*'s hash — or the reference image's, when they're the same picture."""
    digest = pixel_hash(pix)
    if reference is None or reference.stem == digest or not reference.exists():
        return digest
    return reference.stem if same_picture(pix, pymupdf.Pixmap(str(reference))) else digest


@dataclass(frozen=True)
class PageCapture:
    """The PDF half of a version: slide order plus each page's hash and text."""

    order: tuple[str, ...]
    pages: dict[str, tuple[str, str]]  # slide id -> (pixel hash, visible text)


def capture_pages(
    pdf_path: Path,
    *,
    images_dir: Path | None = None,
    reference: Mapping[str, Path] | None = None,
) -> PageCapture:
    """Hash and read every page with a diffable id (the expensive half).

    With *images_dir*, each page image is also written there as ``<hash>.png``
    (skipped when that file already exists). *reference* maps slide ids to the
    base's ``<hash>.png`` images: a page that is the same picture as its
    reference takes the reference's hash.
    """
    reference = reference or {}
    ids, _diags = dedupe_page_ids(read_page_ids(pdf_path))
    if images_dir is not None:
        images_dir.mkdir(parents=True, exist_ok=True)
    order: list[str] = []
    pages: dict[str, tuple[str, str]] = {}
    with pymupdf.open(pdf_path) as doc:
        for index, slide_id in enumerate(ids):
            if not is_diffable_id(slide_id) or slide_id in pages:
                continue
            page = doc[index]
            pix = _render(page)
            digest = _canonical_hash(pix, reference.get(slide_id))
            if images_dir is not None:
                target = images_dir / f"{digest}.png"
                if not target.exists():
                    pix.save(target)
            pages[slide_id] = (digest, page_text(page))
            order.append(slide_id)
    return PageCapture(order=tuple(order), pages=pages)


def combine(pages: PageCapture, narration: Mapping[str, PageNarration]) -> DeckVersion:
    """Join a page capture with the narration blocks (the cheap half)."""
    slides = {}
    for sid in pages.order:
        digest, text = pages.pages[sid]
        block = narration.get(sid)
        slides[sid] = SlideVersion(
            image_hash=digest,
            text=text,
            narration=serialize_block(block) if block is not None else "",
        )
    return DeckVersion(order=pages.order, slides=slides)


def store_images(
    pdf_path: Path, version: DeckVersion, slide_ids: set[str], images_dir: Path
) -> None:
    """Write missing images for selected slides from an already captured version.

    Existing canonical images stay untouched. Only pages whose images are
    missing need rendering; no pixel comparison is needed a second time.
    """
    missing = {
        sid: images_dir / f"{version.slides[sid].image_hash}.png"
        for sid in slide_ids & version.slides.keys()
        if not (images_dir / f"{version.slides[sid].image_hash}.png").exists()
    }
    if not missing:
        return
    images_dir.mkdir(parents=True, exist_ok=True)
    ids, _diags = dedupe_page_ids(read_page_ids(pdf_path))
    with pymupdf.open(pdf_path) as doc:
        for index, sid in enumerate(ids):
            target = missing.pop(sid, None)
            if target is not None and not target.exists():
                _render(doc[index]).save(target)


def capture(
    pdf_path: Path,
    *,
    sidecar_path: Path | None = None,
    images_dir: Path | None = None,
    reference: Mapping[str, Path] | None = None,
) -> DeckVersion:
    """Capture the current version of the deck at *pdf_path*.

    *images_dir* and *reference* are as for :func:`capture_pages`.
    """
    deck, _diags = load_deck(pdf_path, sidecar_path=sidecar_path)
    pages = capture_pages(deck.pdf_path, images_dir=images_dir, reference=reference)
    return combine(pages, deck.narration)
