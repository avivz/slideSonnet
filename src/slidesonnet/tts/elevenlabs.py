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

_ElevenLabs: type[_ElevenLabsType] | None
try:
    from elevenlabs import ElevenLabs as _ElevenLabsImport

    _ElevenLabs = _ElevenLabsImport
except ImportError:
    _ElevenLabs = None

# Module-level alias for test mocking via @patch("slidesonnet.tts.elevenlabs.ElevenLabs")
ElevenLabs: type[_ElevenLabsType] | None = _ElevenLabs


class ElevenLabsTTS(TTSEngine):
    def __init__(self, config: TTSConfig) -> None:
        self._api_key_env: str = config.elevenlabs_api_key_env
        self._client: _ElevenLabsType | None = None
        self.voice_id: str = config.elevenlabs_voice_id
        self.model_id: str = config.elevenlabs_model_id
        self.stability: float = config.elevenlabs_stability
        self.similarity_boost: float = config.elevenlabs_similarity_boost

    def _ensure_client(self) -> _ElevenLabsType:
        """Validate dependencies and create the client on first call."""
        if self._client is not None:
            return self._client

        api_key = os.environ.get(self._api_key_env, "")
        if not api_key:
            raise TTSError(
                f"Environment variable '{self._api_key_env}' not set. Add it to your .env file."
            )

        if ElevenLabs is None:
            raise TTSError(
                "elevenlabs package not installed. "
                "Install with: pip install slidesonnet[elevenlabs]"
            )

        self._client = ElevenLabs(api_key=api_key)
        return self._client

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        voice_id = voice if voice else self.voice_id
        client = self._ensure_client()

        audio_generator = client.text_to_speech.convert(
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

    def cache_key(self) -> str:
        return (
            f"elevenlabs:{self.voice_id}:{self.model_id}:{self.stability}:{self.similarity_boost}"
        )


def _get_audio_duration(path: Path) -> float:
    """Get audio duration using ffprobe."""
    from slidesonnet.video.composer import get_duration

    return get_duration(path)
