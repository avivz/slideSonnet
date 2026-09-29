"""Per-deck ``.env`` values (API keys, the clip pool), read without touching ``os.environ``.

Cloud TTS keys (``INWORLD_API_KEY``) and the pool (``SLIDESONNET_AUDIO_DIR``)
may live in a ``.env`` next to the deck (or higher up, at a course root). One
editor process serves many decks, so the file is *read* per deck, never loaded
into the process environment: loading it would let the first deck's ``.env``
win for every deck after it (billing the wrong account, or writing clips into
the wrong pool).

Lookup order for :func:`getenv`, first match wins:

1. the process environment (a shell export, or ``--audio-dir``);
2. the nearest ``.env`` from the deck directory upward;
3. the nearest ``.env`` from the cwd upward.

The deck directory comes first among the files so a key is found no matter
where the editor was launched from (e.g. ``$HOME``).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

_cache: dict[Path, tuple[tuple[int, int], dict[str, str]]] = {}
_cache_lock = threading.Lock()


def _nearest_dotenv(start: Path) -> Path | None:
    """Walk *start* and its parents for the first ``.env`` file, if any."""
    for parent in (start, *start.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def _read(path: Path) -> dict[str, str]:
    """The ``.env`` file's values (cached until the file changes)."""
    try:
        from dotenv import dotenv_values
    except ImportError:  # python-dotenv missing: only the process environment counts
        return {}
    try:
        st = path.stat()
    except OSError:
        return {}
    stamp = (st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get(path)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    values = {k: v for k, v in dotenv_values(path).items() if v is not None}
    with _cache_lock:
        _cache[path] = (stamp, values)
    return values


def dotenv_files(start: Path | None = None) -> list[Path]:
    """The ``.env`` files that apply: nearest to *start* (the deck dir), then the cwd's."""
    found: list[Path] = []
    for origin in (start, Path.cwd()):
        if origin is None:
            continue
        path = _nearest_dotenv(origin.resolve())
        if path is not None and path not in found:
            found.append(path)
    return found


def deck_env(start: Path | None = None) -> dict[str, str]:
    """Merged ``.env`` values for a deck in *start* (nearest file wins); no side effects."""
    merged: dict[str, str] = {}
    for path in reversed(dotenv_files(start)):
        merged.update(_read(path))
    return merged


def getenv(name: str, start: Path | None = None) -> str | None:
    """*name* from the process environment, else from the deck's ``.env`` (see above)."""
    value = os.environ.get(name)
    if value:
        return value
    return deck_env(start).get(name) or None
