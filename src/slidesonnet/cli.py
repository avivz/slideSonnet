"""CLI entry point for slideSonnet."""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Literal, cast

import click

from slidesonnet import __version__
from slidesonnet.clean import KeepLevel
from slidesonnet.clean import clean as run_clean
from slidesonnet.exceptions import (
    APINotAllowedError,
    FFmpegError,
    ParserError,
    SlideSonnetError,
    TTSError,
)
from slidesonnet.init import init_project
from slidesonnet.pipeline import (
    BuildResult,
    DryRunResult,
    build as run_build,
    dry_run as run_dry_run,
    export_pdfs as run_export_pdfs,
    export_utterances as run_export_utterances,
    generate_srt_file as run_generate_srt,
    list_slides as run_list_slides,
)
from slidesonnet.preview import preview_single_slide

logger = logging.getLogger(__name__)

_DOCTOR_HINT = '(run "slidesonnet doctor" to check dependencies)'


class _CliFormatter(logging.Formatter):
    """Format WARNING/ERROR with level prefix, INFO without."""

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno >= logging.WARNING:
            return f"{record.levelname}: {record.getMessage()}"
        return record.getMessage()


def _configure_logging(quiet: bool = False) -> None:
    """Set up logging for CLI use."""
    if not logging.root.handlers:
        handler = logging.StreamHandler()  # stderr by default
        handler.setFormatter(_CliFormatter())
        logging.root.addHandler(handler)
    logging.root.setLevel(logging.WARNING if quiet else logging.INFO)


_AUTO_NAMES = ("slidesonnet.yaml", "lecture.yaml")


def _discover_playlist(playlist: Path | None) -> Path:
    """Return the playlist path, auto-discovering if not provided.

    Checks for ``slidesonnet.yaml`` then ``lecture.yaml`` in the current
    directory when *playlist* is None.
    """
    if playlist is not None:
        return playlist
    for name in _AUTO_NAMES:
        candidate = Path(name)
        if candidate.exists():
            return candidate
    raise click.UsageError(
        "No playlist file found. Create slidesonnet.yaml in the current directory,\n"
        "or pass the path explicitly: slidesonnet build <playlist.yaml>"
    )


def _print_build_result(result: BuildResult) -> None:
    """Print a single consolidated build completion line."""
    if result.until:
        click.echo(f"Stage '{result.until}' complete ({result.elapsed_seconds:.1f}s)")
    elif result.output_path.exists():
        size_mb = result.output_path.stat().st_size / (1024 * 1024)
        line = f"Built {result.output_path.name} ({size_mb:.1f} MB, {result.elapsed_seconds:.1f}s)"
        if result.srt_path and result.srt_path.exists():
            line += f" + {result.srt_path.name}"
        click.echo(line)


class _SuggestGroup(click.Group):
    """Click group that suggests close matches for misspelled subcommands."""

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as e:
            if args:
                cmd_name = args[0]
                matches = difflib.get_close_matches(
                    cmd_name, self.list_commands(ctx), n=1, cutoff=0.6
                )
                if matches:
                    raise click.UsageError(
                        f"No such command '{cmd_name}'. Did you mean '{matches[0]}'?"
                    ) from e
            raise


@click.group(cls=_SuggestGroup, invoke_without_command=True)
@click.version_option(version=__version__)
@click.option("--quiet", "-q", is_flag=True, help="Suppress progress output (errors still shown)")
@click.pass_context
def main(ctx: click.Context, quiet: bool) -> None:
    """slideSonnet — compile narrated lecture videos from slides.

    \b
    Takes a playlist file (.yaml) that lists slide modules (MARP .md,
    Beamer .tex, or video files) and builds an MP4 with synthesized
    narration from slide annotations.

    \b
    Commands:
      build      [PLAYLIST] [--tts ...] [--preview] [-n] [--until STAGE] [-o OUTPUT]
      preview    [PLAYLIST] [--until STAGE]     (= build --tts piper --preview)
      subtitles  [PLAYLIST] [-o OUTPUT]         (generate SRT from cache)
      pdf        [PLAYLIST]                     (export concatenated PDF)
      list       [PLAYLIST] [--tts ...]         (list slides with narration)
      utterances [PLAYLIST] [-o FILE] [--tts ...] (export narration text)
      preview-slide SLIDES N [-p PLAYLIST]      (play one slide's audio)
      init       md|tex [DIR]                   (scaffold a new project)
      clean      [PLAYLIST] [--keep nothing|api|current|exact]
      doctor                                    (check installed dependencies)

    \b
    PLAYLIST defaults to slidesonnet.yaml (or lecture.yaml) in the current
    directory if not specified.

    \b
    Quick start:
      slidesonnet init md my-lecture
      cd my-lecture && slidesonnet build --tts piper

    Run "slidesonnet COMMAND --help" for details on a specific command.
    """
    _configure_logging(quiet=quiet)
    ctx.ensure_object(dict)
    ctx.obj["quiet"] = quiet
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


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
@click.argument("playlist", required=False, default=None, type=click.Path(path_type=Path))
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
@click.option("--no-srt", is_flag=True, help="Skip SRT subtitle generation")
@click.option("--allow-api", is_flag=True, help="Allow paid API calls (e.g. ElevenLabs TTS)")
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Output video path")
@click.pass_context
def build(
    ctx: click.Context,
    playlist: Path | None,
    tts: str | None,
    dry_run: bool,
    preview: bool,
    until: str | None,
    no_srt: bool,
    allow_api: bool,
    output: Path | None,
) -> None:
    """Build an MP4 video from a playlist file.

    \b
    PLAYLIST is a YAML file that lists slide modules and configures
    TTS, voice, and video settings. Defaults to slidesonnet.yaml (or
    lecture.yaml) in the current directory if not specified. An SRT
    subtitle file is generated alongside the video (use --no-srt to skip).

    \b
    When the playlist uses a paid TTS backend (e.g. ElevenLabs), the build
    will fail with a report if uncached slides would require API calls.
    Pass --allow-api to proceed, or use --tts piper for free local TTS.

    \b
    Examples:
      slidesonnet build
      slidesonnet build --tts piper --preview
      slidesonnet build --allow-api             # allow paid TTS
      slidesonnet build -n                      # dry-run
      slidesonnet build --until tts             # stop after audio
      slidesonnet build -o my-lecture.mp4        # custom output name
    """
    playlist = _discover_playlist(playlist)
    if not playlist.exists():
        raise click.BadParameter(f"Path '{playlist}' does not exist.", param_hint="'PLAYLIST'")
    quiet: bool = ctx.obj.get("quiet", False)
    # Explicit --tts elevenlabs implies opt-in to paid API calls
    effective_allow_api = allow_api or tts == "elevenlabs"
    try:
        if dry_run:
            if preview:
                logger.warning("--preview has no effect with --dry-run")
            result = run_dry_run(
                playlist,
                tts_override=cast(Literal["piper", "elevenlabs"] | None, tts),
            )
            _print_dry_run(result)
        else:
            build_result = run_build(
                playlist,
                tts_override=cast(Literal["piper", "elevenlabs"] | None, tts),
                preview=preview,
                until=until,
                quiet=quiet,
                no_srt=no_srt,
                allow_api=effective_allow_api,
                output_override=output,
            )
            if not quiet:
                _print_build_result(build_result)
    except APINotAllowedError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    except SlideSonnetError as e:
        logger.error("%s", e)
        if isinstance(e, (ParserError, FFmpegError, TTSError)):
            logger.error("%s", _DOCTOR_HINT)
        raise SystemExit(1)


@main.command()
@click.argument("playlist", required=False, default=None, type=click.Path(path_type=Path))
@click.option("--dry-run", "-n", is_flag=True, help="Report cache status without building anything")
@click.option(
    "--until",
    type=click.Choice(["slides", "tts", "segments"]),
    help="Run pipeline only up to STAGE (slides, tts, or segments)",
)
@click.option("--no-srt", is_flag=True, help="Skip SRT subtitle generation")
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Output video path")
@click.pass_context
def preview(
    ctx: click.Context,
    playlist: Path | None,
    dry_run: bool,
    until: str | None,
    no_srt: bool,
    output: Path | None,
) -> None:
    """Build a preview video using local Piper TTS (free, no API key).

    Shorthand for: slidesonnet build --tts piper --preview
    """
    playlist = _discover_playlist(playlist)
    if not playlist.exists():
        raise click.BadParameter(f"Path '{playlist}' does not exist.", param_hint="'PLAYLIST'")
    quiet: bool = ctx.obj.get("quiet", False)
    try:
        if dry_run:
            result = run_dry_run(playlist, tts_override="piper")
            _print_dry_run(result)
        else:
            build_result = run_build(
                playlist,
                tts_override="piper",
                preview=True,
                until=until,
                quiet=quiet,
                no_srt=no_srt,
                output_override=output,
            )
            if not quiet:
                _print_build_result(build_result)
    except SlideSonnetError as e:
        logger.error("%s", e)
        if isinstance(e, (ParserError, FFmpegError, TTSError)):
            logger.error("%s", _DOCTOR_HINT)
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
        if isinstance(e, (ParserError, FFmpegError, TTSError)):
            logger.error("%s", _DOCTOR_HINT)
        raise SystemExit(1)


@main.command()
@click.argument("playlist", required=False, default=None, type=click.Path(path_type=Path))
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    help="Output SRT file path (default: alongside playlist as .srt)",
)
@click.option(
    "--tts",
    type=click.Choice(["piper", "elevenlabs"]),
    help="TTS backend (for locating cached audio files)",
)
def subtitles(playlist: Path | None, output: Path | None, tts: str | None) -> None:
    """Generate SRT subtitles from a previously built playlist.

    \b
    Reads cached audio durations and narration text to produce an SRT
    subtitle file. Requires a prior build (audio files must exist in cache).

    \b
    Examples:
      slidesonnet subtitles
      slidesonnet subtitles -o lecture_en.srt
    """
    playlist = _discover_playlist(playlist)
    if not playlist.exists():
        raise click.BadParameter(f"Path '{playlist}' does not exist.", param_hint="'PLAYLIST'")
    try:
        srt_path = run_generate_srt(
            playlist,
            tts_override=cast(Literal["piper", "elevenlabs"] | None, tts),
            output=output,
        )
        click.echo(str(srt_path))
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)
    except Exception as e:
        logger.error("SRT generation failed: %s", e)
        raise SystemExit(1)


@main.command()
@click.argument("playlist", required=False, default=None, type=click.Path(path_type=Path))
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    help="Output file path (default: print to stdout)",
)
@click.option(
    "--tts",
    type=click.Choice(["piper", "elevenlabs"]),
    help="TTS backend for pronunciation rules (default: from playlist config)",
)
def utterances(playlist: Path | None, output: Path | None, tts: str | None) -> None:
    """Export narration text for proofreading.

    \b
    Parses all slide modules and prints narration text (post-pronunciation)
    grouped by module. No build or TTS calls are made.

    \b
    Output format:
      # module-path/slides.md
      [1] Hello and welcome to this lecture.
      [2] [silent]
      [3] (voice: alice) Let's begin with the basics.

    \b
    Examples:
      slidesonnet utterances
      slidesonnet utterances -o narration.txt
      slidesonnet utterances --tts piper
    """
    playlist = _discover_playlist(playlist)
    if not playlist.exists():
        raise click.BadParameter(f"Path '{playlist}' does not exist.", param_hint="'PLAYLIST'")
    try:
        modules = run_export_utterances(
            playlist,
            tts_override=cast(Literal["piper", "elevenlabs"] | None, tts),
        )
        lines: list[str] = []
        for i, mod in enumerate(modules):
            if i > 0:
                lines.append("")
            lines.append(f"# {mod.module_path}")
            lines.append("")
            for slide in mod.slides:
                prefix = f"[{slide.slide_index}]"
                if slide.text == "[silent]":
                    lines.append(f"{prefix} [silent]")
                else:
                    voice_prefix = f"(voice: {slide.voice}) " if slide.voice else ""
                    lines.append(f"{prefix} {voice_prefix}{slide.text}")
        text = "\n".join(lines) + "\n"
        if output:
            output.write_text(text, encoding="utf-8")
            click.echo(str(output))
        else:
            click.echo(text, nl=False)
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command()
@click.argument("fmt", type=click.Choice(["md", "tex"]))
@click.argument("target", type=click.Path(path_type=Path), default=".")
@click.pass_context
def init(ctx: click.Context, fmt: str, target: Path) -> None:
    """Create a new slideSonnet project.

    \b
    FMT selects the slide format: md (MARP Markdown) or tex (Beamer LaTeX).
    TARGET is the directory to create (default: current dir).

    \b
    Creates:
      slidesonnet.yaml, .gitignore, .env,
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
        if not ctx.obj.get("quiet", False):
            click.echo(f"Project created at {target}")
            if str(target) != ".":
                click.echo(f"\n  cd {target}")
            click.echo("  slidesonnet preview")
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command()
@click.argument("playlist", required=False, default=None, type=click.Path(path_type=Path))
@click.option(
    "--keep",
    type=click.Choice(["nothing", "api", "current", "exact"]),
    default="api",
    show_default=True,
    help="What to preserve",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.pass_context
def clean(ctx: click.Context, playlist: Path | None, keep: str, yes: bool) -> None:
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
      slidesonnet clean                              # keep API audio
      slidesonnet clean --keep current               # keep matching audio
      slidesonnet clean --keep nothing -y            # nuke everything
    """
    playlist = _discover_playlist(playlist)
    if not playlist.exists():
        raise click.BadParameter(f"Path '{playlist}' does not exist.", param_hint="'PLAYLIST'")
    quiet: bool = ctx.obj.get("quiet", False)
    build_dir = playlist.resolve().parent / "cache"
    if not build_dir.exists():
        if not quiet:
            click.echo("Nothing to clean.")
        return

    if keep == "nothing" and not yes:
        click.confirm(
            "This will delete all cached audio including API-generated files. Continue?",
            default=False,
            abort=True,
        )

    result = run_clean(playlist, keep=cast(KeepLevel, keep))
    if not quiet:
        if result.removed_files == 0:
            click.echo("Nothing to remove.")
        elif keep == "nothing":
            click.echo(f"Removed {result.removed_files} files ({result.removed_mb:.1f} MB)")
        else:
            parts = [f"removed {result.removed_files} files ({result.removed_mb:.1f} MB)"]
            if result.kept_files > 0:
                parts.append(f"kept {result.kept_files} files")
            click.echo(f"Cleaned cache: {', '.join(parts)}")


@main.command()
@click.argument("playlist", required=False, default=None, type=click.Path(path_type=Path))
def pdf(playlist: Path | None) -> None:
    """Export a concatenated PDF for all slide modules in a playlist.

    \b
    Compiles Beamer sources and runs marp --pdf for MARP modules,
    then concatenates into a single output PDF.

    \b
    Examples:
      slidesonnet pdf
    """
    playlist = _discover_playlist(playlist)
    if not playlist.exists():
        raise click.BadParameter(f"Path '{playlist}' does not exist.", param_hint="'PLAYLIST'")
    try:
        pdf_path = run_export_pdfs(playlist)
        click.echo(str(pdf_path))
    except SlideSonnetError as e:
        logger.error("%s", e)
        if isinstance(e, (ParserError, FFmpegError)):
            logger.error("%s", _DOCTOR_HINT)
        raise SystemExit(1)


def _truncate(text: str, width: int) -> str:
    """Truncate *text* to *width* characters, adding ellipsis if needed."""
    if len(text) <= width:
        return text
    return text[: width - 1] + "\u2026"


@main.command("list")
@click.argument("playlist", required=False, default=None, type=click.Path(path_type=Path))
@click.option(
    "--tts",
    type=click.Choice(["piper", "elevenlabs"]),
    help="TTS backend for pronunciation rules (default: from playlist config)",
)
def list_cmd(playlist: Path | None, tts: str | None) -> None:
    """List slides with voice and narration text.

    \b
    Parses a playlist's slide modules and prints a table showing each
    slide's number, source file, voice preset, and narration.
    Useful for discovering slide numbers before using preview-slide.

    \b
    Examples:
      slidesonnet list
      slidesonnet list --tts piper
    """
    playlist = _discover_playlist(playlist)
    if not playlist.exists():
        raise click.BadParameter(f"Path '{playlist}' does not exist.", param_hint="'PLAYLIST'")
    try:
        list_result = run_list_slides(
            playlist,
            tts_override=cast(Literal["piper", "elevenlabs"] | None, tts),
        )
        results = list_result.slides
        if not results:
            click.echo("No slides found.")
            return

        # Compute column widths
        narrated = [r for r in results if r.cached is not None]
        max_idx = max(len(str(r.slide_index)) for r in results)
        max_file = max(len(r.module_path) for r in results)
        max_voice = max(len(r.voice) for r in results)
        max_chars = max(len(str(r.chars)) for r in narrated) if narrated else 0
        w_idx = max(max_idx, 1)
        w_file = max(max_file, 4)
        w_voice = max(max_voice, 5)
        w_chars = max(max_chars, 5)  # "Chars" header

        header = (
            f"{'#':<{w_idx}}   {'File':<{w_file}}   {'Voice':<{w_voice}}"
            f"   {'Chars':>{w_chars}}   Narration"
        )
        click.echo(header)
        for r in results:
            if r.cached is not None:
                symbol = "\u25cf " if r.cached else "\u25cb "
                chars_str = str(r.chars)
            else:
                symbol = ""
                chars_str = "\u2013"
            narration = _truncate(r.text, 60)
            click.echo(
                f"{r.slide_index:<{w_idx}}   {r.module_path:<{w_file}}   {r.voice:<{w_voice}}"
                f"   {chars_str:>{w_chars}}   {symbol}{narration}"
            )

        # Summary line (only when narrated slides exist)
        if narrated:
            n_cached = sum(1 for r in narrated if r.cached is True)
            n_needs_tts = sum(1 for r in narrated if r.cached is False)
            total_slides = len(results)
            parts = [f"{total_slides} slides", f"{n_cached} cached"]
            if n_needs_tts > 0:
                uncached_chars = sum(r.chars for r in results if r.cached is False)
                verb = "needs" if n_needs_tts == 1 else "need"
                parts.append(
                    f"{n_needs_tts} {verb} TTS"
                    f" (~{uncached_chars:,} characters via {list_result.tts_backend})"
                )
            click.echo("\n" + ", ".join(parts))
            click.echo("\u25cf cached  \u25cb needs TTS")
    except SlideSonnetError as e:
        logger.error("%s", e)
        raise SystemExit(1)


@main.command()
def doctor() -> None:
    """Check that required tools and dependencies are installed.

    \b
    Checks: ffmpeg, ffprobe, marp-cli, pdflatex, pdftoppm, pdfunite, piper, elevenlabs.
    Run this if builds fail with "command not found" or tool errors.

    \b
    Examples:
      slidesonnet doctor
    """
    from slidesonnet.doctor import print_report, run_all_checks

    all_ok = print_report(run_all_checks())
    if not all_ok:
        raise SystemExit(1)
