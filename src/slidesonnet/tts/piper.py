"""Piper TTS backend — local, free text-to-speech."""

from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

from slidesonnet.tts.base import TTSEngine

_VOICES_DIR = Path.home() / ".local" / "share" / "piper_models"


def _ensure_voice(voice_name: str) -> None:
    """Download a Piper voice model if it doesn't already exist."""
    _VOICES_DIR.mkdir(parents=True, exist_ok=True)
    model_path = _VOICES_DIR / f"{voice_name}.onnx"
    if model_path.exists() and model_path.stat().st_size > 0:
        return

    print(f"Downloading Piper voice '{voice_name}'...")
    try:
        from piper.download_voices import download_voice
    except ImportError:
        print(
            f"ERROR: Piper voice '{voice_name}' not found at {model_path} and "
            f"auto-download requires the piper-tts Python package.\n"
            f"Install with: pip install piper-tts\n"
            f"Or download the voice manually to {_VOICES_DIR}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    download_voice(voice_name, _VOICES_DIR)
    print(f"Downloaded Piper voice '{voice_name}' to {_VOICES_DIR}")


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
            print(
                "ERROR: 'piper' not found. Install with: pip install piper-tts",
                file=sys.stderr,
            )
            raise SystemExit(1)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: piper failed:\n{e.stderr}", file=sys.stderr)
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
