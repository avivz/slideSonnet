"""Per-deck services: revision-checked, serialized, atomic writes of the sidecar.

One :class:`DeckService` exists per deck in the process (see :func:`deck_service`),
shared by every editor tab and every API request. It owns the deck's write lock,
so two writers — a NiceGUI tab and an API client, or two API clients — can never
interleave a read-modify-write of the same sidecar.

Every write names the narration revision it was edited against. If the file on
disk has moved on (an agent edited it, another tab saved), the write is refused
with :class:`RevisionConflict` instead of silently undoing the other edit.

Work that doesn't need to finish before a save returns — reclaiming audio clips
the edit orphaned — runs afterwards on a debounced background timer (B3: saves
used to run the prune inline, on the UI event loop).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from slidesonnet.atomic import atomic_write_text
from slidesonnet.config import Config, default_config_path, load_config
from slidesonnet.deck import dedupe_page_ids, default_sidecar_path, load_deck, sidecar_text
from slidesonnet.diagnostics import Diagnostic
from slidesonnet.narration.format import SidecarError, parse_sidecar, serialize_block
from slidesonnet.narration.model import Deck
from slidesonnet.pdf.reader import read_page_ids
from slidesonnet.review import ops as review_ops
from slidesonnet.server.revisions import SourceRevisions, content_revision, text_revision

logger = logging.getLogger(__name__)

#: How long after the last save the orphaned-audio sweep waits (debounce).
PRUNE_DELAY_S = 0.75


class RevisionConflict(Exception):
    """The sidecar changed since the caller read it; nothing was written."""

    def __init__(self, expected: str, current: str) -> None:
        super().__init__(f"narration changed on disk (expected {expected}, found {current})")
        self.expected = expected
        self.current = current


@dataclass
class LoadedDeck:
    """A deck as read from disk, with the revisions it was read at."""

    deck: Deck
    diagnostics: list[Diagnostic]
    config: Config
    revisions: SourceRevisions


@dataclass(frozen=True)
class WriteResult:
    """Outcome of a write: whether anything changed, and the revision now on disk."""

    changed: bool
    revision: str


class DeckService:
    """Reads and writes one deck's sources. Thread-safe; blocking — call off the loop."""

    def __init__(self, pdf_path: Path, sidecar_path: Path | None = None) -> None:
        self.pdf_path = Path(pdf_path).resolve()
        self.sidecar_path = (sidecar_path or default_sidecar_path(self.pdf_path)).resolve()
        self.config_path = default_config_path(self.pdf_path)
        self._write_lock = threading.RLock()
        #: Serializes preview/export assembly: they share the render directory.
        self.render_lock = threading.Lock()
        self._pages: tuple[str, list[str], list[Diagnostic]] | None = None
        self._pages_lock = threading.Lock()
        self._prune_timer: threading.Timer | None = None
        self._prune_lock = threading.Lock()

    # ---- revisions ------------------------------------------------------
    def narration_revision(self) -> str:
        return content_revision(self.sidecar_path)

    def revisions(self) -> SourceRevisions:
        return SourceRevisions(
            narration=content_revision(self.sidecar_path),
            pdf=content_revision(self.pdf_path),
            config=content_revision(self.config_path),
            review=content_revision(review_ops.review_path(self.pdf_path)),
        )

    # ---- reading --------------------------------------------------------
    def page_ids(self) -> tuple[list[str], list[Diagnostic]]:
        """Deduped page ids + their diagnostics, re-read only when the PDF changed."""
        rev = content_revision(self.pdf_path)
        with self._pages_lock:
            if self._pages is None or self._pages[0] != rev:
                ids, diags = dedupe_page_ids(read_page_ids(self.pdf_path))
                self._pages = (rev, ids, diags)
            _, ids, diags = self._pages
        return list(ids), list(diags)

    def load(self) -> LoadedDeck:
        """Read the deck fresh from disk. Raises SidecarError/ConfigError when malformed."""
        revisions = self.revisions()
        config = load_config(self.pdf_path)
        deck, diagnostics = load_deck(
            self.pdf_path, sidecar_path=self.sidecar_path, pages=self.page_ids()
        )
        return LoadedDeck(deck=deck, diagnostics=diagnostics, config=config, revisions=revisions)

    # ---- writing --------------------------------------------------------
    def write(self, deck: Deck, *, expected_revision: str) -> WriteResult:
        """Persist *deck*'s narration if the sidecar is still at *expected_revision*.

        The check and the atomic replace happen under this deck's lock, so no
        other writer in the process can slip in between. (An external program
        that ignores the lock can still race us in the instant between the check
        and the rename; the next poll then reports its edit as a change.)
        """
        with self._write_lock:
            current = self.narration_revision()
            if current != expected_revision:
                raise RevisionConflict(expected_revision, current)
            text = sidecar_text(deck)
            if text_revision(text) == current:
                return WriteResult(changed=False, revision=current)
            edited = self._blocks_changed(text)
            atomic_write_text(self.sidecar_path, text)
            revision = text_revision(text)
        self._after_write(edited)
        return WriteResult(changed=True, revision=revision)

    def edit(self, expected_revision: str, mutate: Callable[[Deck], bool]) -> WriteResult:
        """Load, apply *mutate* (True when it changed the deck), and write — atomically.

        The whole read-modify-write holds the deck lock; *mutate* sees the deck
        exactly as it is at *expected_revision* or the edit is refused.
        """
        with self._write_lock:
            current = self.narration_revision()
            if current != expected_revision:
                raise RevisionConflict(expected_revision, current)
            loaded = self.load()
            if not mutate(loaded.deck):
                return WriteResult(changed=False, revision=current)
            return self.write(loaded.deck, expected_revision=current)

    def _blocks_changed(self, new_text: str) -> set[str]:
        """Slide ids whose narration block *new_text* changes vs the file on disk."""
        try:
            before = {
                b.slide_id: serialize_block(b)
                for b in parse_sidecar(self.sidecar_path.read_text(encoding="utf-8"))
            }
        except (OSError, SidecarError):
            before = {}
        try:
            after = {b.slide_id: serialize_block(b) for b in parse_sidecar(new_text)}
        except SidecarError:  # pragma: no cover - we just serialized it
            after = {}
        return {sid for sid in before.keys() | after.keys() if before.get(sid) != after.get(sid)}

    def _after_write(self, edited: set[str]) -> None:
        """Bookkeeping for a save: review edit notes now, the audio sweep later."""
        if edited:
            try:
                if review_ops.is_active(self.pdf_path):
                    for sid in sorted(edited):
                        review_ops.note_author_edit(self.pdf_path, sid)
            except Exception:  # never let bookkeeping cost the user their saved edit
                logger.warning("Could not note review edits for %s", self.pdf_path, exc_info=True)
        self.schedule_prune()

    # ---- orphaned-audio sweep (debounced, off the save path) ---------------
    def schedule_prune(self, delay: float = PRUNE_DELAY_S) -> None:
        """(Re)start the debounce timer for the orphaned-audio sweep."""
        with self._prune_lock:
            if self._prune_timer is not None:
                self._prune_timer.cancel()
            timer = threading.Timer(delay, self._run_prune)
            timer.daemon = True
            self._prune_timer = timer
            timer.start()

    def flush_prune(self) -> None:
        """Run a pending sweep now (tests, shutdown); no-op when none is pending."""
        with self._prune_lock:
            timer, self._prune_timer = self._prune_timer, None
        if timer is not None:
            timer.cancel()
            self._prune_now()

    def _run_prune(self) -> None:
        with self._prune_lock:
            self._prune_timer = None
        self._prune_now()

    def _prune_now(self) -> None:
        """Reclaim local clips orphaned by recent edits (cheap to regenerate).

        Best-effort: failures are logged and swallowed. Paid audio is untouched.
        """
        try:
            from slidesonnet.clean import prune_local_orphans

            with self._write_lock:  # never sweep against a half-applied edit
                prune_local_orphans(self.pdf_path)
        except Exception:
            logger.warning("Could not prune stale audio for %s", self.pdf_path, exc_info=True)


_services: dict[Path, DeckService] = {}
_services_lock = threading.Lock()


def deck_service(pdf_path: Path, sidecar_path: Path | None = None) -> DeckService:
    """The process-wide service for the deck at *pdf_path* (created on first use).

    Keyed by the resolved PDF path and sidecar, so every tab and request that
    touches one deck shares one lock.
    """
    pdf = Path(pdf_path).resolve()
    sidecar = (sidecar_path or default_sidecar_path(pdf)).resolve()
    with _services_lock:
        svc = _services.get(pdf)
        if svc is None or svc.sidecar_path != sidecar:
            svc = DeckService(pdf, sidecar)
            _services[pdf] = svc
        return svc


def flush_all_prunes() -> None:
    """Run every deck's pending audio sweep now (tests and shutdown)."""
    with _services_lock:
        services = list(_services.values())
    for svc in services:
        svc.flush_prune()


def reset_services() -> None:
    """Forget every deck service (test isolation). Pending sweeps are cancelled."""
    with _services_lock:
        services = list(_services.values())
        _services.clear()
    for svc in services:
        with svc._prune_lock:
            if svc._prune_timer is not None:
                svc._prune_timer.cancel()
                svc._prune_timer = None
