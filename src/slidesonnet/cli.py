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
from slidesonnet.pipeline import build as run_build
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
    """slideSonnet — compile text-based presentations into narrated videos."""
    _configure_logging()


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
@click.option("--tts", type=click.Choice(["piper", "elevenlabs"]), help="Override TTS backend")
@click.option("--force", "-f", is_flag=True, help="Force rebuild all stages")
@click.option(
    "--jobs",
    "-j",
    type=int,
    default=None,
    help="Parallel jobs (default: 3, capped at 2 for ElevenLabs)",
)
def build(playlist: Path, tts: str | None, force: bool, jobs: int | None) -> None:
    """Build a presentation video from a playlist file."""
    try:
        run_build(
            playlist,
            tts_override=cast(Literal["piper", "elevenlabs"] | None, tts),
            force=force,
            jobs=jobs,
        )
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--jobs",
    "-j",
    type=int,
    default=None,
    help="Parallel jobs (default: 3, capped at 2 for ElevenLabs)",
)
def preview(playlist: Path, jobs: int | None) -> None:
    """Quick preview build using local Piper TTS."""
    try:
        run_build(playlist, tts_override="piper", jobs=jobs)
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
    """Play a single slide's narration audio.

    Parse SLIDES file and synthesize audio for SLIDE_NUMBER using Piper TTS.
    Useful for quick iteration on narration text.
    """
    try:
        preview_single_slide(slides, slide_number, playlist_path=playlist)
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command()
@click.argument("target", type=click.Path(path_type=Path), default=".")
@click.option("--blank", "mode", flag_value="blank", help="Create minimal scaffold")
@click.option("--example", "mode", flag_value="example", help="Create full working demo")
@click.option(
    "--from",
    "from_path",
    type=click.Path(exists=True, path_type=Path),
    help="Copy config from existing playlist",
)
def init(target: Path, mode: str | None, from_path: Path | None) -> None:
    """Initialize a new slideSonnet project."""
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
    type=click.Choice(["nothing", "api", "utterances", "exact"]),
    default="api",
    help="What to preserve: nothing (nuke), api (default), utterances, or exact",
)
def clean(playlist: Path, keep: str) -> None:
    """Remove build artifacts with graduated preservation.

    \b
    --keep nothing     Nuke entire cache directory
    --keep api         Keep API-generated audio (default)
    --keep utterances  Keep audio for current utterances (any engine)
    --keep exact       Keep only audio matching current text + config
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
