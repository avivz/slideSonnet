"""Content revisions and atomic writes — the basis of the API's conflict checks."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from slidesonnet.atomic import atomic_write_text
from slidesonnet.server.revisions import (
    _MEMO_MIN_BYTES,
    ABSENT,
    content_revision,
    text_revision,
)


def test_revision_tracks_content_not_mtime(tmp_path: Path) -> None:
    f = tmp_path / "deck.narration"
    assert content_revision(f) == ABSENT
    f.write_text("@a\n  utterance: hi\n", encoding="utf-8")
    first = content_revision(f)
    os.utime(f, (1, 1))  # a touch without a content change keeps the revision
    assert content_revision(f) == first
    f.write_text("@a\n  utterance: hello\n", encoding="utf-8")
    assert content_revision(f) not in (first, ABSENT)


@pytest.mark.parametrize("size", [4, _MEMO_MIN_BYTES], ids=["sidecar", "memoized-pdf"])
def test_same_second_rewrite_of_equal_size_still_changes_revision(
    tmp_path: Path, size: int
) -> None:
    """The stat stamp missed this (WSL second-granularity mtimes); content can't.

    A big file's digest is memoized by stat signature, so the rewrite must also
    invalidate the memo: the ctime moves even when mtime, size and inode don't.
    """
    f = tmp_path / "deck.pdf"
    f.write_bytes(b"a" * size)
    os.utime(f, (5, 5))
    before = content_revision(f)
    assert content_revision(f) == before  # a second read (a memo hit for the big one)
    time.sleep(0.05)  # past the kernel's coarse ctime tick (a same-tick rewrite can't be seen)
    with open(f, "r+b") as fh:  # in place: same inode, same size
        fh.write(b"b" * size)
    os.utime(f, (5, 5))
    assert content_revision(f) == text_revision("b" * size)


def test_atomic_write_replaces_whole_file_and_leaves_no_temp(tmp_path: Path) -> None:
    f = tmp_path / "deck.narration"
    f.write_text("old", encoding="utf-8")
    atomic_write_text(f, "new text")
    assert f.read_text(encoding="utf-8") == "new text"
    assert [p.name for p in tmp_path.iterdir()] == ["deck.narration"]


def test_atomic_write_failure_keeps_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "deck.narration"
    f.write_text("old", encoding="utf-8")

    def boom(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(f, "new")
    assert f.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["deck.narration"]
