"""Saved lengths of pooled speech clips, so a play doesn't re-measure the deck.

Measuring a compressed clip exactly means decoding it with ffmpeg (~0.1 s
each; see :func:`slidesonnet.video.composer.get_duration`), and every preview
or export needs every clip's length — so an 80-line deck spent ~13 s measuring
files that had not changed. Lengths are saved in ``<pool>/durations.json`` —
the engine's own figure for a clip it just made, a measurement otherwise —
keyed on the clip's name and checked against its size and modification time:
a regenerated take (same name, new file) is measured afresh.

The file is a cache and nothing more. A missing, unreadable, or stale entry
just means measuring again, and a failed save is logged and swallowed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from slidesonnet.atomic import atomic_write_text
from slidesonnet.pool import DURATIONS_FILENAME

logger = logging.getLogger(__name__)

#: ``name -> [size, mtime_ns, seconds]``
_Entries = dict[str, list[float]]


class ClipDurations:
    """Lengths of the clips in one pool directory; call :meth:`save` when done."""

    def __init__(self, audio_dir: Path, measure: Callable[[Path], float]) -> None:
        self._path = audio_dir / DURATIONS_FILENAME
        self._measure = measure
        self._entries = _read(self._path)
        self._fresh: _Entries = {}

    def get(self, clip: Path) -> float:
        st = clip.stat()
        entry = self._entries.get(clip.name)
        if entry is not None and entry[:2] == [st.st_size, st.st_mtime_ns]:
            return entry[2]
        seconds = self._measure(clip)
        self._entries[clip.name] = self._fresh[clip.name] = [st.st_size, st.st_mtime_ns, seconds]
        return seconds

    def record(self, clip: Path, seconds: float) -> None:
        """Remember a length the engine reported for a clip it just wrote."""
        st = clip.stat()
        self._entries[clip.name] = self._fresh[clip.name] = [st.st_size, st.st_mtime_ns, seconds]

    def save(self) -> None:
        """Merge new measurements into the file (another process may have added some)."""
        if not self._fresh:
            return
        try:
            merged = _read(self._path) | self._fresh
            atomic_write_text(self._path, json.dumps(merged, separators=(",", ":")))
            self._fresh = {}
        except OSError:
            logger.warning("could not save clip lengths to %s", self._path, exc_info=True)


def _read(path: Path) -> _Entries:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        name: entry
        for name, entry in raw.items()
        if isinstance(entry, list)
        and len(entry) == 3
        and all(isinstance(v, int | float) for v in entry)
    }
