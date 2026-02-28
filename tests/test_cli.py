"""Tests for the CLI interface."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from slidesonnet import __version__
from slidesonnet.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_version(runner):
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "slideSonnet" in result.output
    assert "build" in result.output
    assert "preview" in result.output
    assert "preview-slide" in result.output
    assert "clean" in result.output
    assert "init" in result.output


def test_build_help(runner):
    result = runner.invoke(main, ["build", "--help"])
    assert result.exit_code == 0
    assert "--tts" in result.output
    assert "--force" in result.output
    assert "piper" in result.output
    assert "elevenlabs" in result.output


def test_build_nonexistent_file(runner):
    result = runner.invoke(main, ["build", "nonexistent.md"])
    assert result.exit_code != 0


def test_clean_no_build_dir(runner, tmp_path):
    playlist = tmp_path / "test.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")
    result = runner.invoke(main, ["clean", str(playlist)])
    assert result.exit_code == 0
    assert "Nothing to clean" in result.output


def test_clean_removes_build_dir(runner, tmp_path):
    playlist = tmp_path / "test.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")
    build_dir = tmp_path / ".build"
    build_dir.mkdir()
    (build_dir / "artifact.mp4").touch()

    result = runner.invoke(main, ["clean", str(playlist)])
    assert result.exit_code == 0
    assert "Removed" in result.output
    assert not build_dir.exists()


def test_build_calls_pipeline(runner, tmp_path):
    playlist = tmp_path / "lecture.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / ".build" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist)])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override=None, force=False, jobs=None)


def test_build_with_tts_override(runner, tmp_path):
    playlist = tmp_path / "lecture.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / ".build" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist), "--tts", "elevenlabs"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist, tts_override="elevenlabs", force=False, jobs=None
        )


def test_build_with_force(runner, tmp_path):
    playlist = tmp_path / "lecture.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / ".build" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist), "--force"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override=None, force=True, jobs=None)


def test_build_with_jobs(runner, tmp_path):
    playlist = tmp_path / "lecture.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / ".build" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist), "--jobs", "4"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override=None, force=False, jobs=4)


def test_preview_calls_build_with_piper(runner, tmp_path):
    playlist = tmp_path / "lecture.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / ".build" / "lecture.mp4"
        result = runner.invoke(main, ["preview", str(playlist)])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override="piper", jobs=None)


def test_preview_with_jobs(runner, tmp_path):
    playlist = tmp_path / "lecture.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / ".build" / "lecture.mp4"
        result = runner.invoke(main, ["preview", str(playlist), "-j", "2"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override="piper", jobs=2)


def test_init_blank(runner, tmp_path):
    target = tmp_path / "newproject"
    result = runner.invoke(main, ["init", str(target), "--blank"])
    assert result.exit_code == 0
    assert "Project created" in result.output
    assert (target / "lecture01.md").exists()
    assert (target / ".gitignore").exists()


def test_init_example(runner, tmp_path):
    target = tmp_path / "newproject"
    result = runner.invoke(main, ["init", str(target), "--example"])
    assert result.exit_code == 0
    assert "Example project" in result.output
    assert (target / "lecture01.md").exists()
    assert (target / "02-definitions" / "slides.md").exists()


def test_init_from(runner, tmp_path):
    # Create source project
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_playlist = source_dir / "lecture.md"
    source_playlist.write_text(
        "---\ntitle: Source\ntts:\n  backend: piper\npronunciation:\n"
        "  - pron/terms.md\n---\n1. [Intro](intro/slides.md)\n"
    )
    pron_dir = source_dir / "pron"
    pron_dir.mkdir()
    (pron_dir / "terms.md").write_text("**Euler**: OY-ler\n")

    target = tmp_path / "target"
    result = runner.invoke(main, ["init", str(target), "--from", str(source_playlist)])
    assert result.exit_code == 0
    assert "copied config" in result.output
    assert (target / "lecture01.md").exists()


def test_init_default_is_blank(runner, tmp_path):
    target = tmp_path / "newproject"
    result = runner.invoke(main, ["init", str(target)])
    assert result.exit_code == 0
    assert (target / "lecture01.md").exists()


def test_preview_slide_calls_preview(runner, tmp_path):
    slides = tmp_path / "slides.md"
    slides.write_text("---\nmarp: true\n---\n\n# Hello\n\n<!-- say: Welcome. -->\n")

    with patch("slidesonnet.cli.preview_single_slide") as mock_preview:
        result = runner.invoke(main, ["preview-slide", str(slides), "1"])
        assert result.exit_code == 0
        mock_preview.assert_called_once_with(slides, 1, playlist_path=None)


def test_preview_slide_with_playlist(runner, tmp_path):
    slides = tmp_path / "slides.md"
    slides.write_text("---\nmarp: true\n---\n\n# Hello\n\n<!-- say: Welcome. -->\n")
    playlist = tmp_path / "lecture.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](slides.md)\n")

    with patch("slidesonnet.cli.preview_single_slide") as mock_preview:
        result = runner.invoke(main, ["preview-slide", str(slides), "1", "-p", str(playlist)])
        assert result.exit_code == 0
        mock_preview.assert_called_once_with(slides, 1, playlist_path=playlist)
