"""Load API keys from a ``.env`` file into the process environment.

Cloud TTS keys (``ELEVENLABS_API_KEY``, ``INWORLD_API_KEY``) live in a ``.env``
next to the deck (or at the project root). The engines read ``os.environ``
directly, but nothing on the synthesis path loaded the file — only
``slidesonnet doctor`` did — so a key sitting in ``.env`` was invisible to actual
generation. The synthesis entry points (:func:`slidesonnet.api._load`) and
:func:`slidesonnet.tts.create_tts` call :func:`load_env`, so every path (CLI,
GUI preview, background queue) sees the key.

The search is anchored at the deck directory when known, then the cwd — so the
key is found no matter where the editor was launched from (e.g. ``$HOME`` while
editing a deck whose ``.env`` is in a tree the cwd never reaches upward).
"""

from __future__ import annotations

from pathlib import Path


def _nearest_dotenv(start: Path) -> str | None:
    """Walk *start* and its parents for the first ``.env`` file, if any."""
    for parent in (start, *start.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            return str(candidate)
    return None


def load_env(start: Path | None = None) -> None:
    """Load a ``.env`` file into ``os.environ``, searched from *start* then cwd.

    *start* (the deck directory, when known) is searched upward first; the cwd is
    searched second. A no-op when python-dotenv isn't installed. python-dotenv's
    default ``override=False`` means an already-present variable is never
    clobbered — so the deck-dir ``.env`` wins over the cwd's, and a shell export
    wins over both. Repeated calls are idempotent.
    """
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    paths: list[str] = []
    if start is not None:
        anchored = _nearest_dotenv(start)
        if anchored is not None:
            paths.append(anchored)
    cwd_env = find_dotenv(usecwd=True)
    if cwd_env and cwd_env not in paths:
        paths.append(cwd_env)
    for path in paths:  # nearest-first; override=False so the first load wins
        load_dotenv(path)
