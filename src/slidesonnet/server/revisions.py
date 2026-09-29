"""Content revisions of a deck's source files.

A revision is a short hash of a file's bytes, so it changes exactly when the
content does — unlike an (mtime, size) stamp, which misses a same-size rewrite
inside one timestamp tick. Clients send the revision they edited against; a
mismatch is a conflict (HTTP 409), never a silent overwrite.

Hashing a large PDF on every request would be wasteful, so digests of big files
are memoized per (mtime_ns, ctime_ns, size, inode). Small files — every sidecar,
config, and review log — are simply re-hashed: cheap, and immune to a stat
signature that fails to move (coarse timestamps on Windows-mounted drives).
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path

#: The revision of a file that does not exist.
ABSENT = "absent"

_DIGEST_CHARS = 16
#: Files at least this large are memoized by stat signature (PDFs); smaller are re-hashed.
_MEMO_MIN_BYTES = 256 * 1024
_memo: dict[str, tuple[tuple[int, int, int, int], str]] = {}
_memo_lock = threading.Lock()


def file_sha256(path: Path) -> str:
    """Hex SHA-256 of *path*'s bytes, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_revision(path: Path) -> str:
    """Short content hash of *path*, or :data:`ABSENT` when it is missing."""
    key = str(path)
    try:
        st = Path(path).stat()
    except OSError:
        return ABSENT
    sig = (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)
    memoize = st.st_size >= _MEMO_MIN_BYTES
    if memoize:
        with _memo_lock:
            hit = _memo.get(key)
        if hit is not None and hit[0] == sig:
            return hit[1]
    try:
        rev = file_sha256(path)[:_DIGEST_CHARS]
    except OSError:
        return ABSENT
    if memoize:
        with _memo_lock:
            _memo[key] = (sig, rev)
    return rev


def text_revision(text: str) -> str:
    """The revision a file holding exactly *text* (UTF-8) would have."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


@dataclass(frozen=True)
class SourceRevisions:
    """One revision per deck source: what a snapshot was built from."""

    narration: str
    pdf: str
    config: str
    review: str
