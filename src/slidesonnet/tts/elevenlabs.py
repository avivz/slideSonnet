"""ElevenLabs TTS backend — cloud, paid, high-quality text-to-speech."""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from slidesonnet.exceptions import TTSError
from slidesonnet.models import TTSConfig
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from elevenlabs import ElevenLabs as _ElevenLabsType

_ElevenLabs: type[_ElevenLabsType] | None
_VoiceSettings: type | None
try:
    from elevenlabs import ElevenLabs as _ElevenLabsImport
    from elevenlabs.types.voice_settings import VoiceSettings as _VoiceSettingsImport

    _ElevenLabs = _ElevenLabsImport
    _VoiceSettings = _VoiceSettingsImport
except ImportError:
    _ElevenLabs = None
    _VoiceSettings = None

# Module-level aliases for test mocking via @patch
ElevenLabs: type[_ElevenLabsType] | None = _ElevenLabs
VoiceSettings: type | None = _VoiceSettings


class ElevenLabsTTS(TTSEngine):
    def __init__(self, config: TTSConfig) -> None:
        self._api_key_env: str = config.elevenlabs_api_key_env
        self._client: _ElevenLabsType | None = None
        self.voice_id: str = config.elevenlabs_voice_id
        self.model_id: str = config.elevenlabs_model_id
        self.stability: float = config.elevenlabs_stability
        self.similarity_boost: float = config.elevenlabs_similarity_boost
        self.speed: float = config.elevenlabs_speed

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

        # Retry on HTTP 429 (rate limit / concurrent limit exceeded) with exponential
        # backoff — parallel builds may exceed the plan's concurrent request limit.
        assert VoiceSettings is not None  # guaranteed by _ensure_client()
        vs_kwargs: dict[str, Any] = {
            "stability": self.stability,
            "similarity_boost": self.similarity_boost,
        }
        if self.speed != 1.0:
            vs_kwargs["speed"] = self.speed
        audio_generator = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=self.model_id,
            output_format="mp3_44100_128",
            voice_settings=VoiceSettings(**vs_kwargs),
            request_options={"max_retries": 5},
        )

        # Write to temp file, atomically rename on success
        fd, tmp = tempfile.mkstemp(dir=output_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                for chunk in audio_generator:
                    f.write(chunk)
            os.replace(tmp, output_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

        return _get_audio_duration(output_path)

    def name(self) -> str:
        return "elevenlabs"

    def cache_key(self) -> str:
        key = f"elevenlabs:{self.voice_id}:{self.model_id}:{self.stability}:{self.similarity_boost}"
        if self.speed != 1.0:
            key += f":{self.speed}"
        return key


def _get_audio_duration(path: Path) -> float:
    """Get audio duration using ffprobe."""
    from slidesonnet.video.composer import get_duration

    return get_duration(path)
