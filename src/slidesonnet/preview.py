"""Preview a single slide's narration audio."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from slidesonnet.config import load_config
from slidesonnet.models import EXTENSION_TO_TYPE, ModuleType
from slidesonnet.parsers.base import SlideParser
from slidesonnet.parsers.beamer import BeamerParser
from slidesonnet.parsers.marp import MarpParser
from slidesonnet.playlist import parse_playlist
from slidesonnet.tts.piper import PiperTTS
from slidesonnet.tts.pronunciation import apply_pronunciation, load_pronunciation_files


def preview_single_slide(
    slides_path: Path,
    slide_number: int,
    playlist_path: Path | None = None,
) -> None:
    """Parse a slide file and play one slide's narration via Piper TTS."""
    slides_path = slides_path.resolve()

    # Determine parser from extension
    suffix = slides_path.suffix.lower()
    module_type = EXTENSION_TO_TYPE.get(suffix)
    parser: SlideParser
    if module_type == ModuleType.MARP:
        parser = MarpParser()
    elif module_type == ModuleType.BEAMER:
        parser = BeamerParser()
    else:
        print(f"ERROR: Unsupported file type '{suffix}'", file=sys.stderr)
        raise SystemExit(1)

    # Parse slides
    with tempfile.TemporaryDirectory() as tmp:
        slides = parser.parse(slides_path, Path(tmp))

    # Validate slide number
    if slide_number < 1 or slide_number > len(slides):
        print(
            f"ERROR: Slide {slide_number} out of range (1–{len(slides)})",
            file=sys.stderr,
        )
        raise SystemExit(1)

    slide = slides[slide_number - 1]

    if not slide.has_narration:
        label = slide.annotation.value
        print(f"Slide {slide_number}: [{label}] — no narration to preview.")
        return

    # Load pronunciation from playlist config if available
    pronunciation: dict[str, str] = {}
    piper_model = "en_US-lessac-medium"
    if playlist_path:
        raw_config, _ = parse_playlist(playlist_path.resolve())
        config = load_config(raw_config, playlist_path.resolve().parent)
        pronunciation = load_pronunciation_files(config.pronunciation_files)
        piper_model = config.tts.piper_model

    # Apply pronunciation
    text = apply_pronunciation(slide.narration_raw, pronunciation)
    print(f"Slide {slide_number}: {text}")

    # Synthesize with Piper
    tts = PiperTTS(model=piper_model)
    with tempfile.TemporaryDirectory() as tmp:
        audio_path = Path(tmp) / "preview.wav"
        duration = tts.synthesize(text, audio_path)
        print(f"Duration: {duration:.1f}s")

        # Play audio
        _play_audio(audio_path)


def _play_audio(path: Path) -> None:
    """Play an audio file using available system player."""
    players: list[list[str]] = [
        ["aplay"],
        ["paplay"],
        ["ffplay", "-nodisp", "-autoexit"],
        ["afplay"],
    ]
    for parts in players:
        try:
            subprocess.run(
                [*parts, str(path)],
                check=True,
                capture_output=True,
            )
            return
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError:
            continue

    print(f"Audio saved to {path} (no audio player found to play it)", file=sys.stderr)
