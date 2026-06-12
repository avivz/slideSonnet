"""Load a :class:`Deck` from a PDF + its narration sidecar, with diagnostics."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from slidesonnet.diagnostics import Diagnostic, diagnose, sort_diagnostics
from slidesonnet.narration.format import parse_sidecar, serialize_sidecar
from slidesonnet.narration.model import Deck, PageNarration
from slidesonnet.pdf.reader import read_page_ids


def default_sidecar_path(pdf_path: Path) -> Path:
    """The sidecar path for *pdf_path*: ``<deck-stem>.narration`` beside it."""
    return pdf_path.with_suffix(".narration")


def dedupe_page_ids(pages: list[str]) -> tuple[list[str], list[Diagnostic]]:
    """Rename repeated slide-ids so every page is addressable: x, x → x, x-2.

    The first occurrence keeps its name; each later one gets the smallest
    ``-n`` (n ≥ 2) that no other page uses — raw ids included, so a genuine
    ``x-2`` elsewhere in the deck is never clobbered (the duplicate skips to
    ``x-3``). Every rename is reported as a warning: narration attached to a
    renamed id is bound by *occurrence order*, which shifts if pages reorder —
    giving each page its own ``\\ssid`` is still the durable fix.

    Unmarked pages (empty id) pass through; they carry their own diagnostic.
    """
    taken = {p for p in pages if p}
    seen: set[str] = set()
    out: list[str] = []
    diags: list[Diagnostic] = []
    for i, pid in enumerate(pages, start=1):
        if not pid or pid not in seen:
            seen.add(pid)
            out.append(pid)
            continue
        n = 2
        while f"{pid}-{n}" in taken:
            n += 1
        new = f"{pid}-{n}"
        taken.add(new)
        seen.add(new)
        out.append(new)
        if pid not in {d.slide_id for d in diags if d.code == "duplicate-id"}:
            diags.append(
                Diagnostic(
                    "warning",
                    "duplicate-id",
                    f"slide-id '{pid}' appears on several pages — later ones were "
                    "renamed to disambiguate; give each page its own \\ssid",
                    pid,
                )
            )
        diags.append(
            Diagnostic(
                "warning",
                "duplicate-id",
                f"page {i} reused slide-id '{pid}' — renamed to '{new}' to "
                "disambiguate; give it its own \\ssid",
                new,
            )
        )
    return out, diags


def dedupe_block_ids(
    blocks: list[PageNarration],
) -> tuple[list[PageNarration], list[Diagnostic]]:
    """Rename repeated sidecar ``@ids`` so no narration block is silently dropped.

    The narration is keyed by id, so two ``@same-id`` blocks would otherwise
    collapse to one (last wins) — losing the first block's text. Instead the
    first keeps its id and each later one is renamed to the smallest free
    ``-n`` (n ≥ 2), avoiding collision with any other block id. A renamed block
    usually has no matching page, so it surfaces in the unattached-narration
    tray where it can be re-attached or deleted. Every rename is a warning;
    de-duplicating the ``@blocks`` in the file is still the durable fix.
    """
    taken = {b.slide_id for b in blocks}
    seen: set[str] = set()
    out: list[PageNarration] = []
    diags: list[Diagnostic] = []
    flagged: set[str] = set()
    for block in blocks:
        sid = block.slide_id
        if sid not in seen:
            seen.add(sid)
            out.append(block)
            continue
        n = 2
        while f"{sid}-{n}" in taken:
            n += 1
        new = f"{sid}-{n}"
        taken.add(new)
        seen.add(new)
        out.append(replace(block, slide_id=new))
        if sid not in flagged:
            flagged.add(sid)
            diags.append(
                Diagnostic(
                    "warning",
                    "duplicate-block",
                    f"slide-id '{sid}' has more than one narration block — later "
                    "ones were renamed to disambiguate; merge the @blocks in the file",
                    sid,
                )
            )
        diags.append(
            Diagnostic(
                "warning",
                "duplicate-block",
                f"a second '{sid}' block was renamed to '{new}' so its text is kept",
                new,
            )
        )
    return out, diags


def load_deck(
    pdf_path: Path,
    *,
    sidecar_path: Path | None = None,
    pages: tuple[list[str], list[Diagnostic]] | None = None,
) -> tuple[Deck, list[Diagnostic]]:
    """Load *pdf_path* and its sidecar into a :class:`Deck` plus diagnostics.

    A missing sidecar is treated as empty narration (every page un-narrated).
    *pages* injects a previously-computed (deduped page ids, dedupe
    diagnostics) pair when the PDF is known unchanged — reading ids re-opens
    the PDF and walks every page, which callers that reload per edit-commit
    (the editor) cannot afford.
    """
    pdf_path = pdf_path.resolve()
    sidecar = sidecar_path or default_sidecar_path(pdf_path)
    if pages is None:
        pages = dedupe_page_ids(read_page_ids(pdf_path))
    page_ids, dedupe_diags = pages

    blocks: list[PageNarration] = []
    block_diags: list[Diagnostic] = []
    if sidecar.exists():
        blocks, block_diags = dedupe_block_ids(parse_sidecar(sidecar.read_text(encoding="utf-8")))

    diags = sort_diagnostics(dedupe_diags + block_diags + diagnose(page_ids, blocks))
    deck = Deck(
        pdf_path=pdf_path,
        sidecar_path=sidecar,
        pages=page_ids,
        narration={b.slide_id: b for b in blocks},
    )
    return deck, diags


def save_deck(deck: Deck, *, header: str | None = None) -> None:
    """Serialize *deck*'s narration to its sidecar, in PDF page order.

    Empty placeholder blocks are skipped: a page with no narration is left out
    of the sidecar entirely (a bare ``@id`` header would otherwise read back as
    an empty narration block and silence its ``missing-narration`` warning).
    """
    blocks = [deck.page_narration(pid) for pid in unique_real_ids(deck.pages)]
    # Include any orphan blocks (not on a page) so they aren't silently dropped.
    on_page = {pid for pid in deck.pages if pid}
    for sid, block in deck.narration.items():
        if sid not in on_page:
            blocks.append(block)
    blocks = [b for b in blocks if not b.is_empty]
    deck.sidecar_path.write_text(serialize_sidecar(blocks, header=header), encoding="utf-8")


def unique_real_ids(pages: list[str]) -> list[str]:
    """The deck's addressable slide-ids: deduped, in page order, blanks dropped."""
    return [pid for pid in dict.fromkeys(pages) if pid]
