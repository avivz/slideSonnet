"""CLI entry point for the slideSonnet narration editor."""

from __future__ import annotations

import difflib
import logging
from pathlib import Path

import click

from slidesonnet import __version__
from slidesonnet.diagnostics import Diagnostic, count_by_severity, has_errors
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
                matches = difflib.get_close_matches(args[0], self.list_commands(ctx), n=1, cutoff=0.6)
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
    use_color = True
    for d in diags:
        label = d.severity.upper()
        if use_color:
            label = click.style(label, fg=_SEVERITY_COLOR.get(d.severity, "white"))
        click.echo(f"  {label}  {d.message}")
    counts = count_by_severity(diags)
    summary = f"{counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} info"
    click.echo(f"\n{summary}")


@main.command()
@click.option("-o", "--output", type=click.Path(path_type=Path), default=Path("slidesonnet.sty"),
              show_default=True, help="Where to write the macro (file or directory)")
def sty(output: Path) -> None:
    """Write the slidesonnet.sty LaTeX macro for your Beamer project."""
    from slidesonnet.api import write_sty

    written = write_sty(output)
    click.echo(str(written))


@main.command()
@click.argument("pdf", type=click.Path(exists=True, path_type=Path))
@click.option("--narration", type=click.Path(path_type=Path), help="Sidecar path (default: <deck>.narration)")
@click.option("--merge", is_flag=True, help="Append blocks for ids missing from an existing sidecar")
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
@click.option("--narration", type=click.Path(path_type=Path), help="Sidecar path (default: <deck>.narration)")
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


@main.command()
def doctor() -> None:
    """Check that required tools and dependencies are installed."""
    from slidesonnet.doctor import print_report, run_all_checks

    if not print_report(run_all_checks()):
        raise SystemExit(1)
