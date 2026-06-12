"""Cache layout for a deck's synthesized audio and render artifacts.

Everything for ``path/deck.pdf`` lives under ``path/.slidesonnet/``:

    .slidesonnet/
      audio/          content-addressed TTS clips (shared across decks in the dir)
      render/<deck>/  page PNGs, assembled tracks, segments (disposable)

Audio is content-addressed, so sharing it across decks is safe. Render
artifacts use positional names (track.wav, page-N.png), so each deck gets its
own subdirectory — otherwise two decks in one directory would interleave files.
"""

from __future__ import annotations

from pathlib import Path

CACHE_DIRNAME = ".slidesonnet"


def cache_root(pdf_path: Path) -> Path:
    return pdf_path.resolve().parent / CACHE_DIRNAME


def audio_dir(pdf_path: Path) -> Path:
    return cache_root(pdf_path) / "audio"


def render_dir(pdf_path: Path) -> Path:
    return cache_root(pdf_path) / "render" / pdf_path.stem
