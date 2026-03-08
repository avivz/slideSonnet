"""Tests for the CLI interface."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from slidesonnet import __version__
from slidesonnet.clean import CleanResult
from slidesonnet.cli import main
from slidesonnet.exceptions import APINotAllowedError
from slidesonnet.pipeline import (
    BuildResult,
    DryRunResult,
    ListResult,
    SlideInfo,
    UtteranceModule,
    UtteranceSlide,
)

# Re-usable assertion kwargs for run_build calls (includes no_srt default)
_BUILD_DEFAULTS = dict(quiet=False, no_srt=False)

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

    with patch("slidesonnet.cli.run_clean", return_value=CleanResult(5, 1024, 2)) as mock_clean:
        result = runner.invoke(main, ["clean", str(playlist)])
        assert result.exit_code == 0
        mock_clean.assert_called_once_with(playlist, keep="api")
        assert "Cleaned" in result.output


def test_clean_keep_nothing(runner, tmp_path):
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()

    with patch("slidesonnet.cli.run_clean", return_value=CleanResult(5, 1024, 0)) as mock_clean:
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
        with patch("slidesonnet.cli.run_clean", return_value=CleanResult(3, 512, 1)):
            result = runner.invoke(main, ["clean", str(playlist), "--keep", level, "--yes"])
            assert result.exit_code == 0, f"--keep {level} failed"


def test_build_calls_pipeline(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["build", str(playlist)])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override=None,
            preview=False,
            until=None,
            quiet=False,
            no_srt=False,
            allow_api=False,
            output_override=None,
        )


def test_build_with_tts_override(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["build", str(playlist), "--tts", "elevenlabs"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override="elevenlabs",
            preview=False,
            until=None,
            quiet=False,
            no_srt=False,
            allow_api=True,
            output_override=None,
        )


def test_build_with_preview(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture_preview.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["build", str(playlist), "--preview"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override=None,
            preview=True,
            until=None,
            quiet=False,
            no_srt=False,
            allow_api=False,
            output_override=None,
        )


def test_build_help_includes_preview(runner):
    result = runner.invoke(main, ["build", "--help"])
    assert result.exit_code == 0
    assert "--preview" in result.output


def test_preview_calls_build_with_piper(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["preview", str(playlist)])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override="piper",
            preview=True,
            until=None,
            quiet=False,
            no_srt=False,
            output_override=None,
        )


def test_init_md(runner, tmp_path):
    target = tmp_path / "newproject"
    result = runner.invoke(main, ["init", "md", str(target)])
    assert result.exit_code == 0
    assert "Project created" in result.output
    assert (target / "slidesonnet.yaml").exists()
    assert (target / "01-intro" / "slides.md").exists()
    assert (target / "02-definitions" / "slides.md").exists()


def test_init_tex(runner, tmp_path):
    target = tmp_path / "newproject"
    result = runner.invoke(main, ["init", "tex", str(target)])
    assert result.exit_code == 0
    assert "Project created" in result.output
    assert (target / "slidesonnet.yaml").exists()
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
    (target / "slidesonnet.yaml").write_text("existing content")
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
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(
            output_path=out,
            elapsed_seconds=1.0,
            until="slides",
        )
        result = runner.invoke(main, ["build", str(playlist), "--until", "slides"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override=None,
            preview=False,
            until="slides",
            quiet=False,
            no_srt=False,
            allow_api=False,
            output_override=None,
        )


def test_build_with_until_tts(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(
            output_path=out,
            elapsed_seconds=1.0,
            until="tts",
        )
        result = runner.invoke(main, ["build", str(playlist), "--until", "tts"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override=None,
            preview=False,
            until="tts",
            quiet=False,
            no_srt=False,
            allow_api=False,
            output_override=None,
        )


def test_build_with_until_segments(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(
            output_path=out,
            elapsed_seconds=1.0,
            until="segments",
        )
        result = runner.invoke(main, ["build", str(playlist), "--until", "segments"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override=None,
            preview=False,
            until="segments",
            quiet=False,
            no_srt=False,
            allow_api=False,
            output_override=None,
        )


def test_preview_with_until(runner, tmp_path):
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(
            output_path=out,
            elapsed_seconds=1.0,
            until="tts",
        )
        result = runner.invoke(main, ["preview", str(playlist), "--until", "tts"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override="piper",
            preview=True,
            until="tts",
            quiet=False,
            no_srt=False,
            output_override=None,
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
        pdf_out = tmp_path / "lecture.pdf"
        mock_export.return_value = pdf_out
        result = runner.invoke(main, ["pdf", str(playlist)])
        assert result.exit_code == 0
        mock_export.assert_called_once_with(playlist)
        assert "lecture.pdf" in result.output


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

    with patch("slidesonnet.cli.run_clean", return_value=CleanResult(5, 1024, 0)) as mock_clean:
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

    with patch("slidesonnet.cli.run_clean", return_value=CleanResult(5, 1024, 0)) as mock_clean:
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

    with patch("slidesonnet.cli.run_clean", return_value=CleanResult(3, 512, 2)):
        result = runner.invoke(main, ["clean", str(playlist)])
        assert result.exit_code == 0
        assert "Continue?" not in result.output


# ---- --no-srt and subtitles CLI tests ----


def test_build_no_srt_flag(runner, tmp_path):
    """--no-srt passes no_srt=True to run_build."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["build", str(playlist), "--no-srt"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override=None,
            preview=False,
            until=None,
            quiet=False,
            no_srt=True,
            allow_api=False,
            output_override=None,
        )


def test_preview_no_srt_flag(runner, tmp_path):
    """preview --no-srt passes no_srt=True."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["preview", str(playlist), "--no-srt"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override="piper",
            preview=True,
            until=None,
            quiet=False,
            no_srt=True,
            output_override=None,
        )


def test_build_result_with_srt(runner, tmp_path):
    """Build output includes SRT filename when srt_path is set."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    out = tmp_path / "lecture.mp4"
    out.write_bytes(b"\x00" * 1024)
    srt = tmp_path / "lecture.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0, srt_path=srt)
        result = runner.invoke(main, ["build", str(playlist)])
        assert result.exit_code == 0
        assert "lecture.srt" in result.output


def test_subtitles_command(runner, tmp_path):
    """subtitles command calls run_generate_srt and prints path."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    srt_path = tmp_path / "lecture.srt"

    with patch("slidesonnet.cli.run_generate_srt", return_value=srt_path) as mock_srt:
        result = runner.invoke(main, ["subtitles", str(playlist)])
        assert result.exit_code == 0
        mock_srt.assert_called_once_with(playlist, tts_override=None, output=None)
        assert str(srt_path) in result.output


def test_subtitles_command_with_output(runner, tmp_path):
    """subtitles -o custom.srt passes output path."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    custom_srt = tmp_path / "custom.srt"

    with patch("slidesonnet.cli.run_generate_srt", return_value=custom_srt) as mock_srt:
        result = runner.invoke(main, ["subtitles", str(playlist), "-o", str(custom_srt)])
        assert result.exit_code == 0
        mock_srt.assert_called_once_with(playlist, tts_override=None, output=custom_srt)


def test_help_includes_subtitles(runner):
    """Main help lists the subtitles command."""
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "subtitles" in result.output


# ---- --allow-api CLI tests ----


def test_allow_api_flag_forwarded(runner, tmp_path):
    """--allow-api is forwarded to run_build."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["build", str(playlist), "--allow-api"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override=None,
            preview=False,
            until=None,
            quiet=False,
            no_srt=False,
            allow_api=True,
            output_override=None,
        )


def test_tts_elevenlabs_implies_allow_api(runner, tmp_path):
    """--tts elevenlabs implicitly sets allow_api=True."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["build", str(playlist), "--tts", "elevenlabs"])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(
            playlist,
            tts_override="elevenlabs",
            preview=False,
            until=None,
            quiet=False,
            no_srt=False,
            allow_api=True,
            output_override=None,
        )


def test_api_not_allowed_error_renders(runner, tmp_path):
    """APINotAllowedError shows message on stderr and exits 1."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.side_effect = APINotAllowedError(
            "Build requires ElevenLabs API calls for 2 uncached slides"
        )
        result = runner.invoke(main, ["build", str(playlist)])
        assert result.exit_code == 1
        assert "ElevenLabs API calls" in result.output


def test_build_help_includes_allow_api(runner):
    """Build help mentions --allow-api."""
    result = runner.invoke(main, ["build", "--help"])
    assert result.exit_code == 0
    assert "--allow-api" in result.output


# ---- utterances CLI tests ----


def test_help_includes_utterances(runner):
    """Main help lists the utterances command."""
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "utterances" in result.output


def test_utterances_help(runner):
    """utterances --help shows expected options."""
    result = runner.invoke(main, ["utterances", "--help"])
    assert result.exit_code == 0
    assert "--tts" in result.output
    assert "-o" in result.output
    assert "proofreading" in result.output


def test_utterances_stdout(runner, tmp_path):
    """utterances prints formatted text to stdout."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    mock_modules = [
        UtteranceModule(
            module_path="01-intro/slides.md",
            slides=[
                UtteranceSlide(slide_index=1, text="Hello and welcome.", voice=None),
                UtteranceSlide(slide_index=2, text="[silent]", voice=None),
                UtteranceSlide(slide_index=3, text="Let's begin.", voice="alice"),
            ],
        ),
    ]

    with patch("slidesonnet.cli.run_export_utterances", return_value=mock_modules) as mock_export:
        result = runner.invoke(main, ["utterances", str(playlist)])
        assert result.exit_code == 0
        mock_export.assert_called_once_with(playlist, tts_override=None)
        assert "# 01-intro/slides.md" in result.output
        assert "[1] Hello and welcome." in result.output
        assert "[2] [silent]" in result.output
        assert "[3] (voice: alice) Let's begin." in result.output


def test_utterances_output_file(runner, tmp_path):
    """utterances -o writes to file and prints path."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    out_file = tmp_path / "narration.txt"

    mock_modules = [
        UtteranceModule(
            module_path="slides.md",
            slides=[UtteranceSlide(slide_index=1, text="Hello.", voice=None)],
        ),
    ]

    with patch("slidesonnet.cli.run_export_utterances", return_value=mock_modules):
        result = runner.invoke(main, ["utterances", str(playlist), "-o", str(out_file)])
        assert result.exit_code == 0
        assert str(out_file) in result.output
        assert out_file.exists()
        content = out_file.read_text()
        assert "[1] Hello." in content


def test_utterances_with_tts_override(runner, tmp_path):
    """utterances --tts passes override."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_export_utterances", return_value=[]) as mock_export:
        result = runner.invoke(main, ["utterances", str(playlist), "--tts", "piper"])
        assert result.exit_code == 0
        mock_export.assert_called_once_with(playlist, tts_override="piper")


def test_utterances_multiple_modules(runner, tmp_path):
    """utterances separates modules with blank line + header."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    mock_modules = [
        UtteranceModule(
            module_path="01-intro/slides.md",
            slides=[UtteranceSlide(slide_index=1, text="First module.", voice=None)],
        ),
        UtteranceModule(
            module_path="02-defs/slides.tex",
            slides=[UtteranceSlide(slide_index=1, text="Second module.", voice=None)],
        ),
    ]

    with patch("slidesonnet.cli.run_export_utterances", return_value=mock_modules):
        result = runner.invoke(main, ["utterances", str(playlist)])
        assert result.exit_code == 0
        assert "# 01-intro/slides.md" in result.output
        assert "# 02-defs/slides.tex" in result.output
        assert "First module." in result.output
        assert "Second module." in result.output


# ---- Auto-discovery tests ----


def test_build_auto_discovers_slidesonnet_yaml(runner, tmp_path, monkeypatch):
    """build without PLAYLIST arg discovers slidesonnet.yaml in cwd."""
    monkeypatch.chdir(tmp_path)
    playlist = tmp_path / "slidesonnet.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "test.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["build"])
        assert result.exit_code == 0
        mock_build.assert_called_once()
        call_args = mock_build.call_args
        assert call_args[1]["output_override"] is None or call_args[0][0] == playlist


def test_build_auto_discovers_lecture_yaml_fallback(runner, tmp_path, monkeypatch):
    """build without PLAYLIST arg falls back to lecture.yaml."""
    monkeypatch.chdir(tmp_path)
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "test.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["build"])
        assert result.exit_code == 0


def test_build_auto_discovery_fails(runner, tmp_path, monkeypatch):
    """build without PLAYLIST arg in empty dir fails with helpful message."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(main, ["build"])
    assert result.exit_code != 0
    assert "No playlist file found" in result.output


def test_build_slidesonnet_yaml_priority(runner, tmp_path, monkeypatch):
    """slidesonnet.yaml is preferred over lecture.yaml."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "slidesonnet.yaml").write_text(_MINIMAL_PLAYLIST)
    (tmp_path / "lecture.yaml").write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "test.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["build"])
        assert result.exit_code == 0
        call_playlist = mock_build.call_args[0][0]
        assert call_playlist.name == "slidesonnet.yaml"


# ---- --output flag tests ----


def test_build_output_flag(runner, tmp_path):
    """--output / -o passes output_override to run_build."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "custom.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["build", str(playlist), "-o", str(out)])
        assert result.exit_code == 0
        mock_build.assert_called_once()
        assert mock_build.call_args[1]["output_override"] == out


# ---- --quiet flag tests ----


def test_build_quiet_suppresses_result(runner, tmp_path):
    """-q build produces no stdout."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["-q", "build", str(playlist)])
        assert result.exit_code == 0
        assert result.output == ""


def test_build_quiet_passes_to_pipeline(runner, tmp_path):
    """-q passes quiet=True to run_build."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=1.0)
        result = runner.invoke(main, ["-q", "build", str(playlist)])
        assert result.exit_code == 0
        mock_build.assert_called_once()
        assert mock_build.call_args[1]["quiet"] is True


def test_init_quiet_suppresses_output(runner, tmp_path):
    """-q init produces no stdout but still creates project."""
    target = tmp_path / "newproject"
    result = runner.invoke(main, ["-q", "init", "md", str(target)])
    assert result.exit_code == 0
    assert result.output == ""
    assert (target / "slidesonnet.yaml").exists()


def test_clean_quiet_suppresses_output(runner, tmp_path):
    """-q clean with results produces no stdout."""
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()
    (build_dir / ".doit.db").touch()

    with patch("slidesonnet.cli.run_clean", return_value=CleanResult(5, 1024, 2)):
        result = runner.invoke(main, ["-q", "clean", str(playlist)])
        assert result.exit_code == 0
        assert result.output == ""


def test_clean_quiet_no_cache(runner, tmp_path):
    """-q clean with missing cache produces no stdout."""
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    result = runner.invoke(main, ["-q", "clean", str(playlist)])
    assert result.exit_code == 0
    assert result.output == ""


# ---- Suggest group tests ----


def test_suggest_close_command(runner):
    """Misspelled command suggests a close match."""
    result = runner.invoke(main, ["buld"])
    assert result.exit_code != 0
    assert "Did you mean 'build'" in result.output


def test_suggest_no_match(runner):
    """Totally unrelated command shows generic error."""
    result = runner.invoke(main, ["xyzzy123"])
    assert result.exit_code != 0


# ---- Error path tests ----


def test_build_slidesonneterror(runner, tmp_path):
    """SlideSonnetError in build renders error and exits 1."""
    from slidesonnet.exceptions import SlideSonnetError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build", side_effect=SlideSonnetError("test error")):
        result = runner.invoke(main, ["build", str(playlist)])
        assert result.exit_code == 1


def test_build_parser_error_shows_doctor_hint(runner, tmp_path):
    """ParserError shows the doctor hint."""
    from slidesonnet.exceptions import ParserError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build", side_effect=ParserError("parse failed")):
        result = runner.invoke(main, ["build", str(playlist)])
        assert result.exit_code == 1


def test_build_ffmpeg_error_shows_doctor_hint(runner, tmp_path):
    """FFmpegError shows the doctor hint."""
    from slidesonnet.exceptions import FFmpegError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build", side_effect=FFmpegError("ffmpeg died")):
        result = runner.invoke(main, ["build", str(playlist)])
        assert result.exit_code == 1


def test_build_tts_error_shows_doctor_hint(runner, tmp_path):
    """TTSError shows the doctor hint."""
    from slidesonnet.exceptions import TTSError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build", side_effect=TTSError("tts failed")):
        result = runner.invoke(main, ["build", str(playlist)])
        assert result.exit_code == 1


def test_preview_error_handling(runner, tmp_path):
    """preview command handles SlideSonnetError."""
    from slidesonnet.exceptions import SlideSonnetError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build", side_effect=SlideSonnetError("boom")):
        result = runner.invoke(main, ["preview", str(playlist)])
        assert result.exit_code == 1


def test_preview_ffmpeg_error_doctor_hint(runner, tmp_path):
    """preview with FFmpegError shows doctor hint."""
    from slidesonnet.exceptions import FFmpegError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build", side_effect=FFmpegError("ffmpeg died")):
        result = runner.invoke(main, ["preview", str(playlist)])
        assert result.exit_code == 1


def test_preview_nonexistent(runner):
    """preview with nonexistent file fails."""
    result = runner.invoke(main, ["preview", "nonexistent.yaml"])
    assert result.exit_code != 0


def test_preview_dry_run(runner, tmp_path):
    """preview --dry-run calls run_dry_run with piper override."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    mock_result = DryRunResult(
        total_narrated=2, cached=2, needs_tts=0, uncached_chars=0, tts_backend="piper"
    )

    with patch("slidesonnet.cli.run_dry_run", return_value=mock_result) as mock_dry:
        result = runner.invoke(main, ["preview", str(playlist), "--dry-run"])
        assert result.exit_code == 0
        mock_dry.assert_called_once_with(playlist, tts_override="piper")


def test_preview_slide_error(runner, tmp_path):
    """preview-slide handles SlideSonnetError."""
    from slidesonnet.exceptions import SlideSonnetError

    slides = tmp_path / "slides.md"
    slides.write_text("---\nmarp: true\n---\n\n# Hello\n\n<!-- say: Hi. -->\n")

    with patch("slidesonnet.cli.preview_single_slide", side_effect=SlideSonnetError("failed")):
        result = runner.invoke(main, ["preview-slide", str(slides), "1"])
        assert result.exit_code == 1


def test_subtitles_nonexistent(runner):
    """subtitles with nonexistent file fails."""
    result = runner.invoke(main, ["subtitles", "nonexistent.yaml"])
    assert result.exit_code != 0


def test_subtitles_slidesonneterror(runner, tmp_path):
    """subtitles handles SlideSonnetError."""
    from slidesonnet.exceptions import SlideSonnetError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_generate_srt", side_effect=SlideSonnetError("fail")):
        result = runner.invoke(main, ["subtitles", str(playlist)])
        assert result.exit_code == 1


def test_subtitles_generic_exception(runner, tmp_path):
    """subtitles handles generic exceptions."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_generate_srt", side_effect=RuntimeError("oops")):
        result = runner.invoke(main, ["subtitles", str(playlist)])
        assert result.exit_code == 1


def test_utterances_nonexistent(runner):
    """utterances with nonexistent file fails."""
    result = runner.invoke(main, ["utterances", "nonexistent.yaml"])
    assert result.exit_code != 0


def test_utterances_error(runner, tmp_path):
    """utterances handles SlideSonnetError."""
    from slidesonnet.exceptions import SlideSonnetError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_export_utterances", side_effect=SlideSonnetError("fail")):
        result = runner.invoke(main, ["utterances", str(playlist)])
        assert result.exit_code == 1


def test_pdf_nonexistent(runner):
    """pdf with nonexistent file fails."""
    result = runner.invoke(main, ["pdf", "nonexistent.yaml"])
    assert result.exit_code != 0


def test_pdf_error(runner, tmp_path):
    """pdf handles SlideSonnetError."""
    from slidesonnet.exceptions import SlideSonnetError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_export_pdfs", side_effect=SlideSonnetError("pdf fail")):
        result = runner.invoke(main, ["pdf", str(playlist)])
        assert result.exit_code == 1


def test_pdf_ffmpeg_error_doctor_hint(runner, tmp_path):
    """pdf with FFmpegError shows doctor hint."""
    from slidesonnet.exceptions import FFmpegError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_export_pdfs", side_effect=FFmpegError("ffmpeg fail")):
        result = runner.invoke(main, ["pdf", str(playlist)])
        assert result.exit_code == 1


def test_clean_nonexistent(runner):
    """clean with nonexistent file fails."""
    result = runner.invoke(main, ["clean", "nonexistent.yaml"])
    assert result.exit_code != 0


def test_clean_nothing_removed(runner, tmp_path):
    """clean with removed_files=0 shows 'Nothing to remove'."""
    playlist = tmp_path / "test.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)
    build_dir = tmp_path / "cache"
    build_dir.mkdir()
    (build_dir / ".doit.db").touch()

    with patch("slidesonnet.cli.run_clean", return_value=CleanResult(0, 0, 3)):
        result = runner.invoke(main, ["clean", str(playlist)])
        assert result.exit_code == 0
        assert "Nothing to remove" in result.output


# ---- Doctor tests ----


def test_doctor_all_ok(runner):
    """doctor exits 0 when all checks pass."""
    with (
        patch("slidesonnet.doctor.run_all_checks", return_value=[]),
        patch("slidesonnet.doctor.print_report", return_value=True),
    ):
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0


def test_doctor_failure(runner):
    """doctor exits 1 when checks fail."""
    with (
        patch("slidesonnet.doctor.run_all_checks", return_value=[]),
        patch("slidesonnet.doctor.print_report", return_value=False),
    ):
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 1


# ---- Build result display tests ----


def test_build_result_stage_complete(runner, tmp_path):
    """Build with --until shows stage completion message."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_build") as mock_build:
        out = tmp_path / "cache" / "lecture.mp4"
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=2.5, until="tts")
        result = runner.invoke(main, ["build", str(playlist), "--until", "tts"])
        assert result.exit_code == 0
        assert "Stage 'tts' complete" in result.output
        assert "2.5s" in result.output


def test_build_result_output_exists(runner, tmp_path):
    """Build result shows file size when output exists."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    out = tmp_path / "lecture.mp4"
    out.write_bytes(b"\x00" * (2 * 1024 * 1024))  # 2 MB

    with patch("slidesonnet.cli.run_build") as mock_build:
        mock_build.return_value = BuildResult(output_path=out, elapsed_seconds=5.0)
        result = runner.invoke(main, ["build", str(playlist)])
        assert result.exit_code == 0
        assert "Built lecture.mp4" in result.output
        assert "2.0 MB" in result.output


def test_build_dry_run_preview_warning(runner, tmp_path):
    """--dry-run --preview logs a warning about preview being ignored."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    mock_result = DryRunResult(
        total_narrated=1, cached=1, needs_tts=0, uncached_chars=0, tts_backend="piper"
    )

    with patch("slidesonnet.cli.run_dry_run", return_value=mock_result):
        result = runner.invoke(main, ["build", str(playlist), "--dry-run", "--preview"])
        assert result.exit_code == 0


# ---- list command edge cases ----


def test_list_error(runner, tmp_path):
    """list handles SlideSonnetError."""
    from slidesonnet.exceptions import SlideSonnetError

    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(_MINIMAL_PLAYLIST)

    with patch("slidesonnet.cli.run_list_slides", side_effect=SlideSonnetError("fail")):
        result = runner.invoke(main, ["list", str(playlist)])
        assert result.exit_code == 1


def test_list_nonexistent(runner):
    """list with nonexistent file fails."""
    result = runner.invoke(main, ["list", "nonexistent.yaml"])
    assert result.exit_code != 0


# ---- No subcommand test ----


def test_no_subcommand_prints_help(runner):
    """Invoking without subcommand prints help."""
    result = runner.invoke(main, [])
    assert result.exit_code == 0
    assert "slideSonnet" in result.output
    assert "build" in result.output


# ---- _truncate tests ----


def test_truncate_short():
    from slidesonnet.cli import _truncate

    assert _truncate("Hello", 10) == "Hello"


def test_truncate_long():
    from slidesonnet.cli import _truncate

    result = _truncate("Hello World and More", 10)
    assert len(result) == 10
    assert result.endswith("\u2026")


# ---- _CliFormatter tests ----


def test_cli_formatter_warning():
    from slidesonnet.cli import _CliFormatter

    fmt = _CliFormatter()
    import logging

    record = logging.LogRecord("test", logging.WARNING, "", 0, "Something went wrong", (), None)
    result = fmt.format(record)
    assert result.startswith("WARNING:")
    assert "Something went wrong" in result


def test_cli_formatter_info():
    from slidesonnet.cli import _CliFormatter

    fmt = _CliFormatter()
    import logging

    record = logging.LogRecord("test", logging.INFO, "", 0, "Just info", (), None)
    result = fmt.format(record)
    assert result == "Just info"


def test_cli_formatter_error():
    from slidesonnet.cli import _CliFormatter

    fmt = _CliFormatter()
    import logging

    record = logging.LogRecord("test", logging.ERROR, "", 0, "Bad stuff", (), None)
    result = fmt.format(record)
    assert result.startswith("ERROR:")
    assert "Bad stuff" in result


# ---- _configure_logging tests ----


def test_configure_logging_quiet():
    import logging

    from slidesonnet.cli import _configure_logging

    # Save state
    old_level = logging.root.level
    old_handlers = logging.root.handlers[:]
    try:
        logging.root.handlers.clear()
        _configure_logging(quiet=True)
        assert logging.root.level == logging.WARNING
    finally:
        logging.root.level = old_level
        logging.root.handlers[:] = old_handlers


def test_configure_logging_normal():
    import logging

    from slidesonnet.cli import _configure_logging

    old_level = logging.root.level
    old_handlers = logging.root.handlers[:]
    try:
        logging.root.handlers.clear()
        _configure_logging(quiet=False)
        assert logging.root.level == logging.INFO
    finally:
        logging.root.level = old_level
        logging.root.handlers[:] = old_handlers
