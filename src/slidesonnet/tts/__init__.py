"""TTS package: speech synthesis backends and a factory."""

from __future__ import annotations

from slidesonnet.models import TTSConfig
from slidesonnet.tts.base import TTSEngine


def create_tts(tts: TTSConfig) -> TTSEngine:
    """Create a TTS engine from a :class:`TTSConfig`."""
    if tts.backend == "kokoro":
        from slidesonnet.tts.kokoro import KokoroTTS

        return KokoroTTS(voice=tts.kokoro_voice, speed=tts.kokoro_speed)
    if tts.backend == "elevenlabs":
        from slidesonnet.tts.elevenlabs import ElevenLabsTTS

        return ElevenLabsTTS(tts)
    raise ValueError(f"Unknown TTS backend: {tts.backend}")
