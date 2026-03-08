"""Tests for playlist parsing."""

import textwrap
from pathlib import Path

import pytest

from slidesonnet.models import ModuleType
from slidesonnet.playlist import parse_playlist


def test_parse_config(playlist_basic):
    config, entries = parse_playlist(playlist_basic)
    assert config["title"] == "Graph Theory Lecture 1"
    assert config["tts"]["backend"] == "piper"
    assert config["tts"]["piper"]["model"] == "en_US-lessac-medium"
    assert config["video"]["resolution"] == "1920x1080"


def test_parse_module_list(playlist_basic):
    _, entries = parse_playlist(playlist_basic)
    assert len(entries) == 3  # item 3 is commented out with //

    assert entries[0].path == Path("01-intro/slides.md")
    assert entries[0].module_type == ModuleType.MARP

    assert entries[1].path == Path("animations/euler.mp4")
    assert entries[1].module_type == ModuleType.VIDEO

    assert entries[2].path == Path("02-summary/slides.md")
    assert entries[2].module_type == ModuleType.MARP


def test_auto_detect_types():
    from slidesonnet.models import PlaylistEntry

    assert PlaylistEntry.from_path("slides.md").module_type == ModuleType.MARP
    assert PlaylistEntry.from_path("slides.tex").module_type == ModuleType.BEAMER
    assert PlaylistEntry.from_path("video.mp4").module_type == ModuleType.VIDEO
    assert PlaylistEntry.from_path("video.mkv").module_type == ModuleType.VIDEO
    assert PlaylistEntry.from_path("video.webm").module_type == ModuleType.VIDEO


def test_unknown_extension():
    from slidesonnet.models import PlaylistEntry

    with pytest.raises(ValueError, match="Unknown file type"):
        PlaylistEntry.from_path("file.docx")


def test_absolute_path_rejected():
    from slidesonnet.models import PlaylistEntry

    with pytest.raises(ValueError, match="must be relative"):
        PlaylistEntry.from_path("/etc/slides.md")


def test_path_traversal_rejected():
    from slidesonnet.models import PlaylistEntry

    with pytest.raises(ValueError, match="must not contain"):
        PlaylistEntry.from_path("../secret/slides.md")


def test_comment_lines_ignored(tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - a.md
          // - b.md
          - c.md
    """)
    )
    _, entries = parse_playlist(playlist)
    assert len(entries) == 2
    assert entries[0].path == Path("a.md")
    assert entries[1].path == Path("c.md")


def test_empty_file_raises(tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text("")
    with pytest.raises(Exception, match="empty"):
        parse_playlist(playlist)


def test_missing_modules_key_raises(tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text("title: Test\n")
    with pytest.raises(Exception, match="modules"):
        parse_playlist(playlist)


def test_modules_not_a_list_raises(tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text("title: Test\nmodules: slides.md\n")
    with pytest.raises(Exception, match="list"):
        parse_playlist(playlist)


def test_module_item_not_a_string_raises(tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text("title: Test\nmodules:\n  - path: slides.md\n")
    with pytest.raises(Exception, match="string"):
        parse_playlist(playlist)


def test_not_a_mapping_raises(tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text("- item1\n- item2\n")
    with pytest.raises(Exception, match="mapping"):
        parse_playlist(playlist)


def test_pronunciation_paths_in_config(playlist_basic):
    config, _ = parse_playlist(playlist_basic)
    assert config["pronunciation"] == ["pronunciation/cs-terms.md"]


def test_unreadable_file_raises(tmp_path):
    playlist = tmp_path / "nonexistent.yaml"
    with pytest.raises(Exception, match="Cannot read playlist file"):
        parse_playlist(playlist)


def test_close_match_suggests_modules(tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text("title: Test\nmoduels:\n  - slides.md\n")
    with pytest.raises(Exception, match="Did you mean 'modules'"):
        parse_playlist(playlist)
