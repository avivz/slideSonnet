"""Editor state — deck navigation, edits, and actions, independent of NiceGUI.

Keeping this UI-free means the editor's logic (parsing edits back into the
sidecar grammar, saving, synthesizing, previewing, exporting) is unit-testable
without a browser, and stays under ``mypy --strict``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from slidesonnet import api
from slidesonnet.audio.synth import uncached_targets
from slidesonnet.cache import audio_dir, render_dir
from slidesonnet.config import default_config_path, load_config
from slidesonnet.deck import default_sidecar_path, load_deck, save_deck
from slidesonnet.diagnostics import Diagnostic
from slidesonnet.narration.format import parse_segments, serialize_body
from slidesonnet.narration.model import Pace, PageNarration
from slidesonnet.pdf.reader import rasterize
from slidesonnet.tts import create_tts

_VALID_PACES: frozenset[str] = frozenset({"slow", "normal", "fast"})

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

    @property
    def voice(self) -> str:
        return self.current_block.voice or ""

    @property
    def pace(self) -> str:
        return self.current_block.pace or "normal"

    def save(self, body: str, *, voice: str = "", pace: str = "normal") -> None:
        """Persist edits to the current slide's block, then re-run diagnostics."""
        block = PageNarration(
            slide_id=self.current_id,
            segments=parse_segments(body),
            voice=voice.strip() or None,
            pace=_coerce_pace(pace),
        )
        if block.segments or block.voice or block.pace:
            self.deck.narration[self.current_id] = block
        else:
            self.deck.narration.pop(self.current_id, None)
        save_deck(self.deck)
        self.reload()
        self._mtimes = self._source_mtimes()  # our own write must not look external

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

    # ---- actions -------------------------------------------------------
    def synth_current(self) -> int:
        return api.synthesize_deck(
            self.pdf_path,
            sidecar_path=self.sidecar_path,
            engine=self.config.tts.backend,
            only_ids={self.current_id},
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


def _coerce_pace(pace: str) -> Pace | None:
    p = pace.strip().lower()
    if p in _VALID_PACES and p != "normal":
        return p  # type: ignore[return-value]
    return None
