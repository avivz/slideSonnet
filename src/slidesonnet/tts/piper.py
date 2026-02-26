"""Piper TTS backend — local, free text-to-speech."""

from __future__ import annotations

import logging
import subprocess
import wave
from pathlib import Path

from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

_VOICES_DIR = Path.home() / ".local" / "share" / "piper_models"


def _ensure_voice(voice_name: str) -> None:
    """Download a Piper voice model if it doesn't already exist."""
    _VOICES_DIR.mkdir(parents=True, exist_ok=True)
    model_path = _VOICES_DIR / f"{voice_name}.onnx"
    if model_path.exists() and model_path.stat().st_size > 0:
        return

    logger.info("Downloading Piper voice '%s'...", voice_name)
    try:
        from piper.download_voices import download_voice
    except ImportError:
        logger.error(
            "Piper voice '%s' not found at %s and auto-download requires the "
            "piper-tts Python package.\nInstall with: pip install piper-tts\n"
            "Or download the voice manually to %s",
            voice_name, model_path, _VOICES_DIR,
        )
        raise SystemExit(1)

    download_voice(voice_name, _VOICES_DIR)
    logger.info("Downloaded Piper voice '%s' to %s", voice_name, _VOICES_DIR)


class PiperTTS(TTSEngine):
    def __init__(self, model: str = "en_US-lessac-medium", speaker: int = 0):
        self.model = model
        self.speaker = speaker

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        model = voice if voice else self.model
        _ensure_voice(model)

        cmd = [
            "piper",
            "--model",
            model,
            "--data-dir",
            str(_VOICES_DIR),
            "--output_file",
            str(output_path),
        ]
        if self.speaker:
            cmd.extend(["--speaker", str(self.speaker)])

        try:
            subprocess.run(
                cmd,
                input=text,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            logger.error("'piper' not found. Install with: pip install piper-tts")
            raise SystemExit(1)
        except subprocess.CalledProcessError as e:
            logger.error("piper failed:\n%s", e.stderr)
            raise SystemExit(1)

        return _wav_duration(output_path)

    def name(self) -> str:
        return "piper"


def _wav_duration(path: Path) -> float:
    """Get duration of a WAV file in seconds."""
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate
