"""Editor state — deck navigation, edits, and actions, independent of NiceGUI.

Keeping this UI-free means the editor's logic (parsing edits back into the
sidecar grammar, saving, synthesizing, previewing, exporting) is unit-testable
without a browser, and stays under ``mypy --strict``.
"""

from __future__ import annotations

import logging
import time
import wave
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

from slidesonnet import api
from slidesonnet.audio.synth import SpeechRef, _ref_targets, ref_cache_status
from slidesonnet.hashing import audio_cache_path_or_alt
from slidesonnet.timing import word_count
from slidesonnet.audio.track import Cue
from slidesonnet.cache import audio_dir, render_dir
from slidesonnet.config import Config, default_config_path, load_config
from slidesonnet.deck import (
    default_sidecar_path,
    dedupe_page_ids,
    load_deck,
    relativize_voice_files,
    resolve_voice_files,
    save_deck,
    unique_real_ids,
)
from slidesonnet.diagnostics import Diagnostic, boundary_transition, voice_diagnostics
from slidesonnet.exceptions import ConfigError
from slidesonnet.narration.format import SidecarError
from slidesonnet.narration.model import Deck, PageNarration, Segment, Transition
from slidesonnet.models import Backend, VoiceConfig, resolve_voice
from slidesonnet.pdf.reader import rasterize, read_page_ids
from slidesonnet.tts import BACKENDS, available_backends, create_tts

logger = logging.getLogger(__name__)

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


def _wav_seconds(path: Path) -> float | None:
    """Audio length from a WAV header (cheap); None for non-WAV or unreadable."""
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate()
            return wf.getnframes() / rate if rate else None
    except (wave.Error, OSError):
        return None


class EditorState:
    """Mutable state behind the narration editor."""

    def __init__(self, pdf_path: Path, *, sidecar_path: Path | None = None) -> None:
        self.pdf_path = pdf_path.resolve()
        self.sidecar_path = sidecar_path or default_sidecar_path(self.pdf_path)
        self.config = load_config(self.pdf_path)
        # The generation engine is chosen in the GUI (session-only, never written
        # to disk). None = fall back to the config default. See active_backend.
        self.selected_backend: Backend | None = None
        self.index = 0
        self._images: list[Path] | None = None
        # (pdf (mtime, size) stamp, deduped page ids, dedupe diagnostics)
        self._page_cache: tuple[tuple[float, int], list[str], list[Diagnostic]] | None = None
        self._audio_scan: tuple[float, list[tuple[SpeechRef, bool]]] | None = None
        # voice-unmapped diagnostics, recomputed when the deck or active engine
        # changes (keyed on (deck identity, backend) so it tracks the engine pick)
        self._voice_diags: tuple[tuple[int, str], list[Diagnostic]] | None = None
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

    def _prev_page_id(self) -> str | None:
        prv = self.index - 1
        return self.deck.pages[prv] if prv >= 0 else None

    @property
    def incoming_transition(self) -> Transition:
        """The effective transition *entering* the current slide.

        A boundary is one transition shared by two slides; it lives canonically on
        the earlier slide's ``transition_out`` (see
        :func:`diagnostics.boundary_transition`). So a slide's incoming transition
        is its boundary with the previous slide — they are the same thing, and the
        editor shows them as such. The first slide has no previous, so its own
        ``transition_in`` stands alone as the deck-open animation.
        """
        prev_id = self._prev_page_id()
        if prev_id is None:
            return self.current_block.transition_in
        return boundary_transition(self.deck.page_narration(prev_id), self.current_block)

    def _set_transition_out(self, slide_id: str, tr: Transition) -> bool:
        """Set *slide_id*'s ``transition_out`` (dropping an emptied block); changed?"""
        old = self.deck.narration.get(slide_id)
        base = old if old is not None else PageNarration(slide_id=slide_id)
        if base.transition_out == tr:
            return False
        new = base.with_content(base.segments, transition_out=tr)
        if new.is_empty:
            if old is None:
                return False
            self.deck.narration.pop(slide_id)
        else:
            self.deck.narration[slide_id] = new
        return True

    def _clear_transition_in(self, slide_id: str) -> bool:
        """Reset *slide_id*'s ``transition_in`` to a cut (dropping an emptied block)."""
        old = self.deck.narration.get(slide_id)
        if old is None or old.transition_in.kind == "cut":
            return False
        new = old.with_content(old.segments, transition_in=Transition())
        if new.is_empty:
            self.deck.narration.pop(slide_id)
        else:
            self.deck.narration[slide_id] = new
        return True

    def replace_block(
        self,
        segments: list[Segment],
        *,
        transition_in: Transition | None = None,
        transition_out: Transition | None = None,
    ) -> bool:
        """Replace the current slide's block wholesale, then persist; False if unsafe.

        Unsafe: the page has no slide-id to key the block ("@" would corrupt the
        sidecar grammar). A block that ends up empty (no segments, plain cuts) is
        dropped from the sidecar entirely.

        A boundary is only ever stored on the earlier slide's ``transition_out``,
        so the two transition controls stay consistent: *transition_in* is the
        boundary with the previous slide — a real change to it is written to that
        slide's ``transition_out`` (and this slide's own ``transition_in`` cleared),
        and a non-cut *transition_out* clears the *next* slide's ``transition_in``.
        The first slide keeps its own ``transition_in`` (the deck-open animation).
        """
        if not self.current_id:
            return False
        tin = transition_in or Transition()
        tout = transition_out or Transition()
        cur_id = self.current_id
        prev_id = self._prev_page_id()
        nxt_id = self._next_page_id()

        changed = False
        # The incoming transition belongs to the boundary with the previous slide.
        # Only move it (onto that slide's out, clearing ours) when it actually
        # changed — a plain blur/navigation must not rewrite the sidecar.
        if prev_id is not None and tin != self.incoming_transition:
            changed |= self._set_transition_out(prev_id, tin)
            own_in = Transition()
        elif prev_id is None:
            own_in = tin  # first slide: its own deck-open transition
        else:
            own_in = self.current_block.transition_in  # unchanged: leave it in place

        cur = self.deck.narration.get(cur_id)
        cur_base = cur if cur is not None else PageNarration(slide_id=cur_id)
        new_cur = cur_base.with_content(segments, transition_in=own_in, transition_out=tout)
        if new_cur.is_empty:
            if cur is not None:
                self.deck.narration.pop(cur_id)
                changed = True
        elif cur != new_cur:
            self.deck.narration[cur_id] = new_cur
            changed = True

        if tout.kind != "cut" and nxt_id is not None:
            changed |= self._clear_transition_in(nxt_id)

        if not changed:
            return False  # a no-op blur/save: don't reload, flash, or revoke the track
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
        self._prune_stale_audio()

    def _prune_stale_audio(self) -> None:
        """Reclaim local clips orphaned by this edit (cheap to regenerate).

        Best-effort: a sweep failure must never cost the user their saved edit,
        so any error is logged and swallowed. Paid audio is left untouched.
        """
        try:
            from slidesonnet.clean import prune_local_orphans

            prune_local_orphans(self.pdf_path)
        except Exception:  # pragma: no cover - defensive: never break a save
            logger.warning("Could not prune stale audio for %s", self.pdf_path, exc_info=True)

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

    # ---- engine selection (GUI, session-only) -----------------------------
    @property
    def active_backend(self) -> Backend:
        """The engine generation actually uses now: the GUI pick, else the config."""
        return self.selected_backend or self.config.tts.backend

    def set_backend(self, backend: Backend) -> None:
        """Pick the generation engine for this session (never written to disk).

        Cache status is per-engine (the audio filename folds in the backend), so
        the badge/uncached scan is invalidated to re-evaluate against the pick.
        """
        self.selected_backend = backend
        self._audio_scan = None

    def backend_options(self) -> list[str]:
        """Engine names for the GUI picker: the installed ones plus the active one."""
        return sorted(set(available_backends()) | {self.active_backend})

    def _active_config(self) -> Config:
        """The config with its backend swapped to the session pick (else as loaded)."""
        if self.selected_backend is None:
            return self.config
        return replace(self.config, tts=replace(self.config.tts, backend=self.selected_backend))

    # ---- voices -----------------------------------------------------------
    def voice_options(self) -> list[str]:
        """The deck's *named* voices for the per-utterance picker — engine ids excluded.

        Names come from the deck's portable voice layer (the sidecar ``voices:``
        block) merged with the shared ``slidesonnet.toml`` library, so the same
        names show under any engine. An utterance references a name and the engine
        voice is resolved through the map; raw engine ids are deliberately *not*
        offered here (define names in the Voices dialog). Empty when the deck has
        no named voices — the picker then offers only the deck default.
        """
        cfg = self._active_config()
        names = set(cfg.voices) | set(self.deck.voices)  # deck wins, but only names matter here
        return sorted(names)

    def resolved_engine_voice(self, name: str) -> str | None:
        """The active engine's voice id a named voice resolves to (None if unmapped).

        Drives the picker label ``name (engine voice)``. Uses the same merged voice
        map and active backend as synthesis, so the label shows the voice that will
        actually speak. A name with no mapping for the active engine returns None.
        """
        cfg = self._active_config()
        voices = {**cfg.voices, **self.deck.voices}  # deck wins, mirroring synthesis
        return resolve_voice(name, voices, cfg.tts.backend)

    def default_voice_label(self) -> str | None:
        """The deck's *named* default-voice, for the picker's unset placeholder.

        Returns the ``default-voice`` name when one is declared, else None — the
        picker says "deck default" rather than surfacing the engine's own voice id
        (an engine-specific id has no place in the named per-utterance picker).
        """
        return self.deck.default_voice or None

    def engine_voice_choices(self, backend: str) -> tuple[list[str], str | None]:
        """``(pickable voices, default voice)`` for *backend* — drives the Voices dialog.

        Kokoro and Qwen3 (CustomVoice) expose a fixed voice list, so the dialog
        offers a combobox started at the engine default; ElevenLabs ids are
        account-specific (no list) so that field stays free text. ElevenLabs is not
        instantiated here — its client needs an API key, and it has no list anyway.
        """
        if backend == "elevenlabs":
            return [], (self.config.tts.elevenlabs_voice_id or None)
        engine = create_tts(replace(self.config.tts, backend=cast(Backend, backend)))
        return list(engine.list_voices()), engine.default_voice()

    def voice_map_for_display(self) -> dict[str, VoiceConfig]:
        """The deck's portable voice map, with file voices shown relative to the deck.

        The in-memory deck holds absolute file-voice paths (so the engine can load
        a ``.pt`` regardless of cwd); the editor shows — and round-trips — the
        portable relative form. Returns a fresh copy safe for the GUI to mutate
        before handing back to :meth:`edit_voices`.
        """
        return relativize_voice_files(self.deck.voices, self.sidecar_path.resolve().parent)

    def edit_voices(self, voices: dict[str, VoiceConfig], default_voice: str | None) -> bool:
        """Replace the deck's portable voice map + default-voice, then save; changed?

        Dropping ``preamble_source`` makes the save regenerate the preamble
        canonically from the edited map (a deck whose map is untouched never
        reaches here, so its hand-written preamble round-trips byte-stable).
        Incoming file-voice paths are resolved to absolute (mirroring load), so an
        unchanged map compares equal and writes nothing. The reload relights the
        voice-unmapped diagnostics against the new map and active engine.
        """
        resolved = resolve_voice_files(voices, self.sidecar_path.resolve().parent)
        default_voice = default_voice or None
        if resolved == self.deck.voices and default_voice == self.deck.default_voice:
            return False
        self.deck.voices = resolved
        self.deck.default_voice = default_voice
        self.deck.preamble_source = None  # regenerate the preamble from the edited map
        self._write_and_reload()
        return True

    # ---- synthesis cost ---------------------------------------------------
    @property
    def tts_is_paid(self) -> bool:
        """True when the active TTS backend spends API credits."""
        return BACKENDS[self.active_backend].paid

    @property
    def tts_is_realtime(self) -> bool:
        """True when synthesis is fast enough to fire unattended on every edit.

        False for a heavy local model (Qwen3): free, but too slow to
        auto-generate. The auto-build gate is ``paid OR not realtime``.
        """
        return BACKENDS[self.active_backend].realtime

    def model_warmup_pending(self) -> bool:
        """True when the active engine still owes a heavy one-time model load.

        Lets the editor show a distinct "Loading model…" status before the first
        Qwen3 generation, instead of a silent multi-second pause. Cheap to call —
        the engine constructor never loads the model; this only checks the
        process-wide warm cache.
        """
        return not create_tts(self._active_config().tts).is_warm()

    def warm_active_engine(self) -> None:
        """Load the active engine's model into the process (blocking).

        Meant to run off the event loop (``run.io_bound``) so the editor can warm
        a heavy engine the moment it's picked, instead of stalling on first play.
        A no-op for light engines; the warm cache is process-wide, so a later
        synth (or a fresh engine instance) reuses the loaded model.
        """
        create_tts(self._active_config().tts).warm()

    def _audio_status(self) -> list[tuple[SpeechRef, bool]]:
        """Deck-wide (segment, is_cached) scan, shared across a render tick.

        Refreshed after at most _AUDIO_SCAN_TTL seconds (so audio synthesized
        by an external CLI run still shows up) and invalidated outright on
        reload and after this state's own synthesis actions.
        """
        now = time.monotonic()
        if self._audio_scan is None or now - self._audio_scan[0] > _AUDIO_SCAN_TTL:
            scan = ref_cache_status(self.deck, self._active_config(), audio_dir(self.pdf_path))
            self._audio_scan = (now, scan)
        return self._audio_scan[1]

    def jobs_context(self) -> tuple[Deck, Config, Path]:
        """``(deck, config, audio_dir)`` for the background JobQueue.

        Uses :meth:`_active_config` — the on-disk config with the *session-selected*
        backend applied — so the queue's cache lookups match the filmstrip sweep and
        the actual synthesis. Passing the raw on-disk config instead lets clips cached
        under one engine mask the picked engine's missing audio, so ``enqueue`` skips
        every clip ("queued 0" despite N missing in the filmstrip).
        """
        return (self.deck, self._active_config(), audio_dir(self.pdf_path))

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

    def est_gen_seconds(self, slide_id: str, speech_index: int) -> float | None:
        """Rough seconds to generate a clip: word-count → audio secs × engine RTF.

        Used only to show an *estimated* progress while a clip generates (elapsed
        vs this). None if the segment can't be found.
        """
        speeches = self.deck.page_narration(slide_id).speech_segments
        if speech_index >= len(speeches):
            return None
        audio_secs = word_count(speeches[speech_index].text) / 150.0 * 60.0
        return max(0.5, audio_secs * BACKENDS[self.active_backend].rtf)

    def current_clip_meta(self) -> dict[int, tuple[float | None, int]]:
        """Per cached segment of the current slide: ``(audio seconds, file bytes)``.

        Duration is read cheaply from the WAV header (Kokoro/Qwen3 write WAV);
        other formats report size only (no ffprobe per render). One cache scan.
        """
        out: dict[int, tuple[float | None, int]] = {}
        current = self.current_id
        if not current:
            return out
        cfg = self._active_config()
        for ref, target in _ref_targets(self.deck, cfg, audio_dir(self.pdf_path)):
            if ref.slide_id != current:
                continue
            path = audio_cache_path_or_alt(target)
            if path is not None:
                out[ref.speech_index] = (_wav_seconds(path), path.stat().st_size)
        return out

    def ungenerated_ids(self) -> set[str]:
        """Slide-ids with at least one speech segment that has no cached audio."""
        return {ref.slide_id for ref, cached in self._audio_status() if not cached}

    # ---- actions -------------------------------------------------------
    # Actions pass engine=selected_backend: the GUI's session pick wins, and
    # api re-reads the on-disk config for the rest (voices, engine params). When
    # nothing is picked (None) api falls back to the config's backend — re-read
    # fresh at action time, so a stale (possibly paid) cached backend is never run.
    def synth_current(self, *, force: bool = False) -> int:
        self._audio_scan = None
        return api.synthesize_deck(
            self.pdf_path,
            sidecar_path=self.sidecar_path,
            only_ids={self.current_id},
            force=force,
            engine=self.selected_backend,
        )

    def synth_segment(self, speech_index: int, *, force: bool = False) -> int:
        """Synthesize one speech segment of the current slide (by speech index)."""
        self._audio_scan = None
        return api.synthesize_deck(
            self.pdf_path,
            sidecar_path=self.sidecar_path,
            only_segments={(self.current_id, speech_index)},
            force=force,
            engine=self.selected_backend,
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
            engine=self.selected_backend,
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
        return api.synthesize_deck(
            self.pdf_path, sidecar_path=self.sidecar_path, engine=self.selected_backend
        )

    def preview_current(self) -> api.Preview:
        self._audio_scan = None  # building a preview synthesizes missing clips
        return api.build_preview(
            self.pdf_path,
            sidecar_path=self.sidecar_path,
            only_id=self.current_id,
            engine=self.selected_backend,
        )

    def preview_deck(self) -> api.Preview:
        self._audio_scan = None
        return api.build_preview(
            self.pdf_path, sidecar_path=self.sidecar_path, engine=self.selected_backend
        )

    def export(self, output: Path, *, silent: bool = False) -> api.ExportResult:
        return api.export(
            self.pdf_path,
            output,
            sidecar_path=self.sidecar_path,
            silent=silent,
            engine=self.selected_backend,
        )

    # ---- per-slide status (filmstrip) -----------------------------------
    def has_narration(self, slide_id: str) -> bool:
        block = self.deck.narration.get(slide_id)
        return block is not None and bool(block.segments)

    def all_diagnostics(self) -> list[Diagnostic]:
        """Load-time diagnostics plus voice-unmapped warnings for the active engine.

        The voice warnings depend on the picked engine (a named voice may map for
        Kokoro but not Qwen3), so they can't be baked in at load time — they're
        recomputed when the deck or the active backend changes and merged in here,
        so a mid-session engine switch relights the affected slides.
        """
        sig = (id(self.deck), self.active_backend)
        if self._voice_diags is None or self._voice_diags[0] != sig:
            voices = {**self.config.voices, **self.deck.voices}
            diags = voice_diagnostics(
                list(self.deck.narration.values()),
                voices,
                self.deck.default_voice,
                self.active_backend,
            )
            self._voice_diags = (sig, diags)
        return self.diagnostics + self._voice_diags[1]

    def status_for(self, slide_id: str) -> SlideStatus:
        """Worst finding for a slide; un-narrated alone reads as 'empty'."""
        severities = {
            d.severity
            for d in self.all_diagnostics()
            if d.slide_id == slide_id and d.code != "missing-narration"
        }
        if "error" in severities:
            return "error"
        if "warning" in severities:
            return "warning"
        return "ready" if self.has_narration(slide_id) else "empty"

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.all_diagnostics() if d.severity == "error")

    def diagnostics_for_current(self) -> list[Diagnostic]:
        return [d for d in self.all_diagnostics() if d.slide_id == self.current_id]


def cue_start(cues: list[Cue], slide_id: str) -> float | None:
    """Start time of *slide_id* in a deck-preview cue sheet, or None if absent."""
    for start, sid in cues:
        if sid == slide_id:
            return start
    return None
