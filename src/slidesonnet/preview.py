"""Preview a single slide's narration audio."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from slidesonnet.config import load_config
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.models import EXTENSION_TO_TYPE, ModuleType
from slidesonnet.parsers.base import SlideParser
from slidesonnet.parsers.beamer import BeamerParser
from slidesonnet.parsers.marp import MarpParser
from slidesonnet.playlist import parse_playlist
from slidesonnet.tts.piper import PiperTTS
from slidesonnet.tts.pronunciation import apply_pronunciation, load_pronunciation_files

logger = logging.getLogger(__name__)


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
        raise SlideSonnetError(f"Unsupported file type '{suffix}'")

    # Parse slides
    with tempfile.TemporaryDirectory() as tmp:
        slides = parser.parse(slides_path, Path(tmp))

    # Validate slide number
    if slide_number < 1 or slide_number > len(slides):
        raise SlideSonnetError(
            f"Slide {slide_number} out of range (1–{len(slides)})"
        )

    slide = slides[slide_number - 1]

    if not slide.has_narration:
        label = slide.annotation.value
        logger.info("Slide %d: [%s] — no narration to preview.", slide_number, label)
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
    logger.info("Slide %d: %s", slide_number, text)

    # Synthesize with Piper
    tts = PiperTTS(model=piper_model)
    with tempfile.TemporaryDirectory() as tmp:
        audio_path = Path(tmp) / "preview.wav"
        duration = tts.synthesize(text, audio_path)
        logger.info("Duration: %.1fs", duration)

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
    last_error: subprocess.CalledProcessError | None = None
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
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode(errors="replace").strip() if isinstance(e.stderr, bytes) else (e.stderr or "").strip()
            logger.warning(
                "%s failed (exit %d)%s",
                parts[0], e.returncode, ": " + stderr if stderr else "",
            )
            last_error = e
            continue

    if last_error is not None:
        logger.error("All audio players failed for %s", path)
    else:
        logger.warning("Audio saved to %s (no audio player found to play it)", path)
