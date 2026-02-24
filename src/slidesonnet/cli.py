"""CLI entry point for slideSonnet."""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from slidesonnet import __version__
from slidesonnet.pipeline import build as run_build


@click.group()
@click.version_option(version=__version__)
def main():
    """slideSonnet — compile text-based presentations into narrated videos."""
    pass


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
@click.option("--tts", type=click.Choice(["piper", "elevenlabs"]), help="Override TTS backend")
@click.option("--force", "-f", is_flag=True, help="Force rebuild all stages")
def build(playlist: Path, tts: str | None, force: bool):
    """Build a presentation video from a playlist file."""
    run_build(playlist, tts_override=tts, force=force)


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
def preview(playlist: Path):
    """Quick preview build using local Piper TTS."""
    run_build(playlist, tts_override="piper")


@main.command()
@click.argument("playlist", type=click.Path(exists=True, path_type=Path))
def clean(playlist: Path):
    """Remove all build artifacts."""
    build_dir = playlist.resolve().parent / ".build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        click.echo(f"Removed {build_dir}")
    else:
        click.echo("Nothing to clean.")
