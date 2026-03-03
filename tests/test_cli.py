"""Tests for the CLI interface."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from slidesonnet import __version__
from slidesonnet.cli import main
from slidesonnet.pipeline import DryRunResult, ListResult, SlideInfo

_MINIMAL_PLAYLIST = "title: test\nmodules:\n  - a.md\n"


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
    assert "pdf" in result.output
    assert "list" in result.output


def test_build_help(runner):
    result = runner.invoke(main, ["build", "--help"])
    assert result.exit_code == 0
    assert "--tts" in result.output
    assert "piper" in result.output
    assert "elevenlabs" in result.output


def test_build_nonexistent_file(runner):
    result = runner.invoke(main, ["build", "nonexistent.yaml"])
    assert result.exit_code != 0


def test_clean_no_build_dir(runner, tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    result = runner.invoke(main, ["clean", str(playlist)])
    assert result.exit_code == 0
    assert "Nothing to clean" in result.output


def test_clean_removes_build_dir(runner, tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()
    (build_dir / "artifact.mp4").touch()

    result = runner.invoke(main, ["clean", str(playlist), "--keep", "nothing", "--yes"])
    assert result.exit_code == 0
    assert "Removed" in result.output
    assert not build_dir.exists()


def test_clean_default_keep_api(runner, tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()
    (build_dir / ".doit.db").touch()

    with patch("slidesonnet.cli.run_clean") as mock_clean:
        result = runner.invoke(main, ["clean", str(playlist)])
        assert result.exit_code == 0
        mock_clean.assert_called_once_with(playlist, keep="api")
        assert "Cleaned" in result.output


def test_clean_keep_nothing(runner, tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()

    with patch("slidesonnet.cli.run_clean") as mock_clean:
        result = runner.invoke(main, ["clean", str(playlist), "--keep", "nothing", "--yes"])
        assert result.exit_code == 0
        mock_clean.assert_called_once_with(playlist, keep="nothing")
        assert "Removed" in result.output


def test_clean_keep_choices(runner, tmp_path):
    """All keep levels are accepted."""
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()

    for level in ("nothing", "api", "current", "exact"):
        with patch("slidesonnet.cli.run_clean"):
            result = runner.invoke(main, ["clean", str(playlist), "--keep", level, "--yes"])
            assert result.exit_code == 0, f"--keep {level} failed"


def test_build_calls_pipeline(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / "cache" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist)])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override=None, preview=False, until=None)


def test_build_with_tts_override(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / "cache" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist), "--tts", "elevenlabs"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist, tts_override="elevenlabs", preview=False, until=None
        )


def test_build_with_preview(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / "cache" / "lecture_preview.mp4"
        result = runner.invoke(main, ["build", str(playlist), "--preview"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override=None, preview=True, until=None)


def test_build_help_includes_preview(runner):
    result = runner.invoke(main, ["build", "--help"])
    assert result.exit_code == 0
    assert "--preview" in result.output


def test_preview_calls_build_with_piper(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / "cache" / "lecture.mp4"
        result = runner.invoke(main, ["preview", str(playlist)])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override="piper", preview=True, until=None)


def test_init_md(runner, tmp_path):
    target = tmp_path / "newproject"
    result = runner.invoke(main, ["init", "md", str(target)])
    assert result.exit_code == 0
    assert "Project created" in result.output
    assert (target / "lecture.yaml").exists()
    assert (target / "01-intro" / "slides.md").exists()
    assert (target / "02-definitions" / "slides.md").exists()


def test_init_tex(runner, tmp_path):
    target = tmp_path / "newproject"
    result = runner.invoke(main, ["init", "tex", str(target)])
    assert result.exit_code == 0
    assert "Project created" in result.output
    assert (target / "lecture.yaml").exists()
    assert (target / "01-intro" / "slides.tex").exists()
    assert (target / "02-definitions" / "slides.tex").exists()


def test_init_default_dir(runner, tmp_path):
    with patch("slidesonnet.cli.init_project") as mock_init:
        result = runner.invoke(main, ["init", "md"])
        assert result.exit_code == 0
        assert "Project created" in result.output
        mock_init.assert_called_once_with(Path("."), fmt="md")


def test_init_refuses_overwrite(runner, tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "lecture.yaml").write_text("existing content")
    result = runner.invoke(main, ["init", "md", str(target)])
    assert result.exit_code == 1


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
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text("title: test\nmodules:\n  - slides.md\n")

    with patch("slidesonnet.cli.preview_single_slide") as mock_preview:
        result = runner.invoke(main, ["preview-slide", str(slides), "1", "-p", str(playlist)])
        assert result.exit_code == 0
        mock_preview.assert_called_once_with(slides, 1, playlist_path=playlist)


# ---- Dry-run CLI tests ----


def test_dry_run_calls_run_dry_run(runner, tmp_path):
    """--dry-run should call run_dry_run, not run_build."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    mock_result = DryRunResult(
        total_narrated=5, cached=3, needs_tts=2, uncached_chars=400, tts_backend="piper"
    )

    with (
        patch("slidesonnet.cli.run_dry_run", return_value=mock_result) as mock_dry,
        patch("slidesonnet.cli.run_build") as mock_build,
    ):
        result = runner.invoke(main, ["build", str(playlist), "--dry-run"])
        assert result.exit_code == 0
        mock_dry.assert_called_once_with(playlist, tts_override=None)
        mock_build.assert_not_called()


def test_dry_run_short_flag(runner, tmp_path):
    """-n short flag should work."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    mock_result = DryRunResult(
        total_narrated=2, cached=2, needs_tts=0, uncached_chars=0, tts_backend="piper"
    )

    with patch("slidesonnet.cli.run_dry_run", return_value=mock_result):
        result = runner.invoke(main, ["build", str(playlist), "-n"])
        assert result.exit_code == 0


def test_dry_run_passes_tts_override(runner, tmp_path):
    """--dry-run with --tts should pass override."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    mock_result = DryRunResult(
        total_narrated=1, cached=0, needs_tts=1, uncached_chars=50, tts_backend="elevenlabs"
    )

    with patch("slidesonnet.cli.run_dry_run", return_value=mock_result) as mock_dry:
        result = runner.invoke(main, ["build", str(playlist), "--dry-run", "--tts", "elevenlabs"])
        assert result.exit_code == 0
        mock_dry.assert_called_once_with(playlist, tts_override="elevenlabs")


def test_dry_run_output_needs_tts(runner, tmp_path):
    """Output format when some slides need TTS."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    mock_result = DryRunResult(
        total_narrated=8, cached=5, needs_tts=3, uncached_chars=1200, tts_backend="elevenlabs"
    )

    with patch("slidesonnet.cli.run_dry_run", return_value=mock_result):
        result = runner.invoke(main, ["build", str(playlist), "--dry-run"])
        assert result.exit_code == 0
        assert "8 narrated slides" in result.output
        assert "5 cached" in result.output
        assert "3 need TTS" in result.output
        assert "1,200 characters" in result.output
        assert "elevenlabs" in result.output


def test_dry_run_output_all_cached(runner, tmp_path):
    """Output format when all slides are cached."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    mock_result = DryRunResult(
        total_narrated=8, cached=8, needs_tts=0, uncached_chars=0, tts_backend="piper"
    )

    with patch("slidesonnet.cli.run_dry_run", return_value=mock_result):
        result = runner.invoke(main, ["build", str(playlist), "--dry-run"])
        assert result.exit_code == 0
        assert "8 narrated slides: all cached" in result.output


def test_dry_run_output_no_narrated(runner, tmp_path):
    """Output format when no narrated slides."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    mock_result = DryRunResult(
        total_narrated=0, cached=0, needs_tts=0, uncached_chars=0, tts_backend="piper"
    )

    with patch("slidesonnet.cli.run_dry_run", return_value=mock_result):
        result = runner.invoke(main, ["build", str(playlist), "--dry-run"])
        assert result.exit_code == 0
        assert "No narrated slides" in result.output


# ---- --until CLI tests ----


def test_build_with_until_slides(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / "cache" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist), "--until", "slides"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist, tts_override=None, preview=False, until="slides"
        )


def test_build_with_until_tts(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / "cache" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist), "--until", "tts"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(playlist, tts_override=None, preview=False, until="tts")


def test_build_with_until_segments(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / "cache" / "lecture.mp4"
        result = runner.invoke(main, ["build", str(playlist), "--until", "segments"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist, tts_override=None, preview=False, until="segments"
        )


def test_preview_with_until(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = tmp_path / "cache" / "lecture.mp4"
        result = runner.invoke(main, ["preview", str(playlist), "--until", "tts"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist, tts_override="piper", preview=True, until="tts"
        )


def test_build_until_invalid_choice(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    result = runner.invoke(main, ["build", str(playlist), "--until", "invalid"])
    assert result.exit_code != 0


# ---- pdf CLI tests ----


def test_pdf_calls_export_pdfs(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_export_pdfs") as mock_export:
        mock_export.return_value = [tmp_path / "a.pdf"]
        result = runner.invoke(main, ["pdf", str(playlist)])
        assert result.exit_code == 0
        mock_export.assert_called_once_with(playlist)
        assert "a.pdf" in result.output


def test_pdf_no_modules(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_export_pdfs") as mock_export:
        mock_export.return_value = []
        result = runner.invoke(main, ["pdf", str(playlist)])
        assert result.exit_code == 0
        assert "No slide modules" in result.output


# ---- list CLI tests ----


def test_list_table_output(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_list_slides") as mock_list:
        mock_list.return_value = ListResult(
            slides=[
                SlideInfo("a.md", 1, "default", "Hello world", cached=True, chars=312),
                SlideInfo("a.md", 2, "alice", "[silent]", cached=None, chars=0),
            ],
            tts_backend="piper",
        )
        result = runner.invoke(main, ["list", str(playlist)])
        assert result.exit_code == 0
        mock_list.assert_called_once_with(playlist, tts_override=None)
        assert "#" in result.output
        assert "File" in result.output
        assert "Voice" in result.output
        assert "Chars" in result.output
        assert "Narration" in result.output
        assert "\u25cf" in result.output  # cached symbol
        assert "Hello world" in result.output
        assert "312" in result.output
        assert "alice" in result.output
        assert "[silent]" in result.output
        assert "\u2013" in result.output  # dash for silent chars
        # Summary line
        assert "2 slides" in result.output
        assert "1 cached" in result.output


def test_list_with_tts_override(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_list_slides") as mock_list:
        mock_list.return_value = ListResult(
            slides=[SlideInfo("a.md", 1, "default", "Hello", cached=True, chars=5)],
            tts_backend="piper",
        )
        result = runner.invoke(main, ["list", str(playlist), "--tts", "piper"])
        assert result.exit_code == 0
        mock_list.assert_called_once_with(playlist, tts_override="piper")


def test_list_no_slides(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_list_slides") as mock_list:
        mock_list.return_value = ListResult(slides=[], tts_backend="piper")
        result = runner.invoke(main, ["list", str(playlist)])
        assert result.exit_code == 0
        assert "No slides found" in result.output


def test_list_mixed_cached_uncached(runner, tmp_path):
    """Table shows ● for cached, ○ for uncached, summary with TTS info."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_list_slides") as mock_list:
        mock_list.return_value = ListResult(
            slides=[
                SlideInfo("a.md", 1, "default", "Hello world", cached=True, chars=312),
                SlideInfo("a.md", 2, "default", "This is uncached", cached=False, chars=187),
                SlideInfo("a.md", 3, "alice", "[silent]", cached=None, chars=0),
            ],
            tts_backend="piper",
        )
        result = runner.invoke(main, ["list", str(playlist)])
        assert result.exit_code == 0
        assert "\u25cf" in result.output  # cached
        assert "\u25cb" in result.output  # uncached
        assert "3 slides" in result.output
        assert "1 cached" in result.output
        assert "1 needs TTS" in result.output
        assert "187 characters" in result.output
        assert "piper" in result.output


# ---- Confirmation prompt tests ----


def test_clean_keep_nothing_prompts(runner, tmp_path):
    """clean --keep nothing without --yes prompts for confirmation."""
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()

    with patch("slidesonnet.cli.run_clean") as mock_clean:
        result = runner.invoke(main, ["clean", str(playlist), "--keep", "nothing"], input="y\n")
        assert result.exit_code == 0
        assert "delete all cached audio" in result.output
        mock_clean.assert_called_once()


def test_clean_keep_nothing_aborts(runner, tmp_path):
    """clean --keep nothing aborts when user declines."""
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()

    with patch("slidesonnet.cli.run_clean") as mock_clean:
        result = runner.invoke(main, ["clean", str(playlist), "--keep", "nothing"], input="n\n")
        assert result.exit_code != 0
        mock_clean.assert_not_called()


def test_clean_keep_nothing_yes_flag(runner, tmp_path):
    """clean --keep nothing --yes skips the prompt."""
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()

    with patch("slidesonnet.cli.run_clean") as mock_clean:
        result = runner.invoke(main, ["clean", str(playlist), "--keep", "nothing", "--yes"])
        assert result.exit_code == 0
        assert "delete all cached audio" not in result.output
        mock_clean.assert_called_once()


def test_clean_keep_api_no_prompt(runner, tmp_path):
    """clean --keep api (default) never prompts."""
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()
    (build_dir / ".doit.db").touch()

    with patch("slidesonnet.cli.run_clean"):
        result = runner.invoke(main, ["clean", str(playlist)])
        assert result.exit_code == 0
        assert "Continue?" not in result.output
