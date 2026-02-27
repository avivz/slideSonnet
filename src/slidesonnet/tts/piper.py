"""Piper TTS backend — local, free text-to-speech."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import wave
from pathlib import Path

from slidesonnet.exceptions import TTSError
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

_VOICES_DIR = Path.home() / ".local" / "share" / "piper_models"

# Resolve piper binary: prefer PATH, fall back to the venv's bin/ directory.
_VENV_BIN = Path(sys.executable).parent


def _find_piper() -> str:
    found = shutil.which("piper")
    if found:
        return found
    venv_piper = _VENV_BIN / "piper"
    if venv_piper.is_file():
        return str(venv_piper)
    return "piper"  # let subprocess raise FileNotFoundError


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
        raise TTSError(
            f"Piper voice '{voice_name}' not found at {model_path} and auto-download "
            f"requires the piper-tts Python package.\nInstall with: pip install piper-tts\n"
            f"Or download the voice manually to {_VOICES_DIR}"
        )

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
            _find_piper(),
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
            raise TTSError("'piper' not found. Install with: pip install piper-tts")
        except subprocess.CalledProcessError as e:
            raise TTSError(f"piper failed:\n{e.stderr}")

        return _wav_duration(output_path)

    def name(self) -> str:
        return "piper"

    def cache_key(self) -> str:
        return f"piper:{self.model}:{self.speaker}"


def _wav_duration(path: Path) -> float:
    """Get duration of a WAV file in seconds."""
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate
