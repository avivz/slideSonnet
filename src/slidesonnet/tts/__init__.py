"""TTS package: speech synthesis backends and a factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from slidesonnet.models import TTSConfig
from slidesonnet.tts.base import TTSEngine

if TYPE_CHECKING:
    from slidesonnet.config import Config


def create_tts(tts: TTSConfig) -> TTSEngine:
    """Create a TTS engine from a :class:`TTSConfig`."""
    from slidesonnet.tts.piper import PiperTTS

    if tts.backend == "piper":
        return PiperTTS(model=tts.piper_model, speed=tts.piper_speed)
    if tts.backend == "elevenlabs":
        from slidesonnet.tts.elevenlabs import ElevenLabsTTS

        return ElevenLabsTTS(tts)
    raise ValueError(f"Unknown TTS backend: {tts.backend}")


def create_tts_from_config(config: Config) -> TTSEngine:
    """Convenience: build a TTS engine from a full editor :class:`Config`."""
    return create_tts(config.tts)
