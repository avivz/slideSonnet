"""Real-server NiceGUI launcher for the Playwright browser-journey tests.

Started as a subprocess by ``tests/test_browser_journeys.py``. It serves the
actual editor — real websocket, real DOM/focus/blur lifecycle — with two
test-only twists, neither of which touches production code:

- **Markers in the DOM.** NiceGUI's ``.mark()`` is server-side metadata only
  (consumed by ``ElementFilter``); nothing reaches the browser. We wrap it so
  every marker also lands as a CSS class (``ss-marker-<name>``) that Playwright
  can target, surviving destructive re-renders of the block editor.
- **Stub TTS (default).** ``create_tts`` is replaced — in every module that
  imported it by name — with a deterministic engine that writes a short silent
  wav instantly. ``name()`` returns ``"kokoro"`` so cache filenames and
  extensions look exactly like the local engine's. Set
  ``SLIDESONNET_TEST_REAL_TTS=1`` to skip the patching (the kokoro journey).

Environment:
    SLIDESONNET_EDIT_PDF           deck to edit (required)
    SLIDESONNET_TEST_PORT          port to serve on (default 8666)
    SLIDESONNET_TEST_REAL_TTS      "1" -> keep the real TTS engine
    SLIDESONNET_TEST_STUB_SECONDS  stub clip length in seconds (default 1.0)
"""

from __future__ import annotations

import os
import wave
from pathlib import Path

from nicegui import ui
from nicegui.element import Element

from slidesonnet.gui.app import build_editor
from slidesonnet.models import TTSConfig
from slidesonnet.tts.base import TTSEngine

_SAMPLE_RATE = 24_000


class StubEngine(TTSEngine):
    """Instant, deterministic TTS: a fixed-length silent wav per utterance."""

    paid = False

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(_SAMPLE_RATE)
            wf.writeframes(b"\x00\x00" * int(self.seconds * _SAMPLE_RATE))
        return self.seconds

    def name(self) -> str:
        return "kokoro"  # cache filenames/extensions match the local engine

    def cache_key(self) -> str:
        return "stub"


def _patch_tts(seconds: float) -> None:
    """Replace ``create_tts`` everywhere it was imported with a stub factory."""
    import slidesonnet.audio.synth as synth_mod
    import slidesonnet.gui.state as state_mod
    import slidesonnet.tts as tts_mod

    def factory(_cfg: TTSConfig) -> TTSEngine:
        return StubEngine(seconds)

    tts_mod.create_tts = factory  # type: ignore[assignment]
    synth_mod.create_tts = factory  # type: ignore[assignment]
    state_mod.create_tts = factory  # type: ignore[assignment]


def _expose_markers() -> None:
    """Make ``.mark()`` also emit an ``ss-marker-<name>`` CSS class."""
    original = Element.mark

    def mark_with_classes(self: Element, *markers: str) -> Element:
        original(self, *markers)
        self._classes.extend(f"ss-marker-{m}" for m in self._markers)
        return self

    Element.mark = mark_with_classes  # type: ignore[method-assign, assignment]


if __name__ in {"__main__", "__mp_main__"}:
    _expose_markers()
    if os.environ.get("SLIDESONNET_TEST_REAL_TTS") != "1":
        _patch_tts(float(os.environ.get("SLIDESONNET_TEST_STUB_SECONDS", "1.0")))
    _pdf = Path(os.environ["SLIDESONNET_EDIT_PDF"])

    @ui.page("/")
    def index() -> None:
        build_editor(_pdf)

    ui.run(
        host="127.0.0.1",
        port=int(os.environ.get("SLIDESONNET_TEST_PORT", "8666")),
        title="slideSonnet (browser tests)",
        reload=False,
        show=False,
    )
