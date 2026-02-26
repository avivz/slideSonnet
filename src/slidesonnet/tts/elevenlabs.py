"""ElevenLabs TTS backend — cloud, paid, high-quality text-to-speech."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from slidesonnet.exceptions import TTSError
from slidesonnet.models import TTSConfig
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from elevenlabs import ElevenLabs as _ElevenLabsType

try:
    from elevenlabs import ElevenLabs as _ElevenLabs
except ImportError:
    _ElevenLabs = None

# Module-level alias for test mocking via @patch("slidesonnet.tts.elevenlabs.ElevenLabs")
ElevenLabs: type[_ElevenLabsType] | None = _ElevenLabs


class ElevenLabsTTS(TTSEngine):
    def __init__(self, config: TTSConfig) -> None:
        api_key = os.environ.get(config.elevenlabs_api_key_env, "")
        if not api_key:
            raise TTSError(
                f"Environment variable '{config.elevenlabs_api_key_env}' not set. "
                f"Add it to your .env file."
            )

        if ElevenLabs is None:
            raise TTSError(
                "elevenlabs package not installed. "
                "Install with: pip install slidesonnet[elevenlabs]"
            )

        self.client: _ElevenLabsType = ElevenLabs(api_key=api_key)
        self.voice_id: str = config.elevenlabs_voice_id
        self.model_id: str = config.elevenlabs_model_id
        self.stability: float = config.elevenlabs_stability
        self.similarity_boost: float = config.elevenlabs_similarity_boost

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        voice_id = voice if voice else self.voice_id

        audio_generator = self.client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=self.model_id,
            output_format="mp3_44100_128",
        )

        # Write the audio stream to file
        with open(output_path, "wb") as f:
            for chunk in audio_generator:
                f.write(chunk)

        return _get_audio_duration(output_path)

    def name(self) -> str:
        return "elevenlabs"


def _get_audio_duration(path: Path) -> float:
    """Get audio duration using ffprobe."""
    from slidesonnet.video.composer import get_duration

    return get_duration(path)
