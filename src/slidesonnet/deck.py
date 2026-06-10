"""Load a :class:`Deck` from a PDF + its narration sidecar, with diagnostics."""

from __future__ import annotations

from pathlib import Path

from slidesonnet.diagnostics import Diagnostic, diagnose
from slidesonnet.narration.format import parse_sidecar, serialize_sidecar
from slidesonnet.narration.model import Deck, PageNarration
from slidesonnet.pdf.reader import read_page_ids


def default_sidecar_path(pdf_path: Path) -> Path:
    """The sidecar path for *pdf_path*: ``<deck-stem>.narration`` beside it."""
    return pdf_path.with_suffix(".narration")


def load_deck(pdf_path: Path, *, sidecar_path: Path | None = None) -> tuple[Deck, list[Diagnostic]]:
    """Load *pdf_path* and its sidecar into a :class:`Deck` plus diagnostics.

    A missing sidecar is treated as empty narration (every page un-narrated).
    """
    pdf_path = pdf_path.resolve()
    sidecar = sidecar_path or default_sidecar_path(pdf_path)
    pages = read_page_ids(pdf_path)

    blocks: list[PageNarration] = []
    if sidecar.exists():
        blocks = parse_sidecar(sidecar.read_text(encoding="utf-8"))

    diags = diagnose(pages, blocks)
    deck = Deck(
        pdf_path=pdf_path,
        sidecar_path=sidecar,
        pages=pages,
        narration={b.slide_id: b for b in blocks},
    )
    return deck, diags


def blank_blocks_for(pages: list[str]) -> list[PageNarration]:
    """One empty narration block per (unique, real) page id, in page order."""
    seen: set[str] = set()
    blocks: list[PageNarration] = []
    for pid in pages:
        if pid and pid not in seen:
            seen.add(pid)
            blocks.append(PageNarration(slide_id=pid))
    return blocks


def save_deck(deck: Deck, *, header: str | None = None) -> None:
    """Serialize *deck*'s narration to its sidecar, in PDF page order."""
    blocks = [deck.page_narration(pid) for pid in _unique(deck.pages) if pid]
    # Include any orphan blocks (not on a page) so they aren't silently dropped.
    on_page = {pid for pid in deck.pages if pid}
    for sid, block in deck.narration.items():
        if sid not in on_page:
            blocks.append(block)
    deck.sidecar_path.write_text(serialize_sidecar(blocks, header=header), encoding="utf-8")


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
