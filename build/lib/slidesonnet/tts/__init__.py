"""TTS package: speech synthesis backends and utilities."""

from __future__ import annotations

from slidesonnet.models import ProjectConfig
from slidesonnet.tts.base import TTSEngine


def create_tts(config: ProjectConfig) -> TTSEngine:
    """Create TTS engine from config."""
    from slidesonnet.tts.piper import PiperTTS

    if config.tts.backend == "piper":
        return PiperTTS(model=config.tts.piper_model, speed=config.tts.piper_speed)
    elif config.tts.backend == "elevenlabs":
        from slidesonnet.tts.elevenlabs import ElevenLabsTTS

        return ElevenLabsTTS(config.tts)
    else:
        raise ValueError(f"Unknown TTS backend: {config.tts.backend}")
