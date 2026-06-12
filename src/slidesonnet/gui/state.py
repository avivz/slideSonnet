"""Editor state — deck navigation, edits, and actions, independent of NiceGUI.

Keeping this UI-free means the editor's logic (parsing edits back into the
sidecar grammar, saving, synthesizing, previewing, exporting) is unit-testable
without a browser, and stays under ``mypy --strict``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from slidesonnet import api
from slidesonnet.audio.synth import cached_speech_flags, uncached_targets, ungenerated_ids
from slidesonnet.cache import audio_dir, render_dir
from slidesonnet.config import default_config_path, load_config
from slidesonnet.deck import default_sidecar_path, load_deck, save_deck
from slidesonnet.diagnostics import Diagnostic
from slidesonnet.narration.format import serialize_body
from slidesonnet.narration.model import PageNarration, Segment, Transition
from slidesonnet.pdf.reader import rasterize
from slidesonnet.tts import create_tts

SlideStatus = Literal["error", "warning", "ready", "empty"]


class EditorState:
    """Mutable state behind the narration editor."""

    def __init__(self, pdf_path: Path, *, sidecar_path: Path | None = None) -> None:
        self.pdf_path = pdf_path.resolve()
        self.sidecar_path = sidecar_path or default_sidecar_path(self.pdf_path)
        self.config = load_config(self.pdf_path)
        self.index = 0
        self._images: list[Path] | None = None
        self.reload()
        self._mtimes = self._source_mtimes()

    # ---- loading -------------------------------------------------------
    def reload(self) -> None:
        self.deck, self.diagnostics = load_deck(self.pdf_path, sidecar_path=self.sidecar_path)

    # ---- source watching -------------------------------------------------
    def _source_mtimes(self) -> dict[str, float]:
        sources = (self.pdf_path, self.sidecar_path, default_config_path(self.pdf_path))
        out: dict[str, float] = {}
        for path in sources:
            try:
                out[str(path)] = path.stat().st_mtime
            except OSError:  # missing file counts as a (stable) timestamp of 0
                out[str(path)] = 0.0
        return out

    def poll_sources(self) -> bool:
        """Reload when the PDF, sidecar, or config changed on disk; True if so.

        The editor polls this so external edits (a recompile, hand-editing the
        sidecar) appear live. Saves made through this state refresh the
        baseline themselves and never trigger a reload.
        """
        current = self._source_mtimes()
        if current == self._mtimes:
            return False
        try:
            config = load_config(self.pdf_path)
            deck, diagnostics = load_deck(self.pdf_path, sidecar_path=self.sidecar_path)
        except Exception:
            # mid-recompile: the PDF (or config) is missing or half-written.
            # Keep showing the last good deck; the next tick retries.
            return False
        if current[str(self.pdf_path)] != self._mtimes[str(self.pdf_path)]:
            self._images = None  # page images are stale; re-rasterize on demand
        self._mtimes = current
        self.config = config
        self.deck, self.diagnostics = deck, diagnostics
        self.go(self.index)  # clamp in case the deck shrank
        return True

    def external_changes(self) -> set[str]:
        """Which sources changed on disk since the last baseline: pdf/sidecar/config."""
        current = self._source_mtimes()
        labels = {
            str(self.pdf_path): "pdf",
            str(self.sidecar_path): "sidecar",
            str(default_config_path(self.pdf_path)): "config",
        }
        return {labels[key] for key, mtime in current.items() if mtime != self._mtimes[key]}

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
    @property
    def body_text(self) -> str:
        return serialize_body(self.current_block)

    def _next_page_id(self) -> str | None:
        nxt = self.index + 1
        return self.deck.pages[nxt] if nxt < self.page_count else None

    def set_body(self, body: str) -> bool:
        """Replace the current block from a plain free-text body (preserves transitions).

        Lossy convenience for the plain-text editing path: per-utterance voice,
        pace, and director's notes are not expressible here. Inline ``[pause N]``
        still splits the body into segments.
        """
        from slidesonnet.narration.format import parse_segments

        block = self.current_block
        return self.replace_block(
            parse_segments(body),
            transition_in=block.transition_in,
            transition_out=block.transition_out,
        )

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
        if empty:
            self.deck.narration.pop(self.current_id, None)
        else:
            old = self.deck.narration.get(self.current_id)
            self.deck.narration[self.current_id] = PageNarration(
                slide_id=self.current_id,
                segments=list(segments),
                transition_in=tin,
                transition_out=tout,
                # round-trip bookkeeping: a save re-emits the author's raw text
                # when the content is unchanged, and keeps the comments above
                # the block either way
                source=old.source if old else None,
                canon=old.canon if old else None,
                lead=old.lead if old else None,
                tail=old.tail if old else None,
            )
            if tout.kind != "cut":
                nxt = self._next_page_id()
                if nxt and nxt in self.deck.narration:
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
        try:
            self._mtimes[str(self.sidecar_path)] = self.sidecar_path.stat().st_mtime
        except OSError:
            self._mtimes[str(self.sidecar_path)] = 0.0

    # ---- unattached narration (slide dropped/renamed by a recompile) -------
    def orphan_blocks(self) -> list[PageNarration]:
        """Narration blocks whose slide-id matches no PDF page (sidecar order)."""
        on_page = set(self.deck.pages)
        return [b for sid, b in self.deck.narration.items() if sid not in on_page]

    def unnarrated_pages(self) -> list[str]:
        """Page ids an orphan could attach to (no narration yet), in page order."""
        seen: set[str] = set()
        out: list[str] = []
        for sid in self.deck.pages:
            if sid and sid not in seen and not self.has_narration(sid):
                seen.add(sid)
                out.append(sid)
        return out

    def attach_orphan(self, orphan_id: str, target_id: str) -> None:
        """Move an orphan block's narration onto the page *target_id* and save."""
        if target_id not in self.deck.pages:
            raise ValueError(f"'{target_id}' is not a page in the deck")
        if self.has_narration(target_id):
            raise ValueError(f"slide '{target_id}' already has narration")
        block = self.deck.narration.pop(orphan_id)
        self.deck.narration[target_id] = PageNarration(
            slide_id=target_id,
            segments=block.segments,
            transition_in=block.transition_in,
            transition_out=block.transition_out,
            lead=block.lead,  # comments above the block travel with it
            tail=block.tail,
        )
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
        self.deck.narration[self.current_id] = PageNarration(
            slide_id=self.current_id,
            segments=[*target.segments, *orphan.segments],
            transition_in=target.transition_in,
            transition_out=target.transition_out,
            lead=target.lead,
            tail=target.tail,
        )
        self._write_and_reload()

    def delete_orphan(self, orphan_id: str) -> None:
        """Drop an orphan block (and its text) from the sidecar."""
        self.deck.narration.pop(orphan_id, None)
        self._write_and_reload()

    # ---- voices -----------------------------------------------------------
    def voice_options(self) -> list[str]:
        """Voice choices for the editor: named presets first, then engine voices.

        For Kokoro this is the model's fixed English voice set; for any backend
        it also includes the deck's named presets from ``slidesonnet.toml``. The
        per-utterance voice is otherwise None (the deck default).
        """
        from slidesonnet.tts.kokoro import KOKORO_VOICES

        opts: list[str] = sorted(self.config.voices)  # named presets
        if self.config.tts.backend == "kokoro":
            opts += [v for v in KOKORO_VOICES if v not in opts]
        return opts

    def default_voice(self) -> str | None:
        """The deck-wide voice an utterance with no explicit voice falls back to."""
        if self.config.tts.backend == "kokoro":
            return self.config.tts.kokoro_voice
        return self.config.tts.elevenlabs_voice_id or None

    # ---- synthesis cost ---------------------------------------------------
    @property
    def tts_is_paid(self) -> bool:
        """True when the configured TTS backend spends API credits."""
        return create_tts(self.config.tts).paid

    def uncached_count(self, slide_id: str) -> int:
        """How many of *slide_id*'s speech segments a synthesis run would generate."""
        return len(
            uncached_targets(self.deck, self.config, audio_dir(self.pdf_path), only_ids={slide_id})
        )

    def uncached_total(self) -> int:
        """How many speech segments across the deck a synthesis run would generate."""
        return len(uncached_targets(self.deck, self.config, audio_dir(self.pdf_path)))

    def speech_cached_flags(self) -> list[bool]:
        """Per speech segment of the current slide: True where its audio is cached."""
        if not self.current_id:
            return []
        return cached_speech_flags(
            self.deck, self.config, audio_dir(self.pdf_path), self.current_id
        )

    def ungenerated_ids(self) -> set[str]:
        """Slide-ids with at least one speech segment that has no cached audio."""
        return ungenerated_ids(self.deck, self.config, audio_dir(self.pdf_path))

    # ---- actions -------------------------------------------------------
    def synth_current(self, *, force: bool = False) -> int:
        return api.synthesize_deck(
            self.pdf_path,
            sidecar_path=self.sidecar_path,
            engine=self.config.tts.backend,
            only_ids={self.current_id},
            force=force,
        )

    def synth_segment(self, speech_index: int, *, force: bool = False) -> int:
        """Synthesize one speech segment of the current slide (by speech index)."""
        return api.synthesize_deck(
            self.pdf_path,
            sidecar_path=self.sidecar_path,
            engine=self.config.tts.backend,
            only_segments={(self.current_id, speech_index)},
            force=force,
        )

    def synth_all(self) -> int:
        return api.synthesize_deck(
            self.pdf_path, sidecar_path=self.sidecar_path, engine=self.config.tts.backend
        )

    def preview_current(self) -> api.Preview:
        return api.build_preview(
            self.pdf_path,
            sidecar_path=self.sidecar_path,
            engine=self.config.tts.backend,
            only_id=self.current_id,
        )

    def preview_deck(self) -> api.Preview:
        return api.build_preview(
            self.pdf_path, sidecar_path=self.sidecar_path, engine=self.config.tts.backend
        )

    def export(self, output: Path, *, silent: bool = False) -> api.ExportResult:
        return api.export(
            self.pdf_path,
            output,
            sidecar_path=self.sidecar_path,
            engine=None if silent else self.config.tts.backend,
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


def cue_start(cues: list[tuple[float, str]], slide_id: str) -> float | None:
    """Start time of *slide_id* in a deck-preview cue sheet, or None if absent."""
    for start, sid in cues:
        if sid == slide_id:
            return start
    return None
