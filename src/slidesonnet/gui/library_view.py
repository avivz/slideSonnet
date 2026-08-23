"""The deck library — the editor's landing page.

Lists every deck found under the scan root, grouped by top-level folder, so a
course of decks is one click (or one keystroke) apart instead of one relaunch.
Names render straight from the filesystem; the per-deck counts arrive from a
background pass, so a large tree never blocks the page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from nicegui import run, ui

from slidesonnet.deck import load_deck
from slidesonnet.gui.library import DeckEntry, DeckRegistry
from slidesonnet.gui.theme import apply_theme, wordmark
from slidesonnet.pdf.reader import read_page_ids

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeckStats:
    """The cheap-to-show facts about a deck: how big, how much is written."""

    pages: int
    narrated: int

    @property
    def summary(self) -> str:
        """``49 slides · complete`` / ``49 slides · 11 to narrate``.

        Leads with the deck's size (the thing you scan a course list for) and
        says what's left rather than restating the size as a fraction.
        """
        slides = f"{self.pages} slide" + ("" if self.pages == 1 else "s")
        if self.complete:
            return f"{slides} · complete"
        return f"{slides} · {self.pages - self.narrated} to narrate"

    @property
    def complete(self) -> bool:
        return self.pages > 0 and self.narrated >= self.pages


#: Stats are keyed by ``(pdf, sidecar)`` modification stamps so an unchanged deck
#: is never re-read, and an edited one refreshes on the next visit.
_stats_cache: dict[tuple[str, tuple[float, int], tuple[float, int]], DeckStats] = {}


def _stamp(path: Path | None) -> tuple[float, int]:
    try:
        st = path.stat() if path is not None else None
    except OSError:
        return (0.0, 0)
    return (st.st_mtime, st.st_size) if st else (0.0, 0)


def deck_stats(entry: DeckEntry) -> DeckStats | None:
    """Page and narration counts for *entry*, or ``None`` if it can't be read.

    Cached on the deck's file stamps: the library re-reads only what changed.
    """
    key = (entry.token, _stamp(entry.pdf_path), _stamp(entry.sidecar_path))
    cached = _stats_cache.get(key)
    if cached is not None:
        return cached
    try:
        pages = read_page_ids(entry.pdf_path)
        deck, _ = load_deck(entry.pdf_path, sidecar_path=entry.sidecar_path)
        narrated = sum(
            1
            for page in deck.pages
            if (block := deck.narration.get(page)) is not None and block.segments
        )
    except Exception as exc:  # a broken deck must not break the listing
        logger.debug("stats unavailable for %s: %s", entry.pdf_path, exc)
        return None
    stats = DeckStats(pages=len(pages), narrated=narrated)
    _stats_cache[key] = stats
    return stats


def build_library(registry: DeckRegistry) -> None:
    """Render the deck library for *registry* in the current page."""
    apply_theme()
    registry.rescan()
    entries = registry.entries()

    with ui.header().classes("ss-header items-center justify-between no-wrap"):
        with ui.row().classes("items-center gap-3 no-wrap"):
            wordmark()
            ui.label(str(registry.root)).classes("ss-chip ss-mono ss-lib-root")
        with ui.row().classes("items-center gap-2 no-wrap"):
            count = ui.label(_count_text(len(entries))).classes("ss-mono ss-foot")
            count.mark("library-count")
            rescan = ui.button(icon="refresh").props("flat round dense")
            rescan.mark("library-rescan").tooltip("Rescan for decks")
            rescan.on_click(lambda: ui.navigate.to("/"))

    with ui.column().classes("ss-library w-full items-center gap-0"):
        with ui.column().classes("ss-library-inner gap-4"):
            if registry.truncated():
                _notice(
                    "The scan stopped early — this tree is very large. "
                    "Relaunch closer to your decks, or pass --root, to see them all."
                )
            if not entries:
                _empty_state(registry)
                return
            cards: list[tuple[DeckEntry, ui.label]] = []
            for section, decks in registry.grouped():
                ui.label(section or "decks").classes("ss-lib-section ss-mono")
                with ui.column().classes("ss-lib-group gap-2 w-full"):
                    for entry in decks:
                        cards.append((entry, _deck_card(entry)))
            _unnarrated_section(registry)

    ui.timer(0.05, lambda: _fill_stats(cards), once=True)


def _count_text(n: int) -> str:
    return "no decks" if n == 0 else f"{n} deck" + ("" if n == 1 else "s")


def _notice(text: str) -> None:
    with ui.row().classes("ss-lib-notice items-center gap-2 no-wrap"):
        ui.icon("info").classes("ss-lib-notice-icon")
        ui.label(text).classes("ss-mono")


def _sub_path(entry: DeckEntry) -> str:
    """The part of a deck's path the heading and name don't already say.

    Decks usually live at ``<section>/<name>/<name>.pdf``, where spelling the
    folder out again under the name is pure noise; anything else (a deeper
    nesting, a folder named differently from the deck) is worth showing.
    """
    redundant = {"", entry.name, f"{entry.section}/{entry.name}", entry.section}
    return "" if entry.group in redundant else entry.group


def _deck_card(entry: DeckEntry) -> ui.label:
    """One clickable deck row; returns the label its stats land in."""
    card = ui.element("div").classes("ss-lib-card w-full")
    card.mark(f"deck-card-{entry.token}")
    with card, ui.row().classes("items-center justify-between no-wrap w-full gap-3"):
        with ui.column().classes("gap-0 min-w-0"):
            ui.label(entry.name).classes("ss-lib-name ss-mono")
            sub = _sub_path(entry)
            if sub:
                ui.label(sub).classes("ss-lib-path ss-mono")
        stats_label = ui.label("…").classes("ss-lib-stats ss-mono")
    card.on("click", lambda _e=None, e=entry: ui.navigate.to(f"/d/{e.token}"))
    return stats_label


def _unnarrated_section(registry: DeckRegistry) -> None:
    """PDFs with no sidecar — shown, but not openable in the editor."""
    bare = registry.unnarrated()
    if not bare:
        return
    ui.label("no narration yet").classes("ss-lib-section ss-mono")
    with ui.column().classes("ss-lib-group gap-2 w-full"):
        for entry in bare:
            with ui.element("div").classes("ss-lib-card ss-lib-card-muted w-full"):
                with ui.row().classes("items-center justify-between no-wrap w-full gap-3"):
                    with ui.column().classes("gap-0 min-w-0"):
                        ui.label(entry.name).classes("ss-lib-name ss-mono")
                        sub = _sub_path(entry)
                        if sub:
                            ui.label(sub).classes("ss-lib-path ss-mono")
                    ui.label("no .narration file").classes("ss-lib-stats ss-mono")


def _empty_state(registry: DeckRegistry) -> None:
    with ui.column().classes("ss-lib-empty items-center gap-2"):
        ui.icon("folder_open").classes("ss-lib-empty-icon")
        ui.label("No decks under this folder").classes("ss-lib-empty-title")
        ui.label(str(registry.root)).classes("ss-mono ss-lib-path")
        ui.label(
            "A deck is a PDF with a matching .narration file beside it. "
            "Relaunch from your decks folder, or pass --root."
        ).classes("ss-mono ss-lib-empty-hint")


async def _fill_stats(cards: list[tuple[DeckEntry, ui.label]]) -> None:
    """Fill in each deck's counts off the event loop, one deck at a time.

    Reading a PDF's page ids is fast but not free, and a course can hold dozens
    of decks; doing it after first paint keeps the list instant either way.
    """
    for entry, label in cards:
        try:
            stats = await run.io_bound(deck_stats, entry)
        except Exception as exc:
            logger.debug("stats pass failed for %s: %s", entry.pdf_path, exc)
            stats = None
        if stats is None:
            label.set_text("unreadable")
            label.classes(add="ss-lib-stats-bad")
            continue
        label.set_text(stats.summary)
        label.classes(add="ss-lib-stats-ok" if stats.complete else "ss-lib-stats-partial")
