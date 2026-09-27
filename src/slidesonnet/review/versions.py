"""A deck *version*: per slide id, what the page looks like and says.

A version is captured from the PDF + sidecar on disk. Two versions — the stored
base and the current files — are compared slide by slide (see
:mod:`slidesonnet.review.diff`). Page images are compared by a hash of their
decoded pixels at a fixed resolution, so a recompile that changes nothing
visible (timestamps, PDF object ids) hashes the same.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from slidesonnet.deck import load_deck
from slidesonnet.narration.format import serialize_block

#: Raster resolution for pixel hashes and stored base images.
DIFF_DPI = 150

_MARKER_PREFIX = "SSID:"
_FINAL_MARKER = "SSFINAL"


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


def page_text(page: fitz.Page) -> str:
    """The page's visible text, one line per text line, markers removed."""
    lines = []
    for line in page.get_text().splitlines():
        words = [w for w in line.split() if not w.startswith(_MARKER_PREFIX) and w != _FINAL_MARKER]
        if words:
            lines.append(" ".join(words))
    return "\n".join(lines)


def _render(page: fitz.Page) -> fitz.Pixmap:
    return page.get_pixmap(dpi=DIFF_DPI, alpha=False)


def pixel_hash(pix: fitz.Pixmap) -> str:
    digest = hashlib.sha256(f"{pix.width}x{pix.height}x{pix.n}".encode())
    digest.update(pix.samples)
    return digest.hexdigest()[:24]


def capture(
    pdf_path: Path, *, sidecar_path: Path | None = None, images_dir: Path | None = None
) -> DeckVersion:
    """Capture the current version of the deck at *pdf_path*.

    With *images_dir*, each slide's page image is also written there as
    ``<hash>.png`` (skipped when that file already exists).
    """
    deck, _diags = load_deck(pdf_path, sidecar_path=sidecar_path)
    if images_dir is not None:
        images_dir.mkdir(parents=True, exist_ok=True)
    order: list[str] = []
    slides: dict[str, SlideVersion] = {}
    with fitz.open(deck.pdf_path) as doc:
        for index, slide_id in enumerate(deck.pages):
            if not is_diffable_id(slide_id) or slide_id in slides:
                continue
            page = doc[index]
            pix = _render(page)
            digest = pixel_hash(pix)
            if images_dir is not None:
                target = images_dir / f"{digest}.png"
                if not target.exists():
                    pix.save(target)
            block = deck.narration.get(slide_id)
            slides[slide_id] = SlideVersion(
                image_hash=digest,
                text=page_text(page),
                narration=serialize_block(block) if block is not None else "",
            )
            order.append(slide_id)
    return DeckVersion(order=tuple(order), slides=slides)
