"""ElevenLabs TTS backend — cloud, paid, high-quality text-to-speech."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from slidesonnet.models import TTSConfig
from slidesonnet.tts.base import TTSEngine

try:
    from elevenlabs import ElevenLabs
except ImportError:
    ElevenLabs = None  # type: ignore[assignment,misc]


class ElevenLabsTTS(TTSEngine):
    def __init__(self, config: TTSConfig):
        load_dotenv()
        api_key = os.environ.get(config.elevenlabs_api_key_env, "")
        if not api_key:
            print(
                f"ERROR: Environment variable '{config.elevenlabs_api_key_env}' not set. "
                f"Add it to your .env file.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        if ElevenLabs is None:
            print(
                "ERROR: elevenlabs package not installed. "
                "Install with: pip install slidesonnet[elevenlabs]",
                file=sys.stderr,
            )
            raise SystemExit(1)

        self.client = ElevenLabs(api_key=api_key)
        self.voice_id = config.elevenlabs_voice_id
        self.model_id = config.elevenlabs_model_id
        self.stability = config.elevenlabs_stability
        self.similarity_boost = config.elevenlabs_similarity_boost

    def synthesize(self, text: str, output_path: Path) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        audio_generator = self.client.text_to_speech.convert(
            text=text,
            voice_id=self.voice_id,
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
