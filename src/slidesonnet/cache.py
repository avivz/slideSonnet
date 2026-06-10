"""Cache layout for a deck's synthesized audio and render artifacts.

Everything for ``path/deck.pdf`` lives under ``path/.slidesonnet/``:

    .slidesonnet/
      audio/    content-addressed TTS clips (shared across decks in the dir)
      render/   page PNGs, assembled tracks, concat lists (disposable)
"""

from __future__ import annotations

from pathlib import Path

CACHE_DIRNAME = ".slidesonnet"


def cache_root(pdf_path: Path) -> Path:
    return pdf_path.resolve().parent / CACHE_DIRNAME


def audio_dir(pdf_path: Path) -> Path:
    return cache_root(pdf_path) / "audio"


def render_dir(pdf_path: Path) -> Path:
    return cache_root(pdf_path) / "render"
