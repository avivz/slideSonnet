"""Content revisions and atomic writes — the basis of the API's conflict checks."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from slidesonnet.atomic import atomic_write_text
from slidesonnet.server.revisions import ABSENT, content_revision


def test_revision_tracks_content_not_mtime(tmp_path: Path) -> None:
    f = tmp_path / "deck.narration"
    assert content_revision(f) == ABSENT
    f.write_text("@a\n  utterance: hi\n", encoding="utf-8")
    first = content_revision(f)
    os.utime(f, (1, 1))  # a touch without a content change keeps the revision
    assert content_revision(f) == first
    f.write_text("@a\n  utterance: hello\n", encoding="utf-8")
    assert content_revision(f) not in (first, ABSENT)


def test_same_second_rewrite_of_equal_size_still_changes_revision(tmp_path: Path) -> None:
    """The stat stamp missed this (WSL second-granularity mtimes); content can't."""
    f = tmp_path / "deck.narration"
    f.write_text("aaaa", encoding="utf-8")
    os.utime(f, (5, 5))
    before = content_revision(f)
    f.write_text("bbbb", encoding="utf-8")
    os.utime(f, (5, 5))
    assert content_revision(f) != before


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
