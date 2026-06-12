"""TTS package: speech synthesis backends, their registry, and a factory.

``BACKENDS`` is the single place a TTS engine is described — name, cached-audio
file extension, paid flag, and constructor. The CLI's ``--engine`` choices,
config validation, cache filename extensions, and clean's paid-audio set all
derive from it, so adding an engine means one new ``BackendSpec`` (plus the
``Backend`` Literal in models.py, which mypy can't derive at runtime — a test
pins the two in sync).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from slidesonnet.models import TTSConfig
from slidesonnet.tts.base import TTSEngine


def _make_kokoro(tts: TTSConfig) -> TTSEngine:
    from slidesonnet.tts.kokoro import KokoroTTS

    return KokoroTTS(voice=tts.kokoro_voice, speed=tts.kokoro_speed)


def _make_elevenlabs(tts: TTSConfig) -> TTSEngine:
    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    return ElevenLabsTTS(tts)


@dataclass(frozen=True)
class BackendSpec:
    """Everything the rest of the tool needs to know about a TTS backend."""

    name: str
    extension: str  # cached-audio file extension (".wav", ".mp3")
    paid: bool  # synthesis spends metered API credits
    factory: Callable[[TTSConfig], TTSEngine]


BACKENDS: dict[str, BackendSpec] = {
    "kokoro": BackendSpec("kokoro", ".wav", paid=False, factory=_make_kokoro),
    "elevenlabs": BackendSpec("elevenlabs", ".mp3", paid=True, factory=_make_elevenlabs),
}

#: Backends whose cached audio cost money to produce (clean keeps these).
API_BACKENDS: frozenset[str] = frozenset(n for n, spec in BACKENDS.items() if spec.paid)


def create_tts(tts: TTSConfig) -> TTSEngine:
    """Create a TTS engine from a :class:`TTSConfig`."""
    spec = BACKENDS.get(tts.backend)
    if spec is None:
        raise ValueError(f"Unknown TTS backend: {tts.backend}")
    return spec.factory(tts)
