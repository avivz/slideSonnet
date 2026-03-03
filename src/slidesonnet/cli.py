"""CLI entry point for slideSonnet."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, cast

import click

from slidesonnet import __version__
from slidesonnet.clean import KeepLevel
from slidesonnet.clean import clean as run_clean
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.init import init_blank, init_example, init_from
from slidesonnet.pipeline import (
    DryRunResult,
    build as run_build,
    dry_run as run_dry_run,
    dump_utterances as run_dump_utterances,
    export_pdfs as run_export_pdfs,
)
from slidesonnet.preview import preview_single_slide

logger = logging.getLogger(__name__)


class _CliFormatter(logging.Formatter):
    """Format WARNING/ERROR with level prefix, INFO without."""

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno >= logging.WARNING:
            return f"{record.levelname}: {record.getMessage()}"
        return record.getMessage()


def _configure_logging() -> None:
    """Set up logging for CLI use."""
    if not logging.root.handlers:
        handler = logging.StreamHandler()  # stderr by default
        handler.setFormatter(_CliFormatter())
        logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """slideSonnet — compile narrated lecture videos from slides.

    \b
    Takes a playlist file (.md with YAML front matter) that lists slide
    modules (MARP .md, Beamer .tex, or video files) and builds an MP4
    with synthesized narration from slide annotations.

    \b
    Commands:
      build      PLAYLIST [--tts ...] [--preview] [-f] [-n] [--until STAGE]
      preview    PLAYLIST [--until STAGE]     (= build --tts piper --preview)
      pdf        PLAYLIST                     (export PDFs only)
      utterances PLAYLIST [--tts ...]         (print narration text)
      preview-slide SLIDES N [-p PLAYLIST]    (play one slide's audio)
      init       [DIR] [--blank|--example|--from PLAYLIST]
      clean      PLAYLIST [--keep nothing|api|current|exact]

    \b
    Quick start:
      slidesonnet init --example my-lecture
      slidesonnet build my-lecture/lecture01.md --tts piper

    Run "slidesonnet COMMAND --help" for details on a specific command.
    """
    _configure_logging()


def _print_dry_run(result: DryRunResult) -> None:
    """Format and print a dry-run summary."""
    if result.total_narrated == 0:
        click.echo("No narrated slides")
        return
    if result.needs_tts == 0:
        click.echo(f"{result.total_narrated} narrated slides: all cached")
        return
    click.echo(
        f"{result.total_narrated} narrated slides: "
        f"{result.cached} cached, {result.needs_tts} need TTS "
        f"(~{result.uncached_chars:,} characters via {result.tts_backend})"
    )


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--tts",
    type=click.Choice(["piper", "elevenlabs"]),
    help="Override TTS engine (piper: local/free, elevenlabs: cloud/paid)",
)
@click.option("--force", "-f", is_flag=True, help="Force rebuild all stages, ignoring cache")
@click.option("--dry-run", "-n", is_flag=True, help="Report cache status without building anything")
@click.option("--preview", is_flag=True, help="Fast low-res build (360p, ultrafast encoding)")
@click.option(
    "--until",
    type=click.Choice(["slides", "tts", "segments"]),
    help="Run pipeline only up to STAGE (slides, tts, or segments)",
)
def build(
    playlist: Path,
    tts: str | None,
    force: bool,
    dry_run: bool,
    preview: bool,
    until: str | None,
) -> None:
    """Build an MP4 video from a playlist file.

    PLAYLIST is a Markdown file with YAML front matter that lists slide
    modules and configures TTS, voice, and video settings.
    """
    try:
        if dry_run:
            result = run_dry_run(
                playlist,
                tts_override=cast(Literal["piper", "elevenlabs"] | None, tts),
            )
            _print_dry_run(result)
        else:
            run_build(
                playlist,
                tts_override=cast(Literal["piper", "elevenlabs"] | None, tts),
                force=force,
                preview=preview,
                until=until,
            )
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--until",
    type=click.Choice(["slides", "tts", "segments"]),
    help="Run pipeline only up to STAGE (slides, tts, or segments)",
)
def preview(playlist: Path, until: str | None) -> None:
    """Build a preview video using local Piper TTS (free, no API key).

    Shorthand for: slidesonnet build PLAYLIST --tts piper --preview
    """
    try:
        run_build(playlist, tts_override="piper", preview=True, until=until)
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command("preview-slide")
@click.argument("slides", type=click.Path(exists=True, path_type=Path))
@click.argument("slide_number", type=int)
@click.option(
    "--playlist",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    help="Playlist file for config (pronunciation, voice settings)",
)
def preview_slide(slides: Path, slide_number: int, playlist: Path | None) -> None:
    """Synthesize and play one slide's narration via Piper TTS.

    \b
    SLIDES is a .md (MARP) or .tex (Beamer) slide file.
    SLIDE_NUMBER is the 1-based slide index.

    Useful for quick iteration on narration text without rebuilding
    the full video.
    """
    try:
        preview_single_slide(slides, slide_number, playlist_path=playlist)
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command()
@click.argument("target", type=click.Path(path_type=Path), default=".")
@click.option(
    "--blank",
    "mode",
    flag_value="blank",
    help="Playlist + one empty slide module + pronunciation dir (default)",
)
@click.option(
    "--example",
    "mode",
    flag_value="example",
    help="Two slide modules with sample narration, ready to build",
)
@click.option(
    "--from",
    "from_path",
    type=click.Path(exists=True, path_type=Path),
    help="Copy config and pronunciation from an existing playlist",
)
def init(target: Path, mode: str | None, from_path: Path | None) -> None:
    """Create a new slideSonnet project in TARGET (default: current dir).

    \b
    Generates a playlist file, starter slides, .gitignore, and .env.
    Use --example for a project you can build immediately.
    """
    if from_path:
        init_from(target, from_path)
        click.echo(f"Project created at {target} (copied config from {from_path})")
    elif mode == "example":
        init_example(target)
        click.echo(f"Example project created at {target}")
    else:
        init_blank(target)
        click.echo(f"Project created at {target}")


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--keep",
    type=click.Choice(["nothing", "api", "current", "exact"]),
    default="api",
    help="What to preserve [default: api]",
)
def clean(playlist: Path, keep: str) -> None:
    """Remove cached build artifacts for a playlist.

    \b
    Always removes slide images, video segments, and build state.
    The --keep flag controls which cached audio files are preserved:
      --keep exact       Audio matching current text + config (active backend only)
      --keep current     Audio for current slide text (all backends)
      --keep api         All cloud TTS audio, even orphaned (default)
      --keep nothing     Remove everything, including all audio
    """
    build_dir = playlist.resolve().parent / "cache"
    if not build_dir.exists():
        click.echo("Nothing to clean.")
        return

    run_clean(playlist, keep=cast(KeepLevel, keep))
    if keep == "nothing":
        click.echo(f"Removed {build_dir}")
    else:
        click.echo(f"Cleaned {build_dir} (kept {keep})")


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
def pdf(playlist: Path) -> None:
    """Export PDFs for all slide modules in a playlist.

    Compiles Beamer sources and runs marp --pdf for MARP modules.
    Skips video passthrough modules.
    """
    try:
        paths = run_export_pdfs(playlist)
        if not paths:
            click.echo("No slide modules to export.")
            return
        for p in paths:
            click.echo(str(p))
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--tts",
    type=click.Choice(["piper", "elevenlabs"]),
    help="TTS backend for pronunciation rules (default: from playlist config)",
)
def utterances(playlist: Path, tts: str | None) -> None:
    """Print all utterances (post-pronunciation) for a playlist.

    Parses slides and applies pronunciation substitutions for the
    selected TTS backend. Useful for reviewing what will be spoken.
    """
    try:
        results = run_dump_utterances(
            playlist,
            tts_override=cast(Literal["piper", "elevenlabs"] | None, tts),
        )
        if not results:
            click.echo("No narrated slides.")
            return
        for module_path, slide_idx, text in results:
            click.echo(f"[{module_path} slide {slide_idx}] {text}")
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)
