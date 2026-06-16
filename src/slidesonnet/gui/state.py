"""Editor state — deck navigation, edits, and actions, independent of NiceGUI.

Keeping this UI-free means the editor's logic (parsing edits back into the
sidecar grammar, saving, synthesizing, previewing, exporting) is unit-testable
without a browser, and stays under ``mypy --strict``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from slidesonnet import api
from slidesonnet.audio.synth import SpeechRef, ref_cache_status
from slidesonnet.audio.track import Cue
from slidesonnet.cache import audio_dir, render_dir
from slidesonnet.config import default_config_path, load_config
from slidesonnet.deck import (
    default_sidecar_path,
    dedupe_page_ids,
    load_deck,
    save_deck,
    unique_real_ids,
)
from slidesonnet.diagnostics import Diagnostic
from slidesonnet.exceptions import ConfigError
from slidesonnet.narration.format import SidecarError
from slidesonnet.narration.model import PageNarration, Segment, Transition
from slidesonnet.pdf.reader import rasterize, read_page_ids
from slidesonnet.tts import BACKENDS, create_tts

# Audio cache-status scans stat() every speech segment; renders ask several
# questions per repaint. One scan is shared for this long before re-checking.
_AUDIO_SCAN_TTL = 1.0

SlideStatus = Literal["error", "warning", "ready", "empty"]


def _stat_stamp(path: Path) -> tuple[float, int]:
    """A (mtime, size) change-detection signature for *path*; (0, 0) if missing."""
    try:
        st = path.stat()
    except OSError:
        return (0.0, 0)
    return (st.st_mtime, st.st_size)


class EditorState:
    """Mutable state behind the narration editor."""

    def __init__(self, pdf_path: Path, *, sidecar_path: Path | None = None) -> None:
        self.pdf_path = pdf_path.resolve()
        self.sidecar_path = sidecar_path or default_sidecar_path(self.pdf_path)
        self.config = load_config(self.pdf_path)
        self.index = 0
        self._images: list[Path] | None = None
        # (pdf (mtime, size) stamp, deduped page ids, dedupe diagnostics)
        self._page_cache: tuple[tuple[float, int], list[str], list[Diagnostic]] | None = None
        self._audio_scan: tuple[float, list[tuple[SpeechRef, bool]]] | None = None
        self.source_error: str | None = None
        self.reload()
        self._stamps = self._source_stamps()

    # ---- loading -------------------------------------------------------
    def reload(self) -> None:
        self.deck, self.diagnostics = load_deck(
            self.pdf_path, sidecar_path=self.sidecar_path, pages=self._read_pages_cached()
        )
        self._audio_scan = None  # narration changed; cached audio-status is stale

    def _read_pages_cached(self) -> tuple[list[str], list[Diagnostic]]:
        """Page ids + dedupe diagnostics, re-reading the PDF only when it changed.

        Every commit saves and reloads; without this, each text-field blur
        re-opens the PDF and walks every page — a visible stall on big decks.
        """
        stamp = _stat_stamp(self.pdf_path)
        if self._page_cache is None or self._page_cache[0] != stamp:
            ids, diags = dedupe_page_ids(read_page_ids(self.pdf_path))
            self._page_cache = (stamp, ids, diags)
        _, ids, diags = self._page_cache
        return list(ids), list(diags)

    # ---- source watching -------------------------------------------------
    def _source_stamps(self) -> dict[str, tuple[float, int]]:
        """A (mtime, size) signature per source file.

        Mtime alone misses a recompile when the filesystem reports a coarse
        timestamp (e.g. a PDF rebuilt within the same second, or WSL's
        second-granularity mtimes on Windows-mounted drives); a size change
        catches those. A missing file is a stable (0, 0).
        """
        sources = (self.pdf_path, self.sidecar_path, default_config_path(self.pdf_path))
        return {str(path): _stat_stamp(path) for path in sources}

    def poll_sources(self) -> bool:
        """Reload when the PDF, sidecar, or config changed on disk; True if so.

        The editor polls this so external edits (a recompile, hand-editing the
        sidecar) appear live. Saves made through this state refresh the
        baseline themselves and never trigger a reload.
        """
        current = self._source_stamps()
        if current == self._stamps:
            return False
        try:
            config = load_config(self.pdf_path)
            deck, diagnostics = load_deck(
                self.pdf_path, sidecar_path=self.sidecar_path, pages=self._read_pages_cached()
            )
        except (ConfigError, SidecarError) as exc:
            # A parseable-but-broken source (bad TOML, bad sidecar grammar)
            # won't fix itself by waiting — keep the last good deck but tell
            # the user. Absorb the baseline so this reports once, not per tick.
            self._stamps = current
            self.source_error = str(exc)
            return True
        except Exception:
            # mid-recompile: the PDF (or config) is missing or half-written.
            # Keep showing the last good deck; the next tick retries.
            return False
        if current[str(self.pdf_path)] != self._stamps[str(self.pdf_path)]:
            self._images = None  # page images are stale; re-rasterize on demand
        self._stamps = current
        self.config = config
        self.deck, self.diagnostics = deck, diagnostics
        self.source_error = None
        self._audio_scan = None
        self.go(self.index)  # clamp in case the deck shrank
        return True

    def external_changes(self) -> set[str]:
        """Which sources changed on disk since the last baseline: pdf/sidecar/config."""
        current = self._source_stamps()
        labels = {
            str(self.pdf_path): "pdf",
            str(self.sidecar_path): "sidecar",
            str(default_config_path(self.pdf_path)): "config",
        }
        return {labels[key] for key, stamp in current.items() if stamp != self._stamps[key]}

    def ensure_images(self) -> list[Path]:
        """Rasterize page images on first use (needs pdftoppm)."""
        if self._images is None:
            self._images = rasterize(self.pdf_path, render_dir(self.pdf_path) / "pages")
        return self._images

    # ---- navigation ----------------------------------------------------
    @property
    def page_count(self) -> int:
        return len(self.deck.pages)

    @property
    def current_id(self) -> str:
        return self.deck.pages[self.index]

    @property
    def current_block(self) -> PageNarration:
        return self.deck.page_narration(self.current_id)

    def go(self, index: int) -> None:
        self.index = max(0, min(index, self.page_count - 1))

    def next(self) -> None:
        self.go(self.index + 1)

    def prev(self) -> None:
        self.go(self.index - 1)

    def current_image(self) -> Path | None:
        images = self.ensure_images()
        return images[self.index] if self.index < len(images) else None

    # ---- editing -------------------------------------------------------
    def _next_page_id(self) -> str | None:
        nxt = self.index + 1
        return self.deck.pages[nxt] if nxt < self.page_count else None

    def replace_block(
        self,
        segments: list[Segment],
        *,
        transition_in: Transition | None = None,
        transition_out: Transition | None = None,
    ) -> bool:
        """Replace the current slide's block wholesale, then persist; False if unsafe.

        Unsafe: the page has no slide-id to key the block ("@" would corrupt the
        sidecar grammar). A block that ends up empty (no segments, plain cuts)
        is dropped from the sidecar entirely.

        Setting a non-cut ``transition_out`` clears the *next* slide's
        ``transition_in`` so a boundary is only ever specified on the earlier
        slide (see :func:`diagnostics.boundary_transition`).
        """
        if not self.current_id:
            return False
        tin = transition_in or Transition()
        tout = transition_out or Transition()
        empty = not segments and tin.kind == "cut" and tout.kind == "cut"
        old = self.deck.narration.get(self.current_id)
        if empty:
            if old is None:
                return False  # already absent — nothing to save, nothing to revoke
            self.deck.narration.pop(self.current_id)
            self._write_and_reload()
            return True
        base = old if old is not None else PageNarration(slide_id=self.current_id)
        new_block = base.with_content(segments, transition_in=tin, transition_out=tout)
        nxt = self._next_page_id() if tout.kind != "cut" else None
        clears_next = bool(
            nxt
            and nxt in self.deck.narration
            and self.deck.narration[nxt].transition_in.kind != "cut"
        )
        if old == new_block and not clears_next:
            return False  # a no-op blur/save: don't reload, flash, or revoke the track
        self.deck.narration[self.current_id] = new_block
        if clears_next and nxt is not None:
            self.deck.narration[nxt].transition_in = Transition()
        self._write_and_reload()
        return True

    def _write_and_reload(self) -> None:
        """Persist the deck, re-run diagnostics, and absorb our own sidecar write.

        Only the sidecar baseline is refreshed — refreshing the others here
        would mask a PDF/config change that landed since the last poll.
        """
        save_deck(self.deck)
        self.reload()
        self._stamps[str(self.sidecar_path)] = _stat_stamp(self.sidecar_path)

    # ---- unattached narration (slide dropped/renamed by a recompile) -------
    def orphan_blocks(self) -> list[PageNarration]:
        """Narration blocks whose slide-id matches no PDF page (sidecar order)."""
        on_page = set(self.deck.pages)
        return [b for sid, b in self.deck.narration.items() if sid not in on_page]

    def unnarrated_pages(self) -> list[str]:
        """Page ids an orphan could attach to (no narration yet), in page order."""
        return [sid for sid in unique_real_ids(self.deck.pages) if not self.has_narration(sid)]

    def attach_orphan(self, orphan_id: str, target_id: str) -> None:
        """Move an orphan block's narration onto the page *target_id* and save."""
        if target_id not in self.deck.pages:
            raise ValueError(f"'{target_id}' is not a page in the deck")
        if self.has_narration(target_id):
            raise ValueError(f"slide '{target_id}' already has narration")
        block = self.deck.narration.pop(orphan_id)
        self.deck.narration[target_id] = block.rekeyed(target_id)
        self._write_and_reload()

    def append_orphan_to_current(self, orphan_id: str) -> None:
        """Append an orphan block's segments onto the current slide, then save.

        Unlike :meth:`attach_orphan` (which targets an *empty* slide), this
        merges the orphan's utterances/pauses after whatever the current slide
        already has — the way to fold dropped narration back into a live slide.
        """
        if not self.current_id:
            raise ValueError("this page has no slide-id to append to")
        if orphan_id not in self.deck.narration:
            raise ValueError(f"no narration block '{orphan_id}'")
        orphan = self.deck.narration.pop(orphan_id)
        target = self.current_block
        self.deck.narration[self.current_id] = target.with_content(
            [*target.segments, *orphan.segments]
        )
        self._write_and_reload()

    def delete_orphan(self, orphan_id: str) -> None:
        """Drop an orphan block (and its text) from the sidecar."""
        self.deck.narration.pop(orphan_id, None)
        self._write_and_reload()

    # ---- voices -----------------------------------------------------------
    def voice_options(self) -> list[str]:
        """Voice choices for the editor: named presets first, then engine voices.

        The engine reports its own pickable voice set (Kokoro's fixed English
        voices; cloud engines with account-specific ids report none), plus the
        deck's named presets from ``slidesonnet.toml``. The per-utterance voice
        is otherwise None (the deck default).
        """
        opts: list[str] = sorted(self.config.voices)  # named presets
        opts += [v for v in create_tts(self.config.tts).list_voices() if v not in opts]
        return opts

    def default_voice(self) -> str | None:
        """The deck-wide voice an utterance with no explicit voice falls back to."""
        return create_tts(self.config.tts).default_voice()

    # ---- synthesis cost ---------------------------------------------------
    @property
    def tts_is_paid(self) -> bool:
        """True when the configured TTS backend spends API credits."""
        return BACKENDS[self.config.tts.backend].paid

    def _audio_status(self) -> list[tuple[SpeechRef, bool]]:
        """Deck-wide (segment, is_cached) scan, shared across a render tick.

        Refreshed after at most _AUDIO_SCAN_TTL seconds (so audio synthesized
        by an external CLI run still shows up) and invalidated outright on
        reload and after this state's own synthesis actions.
        """
        now = time.monotonic()
        if self._audio_scan is None or now - self._audio_scan[0] > _AUDIO_SCAN_TTL:
            scan = ref_cache_status(self.deck, self.config, audio_dir(self.pdf_path))
            self._audio_scan = (now, scan)
        return self._audio_scan[1]

    def uncached_count(self, slide_id: str) -> int:
        """How many of *slide_id*'s speech segments a synthesis run would generate."""
        return sum(
            1 for ref, cached in self._audio_status() if ref.slide_id == slide_id and not cached
        )

    def uncached_total(self) -> int:
        """How many speech segments across the deck a synthesis run would generate."""
        return sum(1 for _ref, cached in self._audio_status() if not cached)

    def speech_cached_flags(self) -> list[bool]:
        """Per speech segment of the current slide: True where its audio is cached."""
        if not self.current_id:
            return []
        current = self.current_id
        return [cached for ref, cached in self._audio_status() if ref.slide_id == current]

    def ungenerated_ids(self) -> set[str]:
        """Slide-ids with at least one speech segment that has no cached audio."""
        return {ref.slide_id for ref, cached in self._audio_status() if not cached}

    # ---- actions -------------------------------------------------------
    # Actions pass engine=None so api re-reads the on-disk config at action
    # time — the editor's cached config can be up to one poll interval stale,
    # and running a stale (possibly paid) backend is a money-relevant surprise.
    def synth_current(self, *, force: bool = False) -> int:
        self._audio_scan = None
        return api.synthesize_deck(
            self.pdf_path,
            sidecar_path=self.sidecar_path,
            only_ids={self.current_id},
            force=force,
        )

    def synth_segment(self, speech_index: int, *, force: bool = False) -> int:
        """Synthesize one speech segment of the current slide (by speech index)."""
        self._audio_scan = None
        return api.synthesize_deck(
            self.pdf_path,
            sidecar_path=self.sidecar_path,
            only_segments={(self.current_id, speech_index)},
            force=force,
        )

    def synth_targets(self, targets: set[tuple[str, int]], *, force: bool = False) -> int:
        """Synthesize specific ``(slide_id, speech_index)`` segments — the worker's call.

        Re-reads the on-disk config (engine=None) like the other actions, so a
        live config edit takes effect. UI-free: the background queue drives this.
        """
        self._audio_scan = None
        return api.synthesize_deck(
            self.pdf_path,
            sidecar_path=self.sidecar_path,
            only_segments=set(targets),
            force=force,
        )

    def targets_for_slide(
        self, slide_id: str, *, exclude_speech: int | None = None
    ) -> set[tuple[str, int]]:
        """Uncached ``(slide_id, speech_index)`` clips of *slide_id* (auto-build).

        *exclude_speech* drops the utterance the user is mid-editing, so we never
        synthesize half-typed text.
        """
        return {
            (ref.slide_id, ref.speech_index)
            for ref, cached in self._audio_status()
            if ref.slide_id == slide_id and not cached and ref.speech_index != exclude_speech
        }

    def all_targets(self, *, only_id: str | None = None) -> set[tuple[str, int]]:
        """Every ``(slide_id, speech_index)`` in the deck (or just *only_id*'s).

        Play awaits the in-flight jobs covering these so it never races a
        background generation of a clip it's about to need.
        """
        out: set[tuple[str, int]] = set()
        for slide_id in self.deck.pages:
            if only_id is not None and slide_id != only_id:
                continue
            block = self.deck.page_narration(slide_id)
            for i in range(len(block.speech_segments)):
                out.add((slide_id, i))
        return out

    def targets_for_sweep(self, *, exclude_id: str | None = None) -> set[tuple[str, int]]:
        """Every uncached clip across the deck except those on *exclude_id*.

        The one-time fill when auto-build is enabled: skip the focused slide
        (its own edits drive the incremental path) and queue the rest.
        """
        return {
            (ref.slide_id, ref.speech_index)
            for ref, cached in self._audio_status()
            if not cached and ref.slide_id != exclude_id
        }

    def synth_all(self) -> int:
        self._audio_scan = None
        return api.synthesize_deck(self.pdf_path, sidecar_path=self.sidecar_path)

    def preview_current(self) -> api.Preview:
        self._audio_scan = None  # building a preview synthesizes missing clips
        return api.build_preview(
            self.pdf_path, sidecar_path=self.sidecar_path, only_id=self.current_id
        )

    def preview_deck(self) -> api.Preview:
        self._audio_scan = None
        return api.build_preview(self.pdf_path, sidecar_path=self.sidecar_path)

    def export(self, output: Path, *, silent: bool = False) -> api.ExportResult:
        return api.export(
            self.pdf_path,
            output,
            sidecar_path=self.sidecar_path,
            silent=silent,
        )

    # ---- per-slide status (filmstrip) -----------------------------------
    def has_narration(self, slide_id: str) -> bool:
        block = self.deck.narration.get(slide_id)
        return block is not None and bool(block.segments)

    def status_for(self, slide_id: str) -> SlideStatus:
        """Worst finding for a slide; un-narrated alone reads as 'empty'."""
        severities = {
            d.severity
            for d in self.diagnostics
            if d.slide_id == slide_id and d.code != "missing-narration"
        }
        if "error" in severities:
            return "error"
        if "warning" in severities:
            return "warning"
        return "ready" if self.has_narration(slide_id) else "empty"

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == "error")

    def diagnostics_for_current(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.slide_id == self.current_id]


def cue_start(cues: list[Cue], slide_id: str) -> float | None:
    """Start time of *slide_id* in a deck-preview cue sheet, or None if absent."""
    for start, sid in cues:
        if sid == slide_id:
            return start
    return None
