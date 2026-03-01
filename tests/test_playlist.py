"""Tests for playlist parsing."""

import textwrap
from pathlib import Path

import pytest

from slidesonnet.models import ModuleType
from slidesonnet.playlist import parse_playlist


def test_parse_front_matter(playlist_basic):
    config, entries = parse_playlist(playlist_basic)
    assert config["title"] == "Graph Theory Lecture 1"
    assert config["tts"]["backend"] == "piper"
    assert config["tts"]["piper"]["model"] == "en_US-lessac-medium"
    assert config["video"]["resolution"] == "1920x1080"


def test_parse_module_list(playlist_basic):
    _, entries = parse_playlist(playlist_basic)
    assert len(entries) == 3  # item 3 is commented out with //

    assert entries[0].label == "Introduction"
    assert entries[0].path == Path("01-intro/slides.md")
    assert entries[0].module_type == ModuleType.MARP

    assert entries[1].label == "Animation"
    assert entries[1].path == Path("animations/euler.mp4")
    assert entries[1].module_type == ModuleType.VIDEO

    assert entries[2].label == "Summary"
    assert entries[2].path == Path("02-summary/slides.md")
    assert entries[2].module_type == ModuleType.MARP


def test_auto_detect_types():
    from slidesonnet.models import PlaylistEntry

    assert PlaylistEntry.from_link("a", "slides.md").module_type == ModuleType.MARP
    assert PlaylistEntry.from_link("b", "slides.tex").module_type == ModuleType.BEAMER
    assert PlaylistEntry.from_link("c", "video.mp4").module_type == ModuleType.VIDEO
    assert PlaylistEntry.from_link("d", "video.mkv").module_type == ModuleType.VIDEO
    assert PlaylistEntry.from_link("e", "video.webm").module_type == ModuleType.VIDEO


def test_unknown_extension():
    from slidesonnet.models import PlaylistEntry

    with pytest.raises(ValueError, match="Unknown file type"):
        PlaylistEntry.from_link("x", "file.docx")


def test_absolute_path_rejected():
    from slidesonnet.models import PlaylistEntry

    with pytest.raises(ValueError, match="must be relative"):
        PlaylistEntry.from_link("x", "/etc/slides.md")


def test_path_traversal_rejected():
    from slidesonnet.models import PlaylistEntry

    with pytest.raises(ValueError, match="must not contain"):
        PlaylistEntry.from_link("x", "../secret/slides.md")


def test_comment_lines_ignored(tmp_path):
    playlist = tmp_path / "test.md"
    playlist.write_text(
        textwrap.dedent("""\
        ---
        title: Test
        ---

        # Test

        // This is a comment
        1. [First](a.md)
        // 2. [Commented out](b.md)
        3. [Third](c.md)
    """)
    )
    _, entries = parse_playlist(playlist)
    assert len(entries) == 2
    assert entries[0].label == "First"
    assert entries[1].label == "Third"


def test_non_list_text_ignored(tmp_path):
    playlist = tmp_path / "test.md"
    playlist.write_text(
        textwrap.dedent("""\
        ---
        title: Test
        ---

        # My Presentation

        Some prose text here that should be ignored.

        1. [Only item](slides.md)

        More text.
    """)
    )
    _, entries = parse_playlist(playlist)
    assert len(entries) == 1
    assert entries[0].label == "Only item"


def test_missing_front_matter(tmp_path):
    playlist = tmp_path / "test.md"
    playlist.write_text("1. [Item](slides.md)\n")
    config, entries = parse_playlist(playlist)
    assert config == {}
    assert len(entries) == 1


def test_pronunciation_paths_in_config(playlist_basic):
    config, _ = parse_playlist(playlist_basic)
    assert config["pronunciation"] == ["pronunciation/cs-terms.md"]
