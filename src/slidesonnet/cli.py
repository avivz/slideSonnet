"""CLI entry point for the slideSonnet narration editor."""

from __future__ import annotations

import difflib
import logging
import os
import sys
from pathlib import Path

import click

from slidesonnet import __version__
from slidesonnet.diagnostics import Diagnostic, count_by_severity, has_errors
from slidesonnet.tts import BACKENDS
from slidesonnet.exceptions import SlideSonnetError

logger = logging.getLogger(__name__)

_SEVERITY_COLOR = {"error": "red", "warning": "yellow", "info": "cyan"}


class _CliFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if record.levelno >= logging.WARNING:
            return f"{record.levelname}: {record.getMessage()}"
        return record.getMessage()


def _configure_logging(quiet: bool = False) -> None:
    if not logging.root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_CliFormatter())
        logging.root.addHandler(handler)
    logging.root.setLevel(logging.WARNING if quiet else logging.INFO)


class _SuggestGroup(click.Group):
    """Click group that suggests close matches for misspelled subcommands."""

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as e:
            if args:
                matches = difflib.get_close_matches(
                    args[0], self.list_commands(ctx), n=1, cutoff=0.6
                )
                if matches:
                    raise click.UsageError(
                        f"No such command '{args[0]}'. Did you mean '{matches[0]}'?"
                    ) from e
            raise


@click.group(cls=_SuggestGroup, invoke_without_command=True)
@click.version_option(version=__version__)
@click.option("--quiet", "-q", is_flag=True, help="Suppress progress output (errors still shown)")
@click.pass_context
def main(ctx: click.Context, quiet: bool) -> None:
    """slideSonnet — write, preview, and render narration for a PDF deck.

    \b
    Workflow:
      1. Add \\usepackage{slidesonnet} + \\ssid{...} markers to your Beamer
         source (run "slidesonnet sty" to drop the macro file), compile to PDF.
      2. slidesonnet init deck.pdf      # scaffold a blank .narration sidecar
      3. Edit deck.narration (by hand, an LLM, or "slidesonnet edit deck.pdf").
      4. slidesonnet export deck.pdf -o deck.mp4

    \b
    Commands:
      sty     [-o PATH]                    write the slidesonnet.sty LaTeX macro
      init    deck.pdf [--merge|--force]   scaffold a blank narration sidecar
      check   deck.pdf                     reconcile sidecar ids against the PDF
      tts     deck.pdf [--engine ...]      synthesize narration into the cache
      export  deck.pdf -o OUT.mp4          render the narrated (or silent) video
      subs    deck.pdf -o OUT.srt          write subtitles without rendering video
      edit    deck.pdf                     launch the NiceGUI editor
      clean   deck.pdf [--keep ...]        prune the audio/render cache
      doctor                               check installed dependencies
    """
    _configure_logging(quiet=quiet)
    ctx.ensure_object(dict)
    ctx.obj["quiet"] = quiet
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _print_diagnostics(diags: list[Diagnostic]) -> None:
    for d in diags:
        label = click.style(d.severity.upper(), fg=_SEVERITY_COLOR.get(d.severity, "white"))
        click.echo(f"  {label}  {d.message}")
    counts = count_by_severity(diags)
    summary = f"{counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} info"
    click.echo(f"\n{summary}")


@main.command()
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    default=Path("slidesonnet.sty"),
    show_default=True,
    help="Where to write the macro (file or directory)",
)
def sty(output: Path) -> None:
    """Write the slidesonnet.sty LaTeX macro for your Beamer project."""
    from slidesonnet.api import write_sty

    written = write_sty(output)
    click.echo(str(written))


@main.command()
@click.argument("pdf", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--narration", type=click.Path(path_type=Path), help="Sidecar path (default: <deck>.narration)"
)
@click.option(
    "--merge", is_flag=True, help="Append blocks for ids missing from an existing sidecar"
)
@click.option("--force", is_flag=True, help="Overwrite an existing sidecar")
@click.pass_context
def init(ctx: click.Context, pdf: Path, narration: Path | None, merge: bool, force: bool) -> None:
    """Scaffold a blank narration sidecar from a PDF's slide-ids."""
    from slidesonnet.api import init_sidecar

    try:
        path = init_sidecar(pdf, sidecar_path=narration, merge=merge, force=force)
    except FileExistsError as e:
        raise click.ClickException(str(e))
    except SlideSonnetError as e:
        raise click.ClickException(str(e))
    if not ctx.obj.get("quiet", False):
        click.echo(str(path))


@main.command()
@click.argument("pdf", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--narration", type=click.Path(path_type=Path), help="Sidecar path (default: <deck>.narration)"
)
def check(pdf: Path, narration: Path | None) -> None:
    """Reconcile the sidecar against the PDF; exit non-zero on errors."""
    from slidesonnet.api import check_deck

    try:
        diags = check_deck(pdf, sidecar_path=narration)
    except SlideSonnetError as e:
        raise click.ClickException(str(e))
    if not diags:
        click.echo("OK — no issues.")
        return
    _print_diagnostics(diags)
    if has_errors(diags):
        raise SystemExit(1)


_NARRATION_OPT = click.option(
    "--narration", type=click.Path(path_type=Path), help="Sidecar path (default: <deck>.narration)"
)
_ENGINE_OPT = click.option(
    "--engine",
    type=click.Choice(sorted(BACKENDS)),
    help="TTS backend (default: config; kokoro = free/local)",
)


def _progress(slide_id: str, done: int, total: int) -> None:
    logger.info("  [%d/%d] %s", done, total, slide_id)


@main.command()
@click.argument("pdf", type=click.Path(exists=True, path_type=Path))
@_NARRATION_OPT
@_ENGINE_OPT
@click.option("--id", "ids", multiple=True, help="Synthesize only these slide-ids (repeatable)")
def tts(pdf: Path, narration: Path | None, engine: str | None, ids: tuple[str, ...]) -> None:
    """Synthesize narration into the content-addressed cache (cache-aware)."""
    from slidesonnet.api import synthesize_deck

    try:
        n = synthesize_deck(
            pdf,
            sidecar_path=narration,
            engine=engine,  # type: ignore[arg-type]
            only_ids=set(ids) or None,
            progress=_progress,
        )
    except SlideSonnetError as e:
        raise click.ClickException(str(e))
    click.echo(f"Synthesized {n} new clip(s); rest from cache.")


@main.command()
@click.argument("pdf", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path), help="Output MP4")
@_NARRATION_OPT
@_ENGINE_OPT
@click.option("--silent", is_flag=True, help="No TTS: silent video, timing from the model")
@click.option("--timing", default="tts", show_default=True, help="tts | estimate | fixed:N")
@click.option("--wpm", default=150.0, show_default=True, help="Words/minute for --timing estimate")
@click.option(
    "--subtitles",
    type=click.Choice(["srt", "vtt", "both", "none"]),
    default="srt",
    show_default=True,
    help="Subtitle files beside the video",
)
@click.option(
    "--sub-granularity",
    type=click.Choice(["segment", "slide"]),
    default="segment",
    show_default=True,
    help="One cue per speech segment, or per slide",
)
def export(
    pdf: Path,
    output: Path,
    narration: Path | None,
    engine: str | None,
    silent: bool,
    timing: str,
    wpm: float,
    subtitles: str,
    sub_granularity: str,
) -> None:
    """Render the narrated (or silent) video with optional subtitles."""
    from slidesonnet.api import export as run_export

    try:
        result = run_export(
            pdf,
            output,
            sidecar_path=narration,
            engine=engine,  # type: ignore[arg-type]
            silent=silent,
            timing=timing,
            wpm=wpm,
            subtitles=subtitles,  # type: ignore[arg-type]
            sub_granularity=sub_granularity,
            progress=_progress,
        )
    except (SlideSonnetError, ValueError) as e:
        raise click.ClickException(str(e))
    kind = "silent " if result.silent else ""
    extras = f" + {', '.join(p.name for p in result.subtitles)}" if result.subtitles else ""
    click.echo(f"Built {output.name} ({kind}{result.duration:.1f}s){extras}")


@main.command()
@click.argument("pdf", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o", "--output", required=True, type=click.Path(path_type=Path), help="Output subtitle file"
)
@_NARRATION_OPT
@click.option(
    "--format", "fmt", type=click.Choice(["srt", "vtt"]), default="srt", show_default=True
)
@click.option(
    "--sub-granularity",
    type=click.Choice(["segment", "slide"]),
    default="segment",
    show_default=True,
)
@click.option("--timing", default="tts", show_default=True, help="tts | estimate | fixed:N")
@click.option("--wpm", default=150.0, show_default=True)
def subs(
    pdf: Path,
    output: Path,
    narration: Path | None,
    fmt: str,
    sub_granularity: str,
    timing: str,
    wpm: float,
) -> None:
    """Write subtitles without rendering video (cached audio durations, else timing model)."""
    from slidesonnet.api import write_subs

    try:
        path = write_subs(
            pdf,
            output,
            fmt=fmt,  # type: ignore[arg-type]
            sub_granularity=sub_granularity,
            timing=timing,
            wpm=wpm,
            sidecar_path=narration,
        )
    except (SlideSonnetError, ValueError) as e:
        raise click.ClickException(str(e))
    click.echo(str(path))


@main.command()
@click.argument("pdf", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--keep",
    type=click.Choice(["nothing", "api", "current", "exact"]),
    default="api",
    show_default=True,
    help="What cached audio to preserve",
)
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt for --keep nothing")
def clean(pdf: Path, keep: str, yes: bool) -> None:
    """Prune the deck's audio/render cache."""
    from slidesonnet.cache import cache_root
    from slidesonnet.clean import clean as run_clean

    if not cache_root(pdf).exists():
        click.echo("Nothing to clean.")
        return
    if keep == "nothing" and not yes:
        click.confirm(
            "Delete ALL cached audio (including paid API audio)?", default=False, abort=True
        )
    result = run_clean(pdf, keep=keep)  # type: ignore[arg-type]
    if result.removed_files == 0:
        click.echo("Nothing to remove.")
    else:
        msg = f"Removed {result.removed_files} files ({result.removed_mb:.1f} MB)"
        if result.kept_files:
            msg += f", kept {result.kept_files}"
        click.echo(msg)


@main.command()
@click.argument("pdf", type=click.Path(exists=True, path_type=Path))
@_NARRATION_OPT
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8080, show_default=True, type=int)
@click.option("--no-browser", is_flag=True, help="Do not auto-open a browser tab")
@click.option(
    "--browser",
    metavar="CMD",
    help="Command to open the URL (e.g. 'wslview', 'cmd.exe /c start', or a browser path; "
    "a '{url}' token is substituted). Also via SLIDESONNET_BROWSER. Under WSL, 'wslview' default.",
)
@click.option(
    "--app",
    "app_window",
    is_flag=True,
    help="Open a chromeless app window via Edge/Chrome (auto-detected; Windows-side under WSL). "
    "Firefox has no app-window mode.",
)
@click.option(
    "--dev",
    is_flag=True,
    help="Auto-restart the editor when slideSonnet's own source code changes "
    "(for hacking on slideSonnet itself).",
)
def edit(
    pdf: Path,
    narration: Path | None,
    host: str,
    port: int,
    no_browser: bool,
    browser: str | None,
    app_window: bool,
    dev: bool,
) -> None:
    """Launch the NiceGUI narration editor.

    \b
    On WSL the editor opens in your Windows browser via `wslview` if installed
    (apt install wslu). Other ways to open it:
      slidesonnet edit deck.pdf --app                    # chromeless Edge/Chrome window
      slidesonnet edit deck.pdf --browser "cmd.exe /c start"
      slidesonnet edit deck.pdf --browser '/mnt/c/.../msedge.exe --app={url}'
    """
    from slidesonnet.gui.app import dev_invocation, run_editor

    if dev:
        argv, extra_env = dev_invocation(
            pdf,
            sidecar_path=narration,
            host=host,
            port=port,
            browser=browser,
            app_window=app_window,
            no_browser=no_browser,
        )
        os.execve(sys.executable, argv, {**os.environ, **extra_env})

    run_editor(
        pdf,
        sidecar_path=narration,
        host=host,
        port=port,
        open_browser=not no_browser,
        browser=browser,
        app_window=app_window,
    )


@main.command()
def doctor() -> None:
    """Check that required tools and dependencies are installed."""
    from slidesonnet.doctor import print_report, run_all_checks

    if not print_report(run_all_checks()):
        raise SystemExit(1)
