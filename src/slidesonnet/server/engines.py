"""One synthesis at a time per engine, across the whole process.

The editor's per-clip generation queue, API generate jobs, preview builds, and
exports can all synthesize. A heavy local model is loaded once per process and
isn't safe to drive from two threads at once, and running two cloud requests
for one deck in parallel buys nothing — so every synthesis path takes its
engine's lock first. Model reuse is unchanged: the warm cache is process-wide.

Lock order: a deck's render lock (``DeckService.render_lock``) is always taken
*before* an engine lock, never after, so preview and export cannot deadlock.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slidesonnet.config import Config
    from slidesonnet.models import Backend

#: The engine the editor starts on when a deck's slidesonnet.toml doesn't name
#: one. Paid, so every synthesis it would bill asks first; the CLI keeps Kokoro.
EDITOR_DEFAULT_ENGINE: Backend = "inworld"


def editor_engine(config: Config) -> Backend:
    """The engine the editor uses for a deck when the session picked none."""
    return config.tts.backend if config.tts.backend_configured else EDITOR_DEFAULT_ENGINE


def with_engine(config: Config, engine: Backend | None) -> Config:
    """*config* with its TTS backend swapped to *engine* (None keeps the configured one)."""
    if engine is None or engine == config.tts.backend:
        return config
    return replace(config, tts=replace(config.tts, backend=engine))


_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def engine_lock(backend: str) -> threading.Lock:
    """The process-wide lock serializing synthesis on *backend*."""
    with _guard:
        lock = _locks.get(backend)
        if lock is None:
            lock = _locks[backend] = threading.Lock()
        return lock
