"""Inworld TTS backend — cloud, paid, studio-grade text-to-speech.

Inworld is a low-cost, high-quality cloud engine, with a speaking-rate
control that maps onto the deck's per-utterance ``:pace``. The
engine talks to the ``inworld-tts`` SDK; its client returns the full audio as
bytes, so synthesis is naturally atomic — a failed call writes nothing.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from slidesonnet.exceptions import TTSError
from slidesonnet.models import TTSConfig
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

#: Inworld's speaking_rate accepts [0.5, 1.5]; a pace multiplier can push the
#: configured speed past either end, so we clamp before calling the API.
_SPEAKING_RATE_MIN = 0.5
_SPEAKING_RATE_MAX = 1.5

if TYPE_CHECKING:
    from inworld_tts import InworldTTS as _InworldClientType

_InworldClient: type[_InworldClientType] | None
try:
    from inworld_tts import InworldTTS as _InworldClientImport

    _InworldClient = _InworldClientImport
except ImportError:
    _InworldClient = None

# Module-level alias for test mocking via @patch (the SDK class shares the name
# of our engine, so we keep it as ``InworldClient`` to avoid the collision).
InworldClient: type[_InworldClientType] | None = _InworldClient


class InworldTTS(TTSEngine):
    paid = True

    def __init__(self, config: TTSConfig) -> None:
        self._api_key_env: str = config.inworld_api_key_env
        self._client: _InworldClientType | None = None
        self.voice: str = config.inworld_voice
        self.model: str = config.inworld_model
        self.speed: float = config.inworld_speed

    def _ensure_client(self) -> _InworldClientType:
        """Validate dependencies and create the client on first call."""
        if self._client is not None:
            return self._client

        api_key = os.environ.get(self._api_key_env, "")
        if not api_key:
            raise TTSError(
                f"Environment variable '{self._api_key_env}' not set. Add it to your .env file."
            )

        if InworldClient is None:
            raise TTSError(
                "inworld-tts package not installed. Install with: pip install slidesonnet[inworld]"
            )

        self._client = InworldClient(api_key=api_key)
        return self._client

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        voice_id = voice if voice else self.voice
        client = self._ensure_client()

        kwargs: dict[str, object] = {"voice": voice_id, "model": self.model}
        if self.speed != 1.0:
            kwargs["speaking_rate"] = _clamp(self.speed, _SPEAKING_RATE_MIN, _SPEAKING_RATE_MAX)

        # The SDK returns the whole clip as bytes, so a failure here happens
        # before any file is opened — there is nothing half-written to clean up.
        try:
            audio = client.generate(text, **kwargs)
        except Exception as exc:
            raise TTSError(f"Inworld synthesis failed: {exc}") from exc

        # Write to a temp file, atomically rename on success (matches Kokoro).
        fd, tmp = tempfile.mkstemp(dir=output_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(audio)
            os.replace(tmp, output_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

        return _get_audio_duration(output_path)

    def name(self) -> str:
        return "inworld"

    def cache_key(self) -> str:
        key = f"inworld:{self.voice}:{self.model}"
        if self.speed != 1.0:
            key += f":{self.speed}"
        return key

    def default_voice(self) -> str | None:
        return self.voice or None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _get_audio_duration(path: Path) -> float:
    """Get audio duration using ffprobe."""
    from slidesonnet.video.composer import get_duration

    return get_duration(path)
