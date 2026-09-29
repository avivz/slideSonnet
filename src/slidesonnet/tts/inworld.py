"""Inworld TTS backend — cloud, paid, studio-grade text-to-speech.

Inworld is a low-cost, high-quality cloud engine, with a speaking-rate
control that maps onto the deck's per-utterance ``:pace``. The
engine talks to the ``inworld-tts`` SDK; its client returns the full audio as
bytes, so synthesis is naturally atomic — a failed call writes nothing.

Delivery controls:

* ``[tts.inworld]`` settings (``temperature``, ``delivery_mode``, ``language``,
  ``text_normalization``) are sent only when set, and join :meth:`cache_key`;
* inline pronunciation fixes arrive already resolved to their spoken form
  (:mod:`slidesonnet.narration.spoken`);
* :func:`request_text` turns an utterance into the exact text Inworld gets: on
  the inworld-tts-2 family square brackets are stage directions, so stray ones
  are sent as round brackets; and (unless ``send_direction = false``) a
  ``direct:`` note leads the line as a ``[...]`` direction (inworld-tts-2 itself
  only).
  Synthesis hashes that text, so a changed note re-keys exactly that clip.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from slidesonnet.env import getenv
from slidesonnet.exceptions import TTSError
from slidesonnet.models import TTSConfig
from slidesonnet.narration.spoken import round_brackets
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

#: Inworld's speaking_rate accepts [0.5, 1.5]; a pace multiplier can push the
#: configured speed past either end, so we clamp before calling the API.
_SPEAKING_RATE_MIN = 0.5
_SPEAKING_RATE_MAX = 1.5

#: Inworld's own temperature default: setting it explicitly changes nothing.
_DEFAULT_TEMPERATURE = 1.0


def is_tts2_family(model: str) -> bool:
    """True for the inworld-tts-2 family: it takes any ``[...]`` as a direction and
    has ``delivery_mode``."""
    return model.startswith("inworld-tts-2")


def follows_directions(model: str) -> bool:
    """True for the model that performs a free-text ``[...]`` direction.

    inworld-tts-2 only: ``-flash`` drops directions, and the 1.5 models may read
    them aloud.
    """
    return model == "inworld-tts-2"


def request_text(text: str, direction: str | None, model: str) -> str:
    """The exact text sent to Inworld for an utterance *text* under *model*.

    *direction* is the ``direct:`` note to perform, or None to send none. Text
    without square brackets and without a (followed) direction comes back
    unchanged, so clips cached before delivery controls existed keep their names.
    """
    if is_tts2_family(model) and ("[" in text or "]" in text):
        text = round_brackets(text)
    if direction and follows_directions(model):
        note = " ".join(direction.replace("[", " ").replace("]", " ").split())
        if note:
            text = f"[{note}] {text}"
    return text


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
        self._env_dir: Path | None = config.env_dir
        self._client: _InworldClientType | None = None
        self.voice: str = config.inworld_voice
        self.model: str = config.inworld_model
        self.speed: float = config.inworld_speed
        temperature = config.inworld_temperature
        self.temperature: float | None = (
            None if temperature is None or temperature == _DEFAULT_TEMPERATURE else temperature
        )
        self.delivery_mode: str | None = config.inworld_delivery_mode
        self.language: str | None = config.inworld_language
        self.text_normalization: bool | None = config.inworld_text_normalization

    def _ensure_client(self) -> _InworldClientType:
        """Validate dependencies and create the client on first call."""
        if self._client is not None:
            return self._client

        api_key = getenv(self._api_key_env, self._env_dir) or ""
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
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.delivery_mode is not None:
            kwargs["delivery_mode"] = self.delivery_mode.upper()
        if self.language is not None:
            kwargs["language"] = self.language
        if self.text_normalization is not None:
            kwargs["apply_text_normalization"] = "ON" if self.text_normalization else "OFF"

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
        # Delivery settings append only when set, so an unconfigured deck keeps
        # the key (and the paid clips) it had before they existed.
        if self.temperature is not None:
            key += f":t={self.temperature}"
        if self.delivery_mode is not None:
            key += f":dm={self.delivery_mode}"
        if self.language is not None:
            key += f":lang={self.language}"
        if self.text_normalization is not None:
            key += f":norm={'on' if self.text_normalization else 'off'}"
        return key

    def default_voice(self) -> str | None:
        return self.voice or None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _get_audio_duration(path: Path) -> float:
    """Get audio duration using ffprobe."""
    from slidesonnet.video.composer import get_duration

    return get_duration(path)
