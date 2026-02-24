"""CLI entry point for slideSonnet."""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from slidesonnet import __version__
from slidesonnet.init import init_blank, init_example, init_from
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
@click.argument("target", type=click.Path(path_type=Path), default=".")
@click.option("--blank", "mode", flag_value="blank", help="Create minimal scaffold")
@click.option("--example", "mode", flag_value="example", help="Create full working demo")
@click.option("--from", "from_path", type=click.Path(exists=True, path_type=Path),
              help="Copy config from existing playlist")
def init(target: Path, mode: str | None, from_path: Path | None):
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
def clean(playlist: Path):
    """Remove all build artifacts."""
    build_dir = playlist.resolve().parent / ".build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        click.echo(f"Removed {build_dir}")
    else:
        click.echo("Nothing to clean.")
