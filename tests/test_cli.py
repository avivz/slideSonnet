"""Tests for the CLI interface."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from slidesonnet.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_version(runner):
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_help(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "slideSonnet" in result.output
    assert "build" in result.output
    assert "preview" in result.output
    assert "clean" in result.output


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
        mock_build.assert_called_once_with(playlist, tts_override=None, force=False)


def test_build_with_tts_override(runner, tmp_path):
    playlist = tmp_path / "lecture.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / ".build" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist), "--tts", "elevenlabs"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override="elevenlabs", force=False)


def test_build_with_force(runner, tmp_path):
    playlist = tmp_path / "lecture.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / ".build" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist), "--force"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override=None, force=True)


def test_preview_calls_build_with_piper(runner, tmp_path):
    playlist = tmp_path / "lecture.md"
    playlist.write_text("---\ntitle: test\n---\n1. [a](a.md)\n")

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / ".build" / "lecture.mp4"
        result = runner.invoke(main, ["preview", str(playlist)])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override="piper")
