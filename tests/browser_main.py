"""Real-server launcher for the Playwright browser journeys (``tests/test_browser_journeys.py``).

Started as a subprocess. It serves the actual editor — the production app on
Uvicorn, the built frontend, real SSE and media — with one test-only twist:
**stub TTS.** ``create_tts`` is replaced with a deterministic engine that
writes a short silent WAV instantly; ``name()`` returns ``"kokoro"`` so cache
filenames and extensions look exactly like the local engine's. Set
``SLIDESONNET_TEST_REAL_TTS=1`` to keep the real engine.

Environment:
    SLIDESONNET_EDIT_PDF           deck to edit (required)
    SLIDESONNET_LIB_ROOT           folder scanned for the deck library
                                   (default: the deck's own folder)
    SLIDESONNET_TEST_PORT          port to serve on (default 8666)
    SLIDESONNET_TEST_REAL_TTS      "1" -> keep the real TTS engine
    SLIDESONNET_TEST_STUB_SECONDS  stub clip length in seconds (default 1.0)
"""

from __future__ import annotations

import os
import wave
from pathlib import Path

import uvicorn

from slidesonnet.models import TTSConfig
from slidesonnet.server.run import build_registry, editor_app
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

    def list_voices(self) -> tuple[str, ...]:
        from slidesonnet.tts.kokoro import KOKORO_VOICES

        return KOKORO_VOICES

    def default_voice(self) -> str | None:
        return "am_echo"


def _patch_tts(seconds: float) -> None:
    """Replace ``create_tts`` everywhere it was imported with a stub factory."""
    import slidesonnet.audio.synth as synth_mod
    import slidesonnet.tts as tts_mod

    def factory(_cfg: TTSConfig) -> TTSEngine:
        return StubEngine(seconds)

    tts_mod.create_tts = factory  # type: ignore[assignment]
    synth_mod.create_tts = factory  # type: ignore[assignment]


if __name__ == "__main__":
    from slidesonnet.server import engines

    engines.EDITOR_DEFAULT_ENGINE = "kokoro"  # the journeys run on the free engine
    if os.environ.get("SLIDESONNET_TEST_REAL_TTS") != "1":
        _patch_tts(float(os.environ.get("SLIDESONNET_TEST_STUB_SECONDS", "1.0")))
    pdf = Path(os.environ["SLIDESONNET_EDIT_PDF"])
    lib_root = os.environ.get("SLIDESONNET_LIB_ROOT")
    registry = build_registry(pdf, sidecar_path=None, root=Path(lib_root) if lib_root else None)
    uvicorn.run(
        editor_app(registry, host="127.0.0.1"),
        host="127.0.0.1",
        port=int(os.environ.get("SLIDESONNET_TEST_PORT", "8666")),
        log_level="warning",
    )
