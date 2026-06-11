"""Kokoro TTS backend — local neural text-to-speech (82M params, Apache-2.0).

Noticeably more natural than Piper while still ~2x real-time on CPU. Voices
are named ``<lang><gender>_<name>`` (e.g. ``af_heart`` = American English
female "heart"); the first letter is the KPipeline language code. The model
(~330 MB) auto-downloads from the Hugging Face hub on first use.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any

from slidesonnet.exceptions import TTSError
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kokoro import KPipeline as _KPipelineType

_KPipeline: type[_KPipelineType] | None
try:
    from kokoro import KPipeline as _KPipelineImport

    _KPipeline = _KPipelineImport
except ImportError:
    _KPipeline = None

# Module-level alias for test mocking via @patch
KPipeline: type[_KPipelineType] | None = _KPipeline

_REPO_ID = "hexgrad/Kokoro-82M"
_SAMPLE_RATE = 24_000

# The Kokoro-82M v1.0 English voices (``<lang><gender>_<name>``; lang a=American,
# b=British). Offered as the voice choices in the editor — these need no extra
# language packs, unlike the es/fr/hi/it/ja/pt/zh voices the model also ships.
KOKORO_VOICES: tuple[str, ...] = (
    # American English — female
    "af_heart",
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    # American English — male
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    # British English — female
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    # British English — male
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
)


class KokoroTTS(TTSEngine):
    def __init__(self, voice: str = "af_heart", speed: float = 1.0) -> None:
        self.voice = voice
        self.speed = speed
        self._pipelines: dict[str, Any] = {}  # lang code -> KPipeline

    def _pipeline_for(self, voice: str) -> Any:
        """Get (or lazily create) the KPipeline for *voice*'s language."""
        lang_code = voice[0]  # Kokoro convention: voice prefix is the language
        if lang_code not in self._pipelines:
            if KPipeline is None:
                raise TTSError(
                    "kokoro package not installed. Install with: pip install slidesonnet[kokoro]"
                )
            logger.info("Loading Kokoro pipeline (lang '%s')...", lang_code)
            self._pipelines[lang_code] = KPipeline(lang_code=lang_code, repo_id=_REPO_ID)
        return self._pipelines[lang_code]

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        voice_name = voice if voice else self.voice
        pipeline = self._pipeline_for(voice_name)

        samples: list[float] = []
        for result in pipeline(text, voice=voice_name, speed=self.speed):
            audio = getattr(result, "audio", None)
            if audio is not None:
                samples.extend(audio.tolist())
        if not samples:
            raise TTSError(f"kokoro produced no audio for text: {text[:60]!r}")

        _write_wav(output_path, samples)
        return len(samples) / _SAMPLE_RATE

    def name(self) -> str:
        return "kokoro"

    def cache_key(self) -> str:
        key = f"kokoro:{self.voice}"
        if self.speed != 1.0:
            key += f":{self.speed}"
        return key


def _write_wav(path: Path, samples: list[float]) -> None:
    """Write float samples in [-1, 1] as 16-bit mono PCM at 24 kHz."""
    frames = bytearray()
    for s in samples:
        clamped = max(-1.0, min(1.0, s))
        frames += int(clamped * 32767).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(bytes(frames))
