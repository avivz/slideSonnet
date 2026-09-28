"""Atomic file replacement: a reader sees the old file or the new one, never half.

A sidecar is watched by the editor, by agents, and by other tools. A plain
``write_text`` truncates first and then writes, so a watcher that polls in
between reads an empty or partial file. Writing a sibling temp file and
``os.replace``-ing it over the target is atomic on POSIX filesystems.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write *text* to *path* through a same-directory temp file and an atomic rename.

    The temp file lives next to the target so the rename never crosses a
    filesystem. On any failure the temp file is removed and the target is left
    exactly as it was.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        with contextlib.suppress(OSError):  # keep the original's permissions
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
