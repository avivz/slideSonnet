"""Cache layout for a deck's synthesized audio and render artifacts.

By default everything for ``path/deck.pdf`` lives under ``path/.slidesonnet/``:

    .slidesonnet/
      audio/          content-addressed TTS clips (shared across decks in the dir)
      render/<deck>/  page PNGs, assembled tracks, segments (disposable)

Audio is content-addressed, so sharing it across decks is safe. Render
artifacts use positional names (track.wav, page-N.png), so each deck gets its
own subdirectory — otherwise two decks in one directory would interleave files.

**Speech-clip pool.** The audio directory can be moved out of the deck's cache
so several checkouts (git worktrees of one course, say) or a whole course share
one pool of clips. Resolution order, first match wins:

1. ``--audio-dir`` on the command line (sets the env var for the process);
2. the ``SLIDESONNET_AUDIO_DIR`` environment variable (a shell export or a
   course ``.env``);
3. ``[cache] audio_dir`` in ``slidesonnet.toml`` (relative to the toml);
4. the default ``<deck dir>/.slidesonnet/audio/``.

Only the clips move: render scratch stays per deck because it is positional.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from slidesonnet.config import Config

logger = logging.getLogger(__name__)

CACHE_DIRNAME = ".slidesonnet"

#: Environment variable naming the shared speech-clip pool (overrides the toml).
AUDIO_DIR_ENV = "SLIDESONNET_AUDIO_DIR"

AudioDirSource = Literal["env", "config", "default"]


def cache_root(pdf_path: Path) -> Path:
    return pdf_path.resolve().parent / CACHE_DIRNAME


def default_audio_dir(pdf_path: Path) -> Path:
    """The deck-local clip directory used when no pool is configured."""
    return cache_root(pdf_path) / "audio"


def render_dir(pdf_path: Path) -> Path:
    return cache_root(pdf_path) / "render" / pdf_path.stem


@dataclass(frozen=True)
class AudioDirResolution:
    """Where a deck's clips live and which setting chose that."""

    path: Path
    source: AudioDirSource

    @property
    def shared(self) -> bool:
        """True when the clips live outside the deck's own ``.slidesonnet/``.

        A per-deck ``clean`` sweeps a private cache but must not reach into a
        pool other decks depend on — this is the switch it checks.
        """
        return self.source != "default"


def resolve_audio_dir(pdf_path: Path, config: Config | None = None) -> AudioDirResolution:
    """Apply the resolution order documented in the module docstring."""
    env = os.environ.get(AUDIO_DIR_ENV, "").strip()
    if env:
        return AudioDirResolution(Path(env).expanduser().resolve(), "env")
    default = default_audio_dir(pdf_path)
    if config is not None and config.audio_dir is not None:
        configured = config.audio_dir.expanduser().resolve()
        if configured != default:
            return AudioDirResolution(configured, "config")
    return AudioDirResolution(default, "default")


def audio_dir(pdf_path: Path, config: Config | None = None) -> Path:
    """The clip directory for *pdf_path* — the pool when one is configured."""
    return resolve_audio_dir(pdf_path, config).path


def adopt_legacy_audio(pdf_path: Path, pool: Path) -> int:
    """Copy clips from the deck's old local cache into *pool*; return how many.

    Migration on touch: the first time a deck is used with a pool, whatever its
    ``.slidesonnet/audio/`` already holds becomes available to every other deck
    on the pool, so nothing paid is re-bought. Clips are copied, not moved — the
    local dir stays valid if the pool setting is later removed — and a per-deck
    ``clean`` drops the local copies once the pool has them. Only recognizable
    clip names are adopted; a clip already in the pool is left as is.
    """
    from slidesonnet.hashing import parse_audio_filename

    legacy = default_audio_dir(pdf_path)
    if pool.resolve() == legacy.resolve() or not legacy.is_dir():
        return 0
    adopted = 0
    for src in legacy.iterdir():
        if not src.is_file() or parse_audio_filename(src.name) is None:
            continue
        dst = pool / src.name
        if dst.exists() and dst.stat().st_size > 0:
            continue
        pool.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=pool, suffix=".tmp")
        os.close(fd)
        try:
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)  # atomic: a concurrent reader never sees a partial clip
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        adopted += 1
    if adopted:
        logger.info("adopted %d clip(s) from %s into the pool %s", adopted, legacy, pool)
    return adopted
