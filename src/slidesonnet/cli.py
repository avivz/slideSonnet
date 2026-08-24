"""CLI entry point for the slideSonnet narration editor."""

from __future__ import annotations

import difflib
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import click

from slidesonnet import __version__
from slidesonnet.diagnostics import Diagnostic, count_by_severity, has_errors
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.logging_setup import (
    ENV_LEVEL,
    attach_deck_file_logging,
    configure_console_logging,
    resolve_console_level,
)
from slidesonnet.tts import BACKENDS

logger = logging.getLogger(__name__)

_SEVERITY_COLOR = {"error": "red", "warning": "yellow", "info": "cyan"}


def _attach_deck_logging(ctx: click.Context, pdf: Path) -> None:
    """Add the rotating run-log for *pdf*, honoring --log-file/--no-log-file and config.

    Console logging is already configured by the group; this layers a file handler
    so a ``logger.exception`` from any module (including the background job worker)
    lands on disk with its traceback.
    """
    attach_deck_file_logging(
        pdf, override=ctx.obj.get("log_file"), disabled=ctx.obj.get("no_log_file", False)
    )


def _split_edit_target(target: Path | None, root: Path | None) -> tuple[Path | None, Path]:
    """Resolve ``edit``'s TARGET into ``(deck to open, folder to scan)``.

    A folder means "browse this tree"; a file means "open this deck", and its
    own folder is the default library scope. ``--root`` always wins, so a deck
    can be opened while browsing a wider tree. No VCS lookup is involved: the
    scope is what you pointed at, nothing inferred.
    """
    if target is not None and target.is_dir():
        return None, (root or target).resolve()
    if target is not None:
        return target, (root or target.parent).resolve()
    return None, (root or Path.cwd()).resolve()


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
@click.option("--verbose", "-v", is_flag=True, help="Show debug-level detail in the console")
@click.option(
    "--log-file",
    type=click.Path(path_type=Path),
    default=None,
    help="Write the run log here (default: <deck>/.slidesonnet/slidesonnet.log)",
)
@click.option("--no-log-file", is_flag=True, help="Don't write a run-log file")
@click.pass_context
def main(
    ctx: click.Context, quiet: bool, verbose: bool, log_file: Path | None, no_log_file: bool
) -> None:
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
    try:
        level = resolve_console_level(quiet=quiet, verbose=verbose, env=os.environ.get(ENV_LEVEL))
    except ValueError as e:
        raise click.UsageError(str(e)) from e
    configure_console_logging(level)
    ctx.ensure_object(dict)
    ctx.obj["quiet"] = quiet
    ctx.obj["verbose"] = verbose
    ctx.obj["log_file"] = log_file
    ctx.obj["no_log_file"] = no_log_file
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@contextmanager
def _cli_errors() -> Iterator[None]:
    """Map domain failures to clean CLI errors (message, no traceback).

    One uniform catch set for every command: SlideSonnetError (the domain
    base), ValueError (api parameter validation), FileExistsError (init).
    """
    try:
        yield
    except (SlideSonnetError, ValueError, FileExistsError) as e:
        raise click.ClickException(str(e)) from e


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

    with _cli_errors():
        path = init_sidecar(pdf, sidecar_path=narration, merge=merge, force=force)
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

    with _cli_errors():
        diags = check_deck(pdf, sidecar_path=narration)
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
@click.pass_context
def tts(
    ctx: click.Context, pdf: Path, narration: Path | None, engine: str | None, ids: tuple[str, ...]
) -> None:
    """Synthesize narration into the content-addressed cache (cache-aware)."""
    from slidesonnet.api import synthesize_deck

    _attach_deck_logging(ctx, pdf)
    with _cli_errors():
        n = synthesize_deck(
            pdf,
            sidecar_path=narration,
            engine=engine,  # type: ignore[arg-type]
            only_ids=set(ids) or None,
            progress=_progress,
        )
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
@click.pass_context
def export(
    ctx: click.Context,
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

    _attach_deck_logging(ctx, pdf)
    with _cli_errors():
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
@click.pass_context
def subs(
    ctx: click.Context,
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

    _attach_deck_logging(ctx, pdf)
    with _cli_errors():
        path = write_subs(
            pdf,
            output,
            fmt=fmt,  # type: ignore[arg-type]
            sub_granularity=sub_granularity,
            timing=timing,
            wpm=wpm,
            sidecar_path=narration,
        )
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
@click.argument("target", required=False, type=click.Path(exists=True, path_type=Path))
@_NARRATION_OPT
@click.option(
    "--root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Folder to scan for decks (default: the folder given, else the current one)",
)
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
@click.pass_context
def edit(
    ctx: click.Context,
    target: Path | None,
    narration: Path | None,
    root: Path | None,
    host: str,
    port: int,
    no_browser: bool,
    browser: str | None,
    app_window: bool,
    dev: bool,
) -> None:
    """Launch the NiceGUI narration editor.

    TARGET is a deck PDF to open, or a folder of decks to browse. With neither,
    the current folder is scanned. The editor opens on a library of every deck
    it finds (a PDF with a matching .narration beside it), searching
    subfolders; switch decks from there, with Ctrl+K, or with Alt+left/right.

    \b
      slidesonnet edit                                  # decks under the current folder
      slidesonnet edit ~/courses/aicode                 # decks under a course folder
      slidesonnet edit deck.pdf                         # that deck, plus its neighbours
      slidesonnet edit deck.pdf --root ~/courses        # ...browsing a wider tree

    \b
    On WSL the editor opens in your Windows browser via `wslview` if installed
    (apt install wslu). Other ways to open it:
      slidesonnet edit deck.pdf --app                    # chromeless Edge/Chrome window
      slidesonnet edit deck.pdf --browser "cmd.exe /c start"
      slidesonnet edit deck.pdf --browser '/mnt/c/.../msedge.exe --app={url}'
    """
    pdf, scan_root = _split_edit_target(target, root)
    from slidesonnet.gui import app as gui_app
    from slidesonnet.gui.app import run_editor
    from slidesonnet.gui.launch import dev_invocation

    if dev:
        argv, extra_env = dev_invocation(
            pdf,
            root=scan_root,
            sidecar_path=narration,
            host=host,
            port=port,
            browser=browser,
            app_window=app_window,
            no_browser=no_browser,
        )
        # The reload server is a fresh process that never re-enters this group, so
        # carry the console level and log-file choice across the exec via env.
        env = {**os.environ, **extra_env}
        env[ENV_LEVEL] = logging.getLevelName(logging.root.level)
        if ctx.obj.get("no_log_file"):
            env["SLIDESONNET_DEV_NO_LOG_FILE"] = "1"
        elif ctx.obj.get("log_file") is not None:
            env["SLIDESONNET_DEV_LOG_FILE"] = str(Path(ctx.obj["log_file"]).resolve())
        os.execve(sys.executable, argv, env)

    if pdf is not None:
        _attach_deck_logging(ctx, pdf)
    gui_app.set_log_preferences(
        override=ctx.obj.get("log_file"), disabled=ctx.obj.get("no_log_file", False)
    )
    run_editor(
        pdf,
        sidecar_path=narration,
        root=scan_root,
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
