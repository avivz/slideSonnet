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
from slidesonnet.init import init_project
from slidesonnet.pipeline import (
    DryRunResult,
    build as run_build,
    dry_run as run_dry_run,
    export_pdfs as run_export_pdfs,
    list_slides as run_list_slides,
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
    Takes a playlist file (.yaml) that lists slide modules (MARP .md,
    Beamer .tex, or video files) and builds an MP4 with synthesized
    narration from slide annotations.

    \b
    Commands:
      build      PLAYLIST [--tts ...] [--preview] [-n] [--until STAGE]
      preview    PLAYLIST [--until STAGE]     (= build --tts piper --preview)
      pdf        PLAYLIST                     (export PDFs only)
      list       PLAYLIST [--tts ...]         (list slides with narration)
      preview-slide SLIDES N [-p PLAYLIST]    (play one slide's audio)
      init       md|tex [DIR]                 (scaffold a new project)
      clean      PLAYLIST [--keep nothing|api|current|exact]

    \b
    Quick start:
      slidesonnet init md my-lecture
      slidesonnet build my-lecture/lecture.yaml --tts piper

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
    dry_run: bool,
    preview: bool,
    until: str | None,
) -> None:
    """Build an MP4 video from a playlist file.

    \b
    PLAYLIST is a YAML file that lists slide modules and configures
    TTS, voice, and video settings.

    \b
    Examples:
      slidesonnet build lecture.yaml
      slidesonnet build lecture.yaml --tts piper --preview
      slidesonnet build lecture.yaml -n               # dry-run
      slidesonnet build lecture.yaml --until tts       # stop after audio
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
    SLIDE_NUMBER is the 1-based slide index (use "list" to find numbers).

    \b
    Useful for quick iteration on narration text without rebuilding
    the full video.

    \b
    Examples:
      slidesonnet preview-slide 01-intro/slides.md 3
      slidesonnet preview-slide slides.tex 1 -p lecture.yaml
    """
    try:
        preview_single_slide(slides, slide_number, playlist_path=playlist)
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command()
@click.argument("fmt", type=click.Choice(["md", "tex"]))
@click.argument("target", type=click.Path(path_type=Path), default=".")
def init(fmt: str, target: Path) -> None:
    """Create a new slideSonnet project.

    \b
    FMT selects the slide format: md (MARP Markdown) or tex (Beamer LaTeX).
    TARGET is the directory to create (default: current dir).

    \b
    Creates:
      lecture.yaml, .gitignore, .env,
      pronunciation/cs-terms.md,
      01-intro/slides.{md,tex},
      02-definitions/slides.{md,tex}

    \b
    Examples:
      slidesonnet init md my-lecture
      slidesonnet init tex my-lecture
      slidesonnet init md                     # current directory

    \b
    Refuses to overwrite — if TARGET already contains project files,
    remove them first or choose a different directory.
    """
    try:
        init_project(target, fmt=cast(Literal["md", "tex"], fmt))
        click.echo(f"Project created at {target}")
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--keep",
    type=click.Choice(["nothing", "api", "current", "exact"]),
    default="api",
    show_default=True,
    help="What to preserve",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
def clean(playlist: Path, keep: str, yes: bool) -> None:
    """Remove cached build artifacts for a playlist.

    \b
    Always removes slide images, video segments, and build state.
    The --keep flag controls which cached audio files are preserved:
      --keep exact       Audio matching current text + config (active backend only)
      --keep current     Audio for current slide text (all backends)
      --keep api         All cloud TTS audio, even orphaned (default)
      --keep nothing     Remove everything, including all audio

    \b
    Examples:
      slidesonnet clean lecture.yaml                    # keep API audio
      slidesonnet clean lecture.yaml --keep current     # keep matching audio
      slidesonnet clean lecture.yaml --keep nothing -y  # nuke everything
    """
    build_dir = playlist.resolve().parent / "cache"
    if not build_dir.exists():
        click.echo("Nothing to clean.")
        return

    if keep == "nothing" and not yes:
        click.confirm(
            "This will delete all cached audio including API-generated files. Continue?",
            default=False,
            abort=True,
        )

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


def _truncate(text: str, width: int) -> str:
    """Truncate *text* to *width* characters, adding ellipsis if needed."""
    if len(text) <= width:
        return text
    return text[: width - 1] + "\u2026"


@main.command("list")
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--tts",
    type=click.Choice(["piper", "elevenlabs"]),
    help="TTS backend for pronunciation rules (default: from playlist config)",
)
def list_cmd(playlist: Path, tts: str | None) -> None:
    """List slides with voice and narration text.

    \b
    Parses a playlist's slide modules and prints a table showing each
    slide's number, source file, voice preset, and narration.
    Useful for discovering slide numbers before using preview-slide.

    \b
    Examples:
      slidesonnet list lecture.yaml
      slidesonnet list lecture.yaml --tts piper
    """
    try:
        results = run_list_slides(
            playlist,
            tts_override=cast(Literal["piper", "elevenlabs"] | None, tts),
        )
        if not results:
            click.echo("No slides found.")
            return

        # Compute column widths
        max_idx = max(len(str(r[1])) for r in results)
        max_file = max(len(r[0]) for r in results)
        max_voice = max(len(r[2]) for r in results)
        w_idx = max(max_idx, 1)
        w_file = max(max_file, 4)
        w_voice = max(max_voice, 5)

        header = f"{'#':<{w_idx}}   {'File':<{w_file}}   {'Voice':<{w_voice}}   Narration"
        click.echo(header)
        for module_path, slide_idx, voice, text in results:
            narration = _truncate(text, 60)
            click.echo(
                f"{slide_idx:<{w_idx}}   {module_path:<{w_file}}   {voice:<{w_voice}}   {narration}"
            )
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)
