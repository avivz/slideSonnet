"""CLI entry point for the slideSonnet narration editor."""

from __future__ import annotations

import difflib
import logging
import os
import sys
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from slidesonnet import __version__
from slidesonnet.cache import AUDIO_DIR_ENV
from slidesonnet.cli_options import NARRATION_OPT
from slidesonnet.diagnostics import Diagnostic, count_by_severity, has_errors
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.logging_setup import (
    ENV_LEVEL,
    attach_deck_file_logging,
    configure_console_logging,
    resolve_console_level,
)
from slidesonnet.narration.format import SidecarError
from slidesonnet.progress import RunProgress
from slidesonnet.tts import BACKENDS

if TYPE_CHECKING:
    from slidesonnet.api import ApproveFn, SynthesisPlan

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

    def invoke(self, ctx: click.Context) -> Any:
        # The one error boundary: every subcommand (and the group's own setup,
        # e.g. logging and config) runs inside it.
        with _cli_errors():
            return super().invoke(ctx)


class _PdfPath(click.Path):
    """An existing deck PDF — with a plain message for LaTeX source or a non-PDF file."""

    def __init__(self) -> None:
        super().__init__(exists=True, dir_okay=False, path_type=Path)

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> Any:
        path = super().convert(value, param, ctx)
        p = Path(os.fsdecode(path))
        if p.suffix.lower() in {".tex", ".ltx", ".sty"}:
            self.fail(
                f"{p.name} is LaTeX source — pass the compiled PDF ({p.with_suffix('.pdf').name})",
                param,
                ctx,
            )
        try:
            with p.open("rb") as f:
                magic = f.read(5)
        except OSError as e:
            self.fail(f"can't read {p.name}: {e.strerror}", param, ctx)
        if magic != b"%PDF-":
            self.fail(f"{p.name} isn't a PDF file — pass the deck's compiled PDF", param, ctx)
        return path


_PDF_ARG = click.argument("pdf", type=_PdfPath())


def _apply_verbosity(ctx: click.Context) -> None:
    """Set the console log level from the ``-q``/``-v`` seen so far (kept on the root)."""
    obj = ctx.find_root().ensure_object(dict)
    try:
        level = resolve_console_level(
            quiet=obj.get("quiet", False),
            verbose=obj.get("verbose", False),
            env=os.environ.get(ENV_LEVEL),
        )
    except ValueError as e:
        raise click.UsageError(str(e)) from e
    configure_console_logging(level)


def _verbosity_flag(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    # Recorded on the root before anything can fail, so -v shows tracebacks.
    if value and param.name is not None:
        ctx.find_root().ensure_object(dict)[param.name] = True
        _apply_verbosity(ctx)


def _verbosity_options() -> list[click.Option]:
    """``-q``/``-v``: the same flags on the group and, via _add_verbosity_options,
    after any subcommand (``slidesonnet export deck.pdf -v``)."""
    return [
        click.Option(
            ["--quiet", "-q"],
            is_flag=True,
            expose_value=False,
            callback=_verbosity_flag,
            help="Suppress progress output (errors still shown)",
        ),
        click.Option(
            ["--verbose", "-v"],
            is_flag=True,
            expose_value=False,
            callback=_verbosity_flag,
            help="Show debug-level detail in the console",
        ),
    ]


def _add_verbosity_options(group: click.Group) -> None:
    """Give every command under *group* (nested groups included) the ``-q``/``-v`` flags."""
    for command in group.commands.values():
        command.params.extend(_verbosity_options())
        if isinstance(command, click.Group):
            _add_verbosity_options(command)


@click.group(cls=_SuggestGroup, invoke_without_command=True, params=_verbosity_options())
@click.version_option(version=__version__)
@click.option(
    "--log-file",
    type=click.Path(path_type=Path),
    default=None,
    help="Write the run log here (default: <deck>/.slidesonnet/slidesonnet.log)",
)
@click.option("--no-log-file", is_flag=True, help="Don't write a run-log file")
@click.option(
    "--audio-dir",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "Speech-clip pool: where synthesized audio is cached and looked up. Overrides "
        f"${AUDIO_DIR_ENV} and [cache] audio_dir in slidesonnet.toml for this run. "
        "Point every checkout of a course at one pool so worktrees share (and never "
        "re-buy) the same clips. Default: <deck dir>/.slidesonnet/audio/"
    ),
)
@click.pass_context
def main(
    ctx: click.Context,
    log_file: Path | None,
    no_log_file: bool,
    audio_dir: Path | None,
) -> None:
    """slideSonnet — write, preview, and render narration for a PDF deck.

    \b
    Workflow:
      1. Add \\usepackage{slidesonnet} + \\ssid{...} markers to your Beamer
         source (run "slidesonnet sty" to drop the macro file), compile to PDF.
      2. slidesonnet init deck.pdf      # scaffold a blank .narration sidecar
      3. Edit deck.narration (by hand, an LLM, or "slidesonnet edit deck.pdf").
      4. slidesonnet check deck.pdf     # catch id and voice problems early
      5. slidesonnet export deck.pdf -o deck.mp4 --draft   # writes deck.draft.mp4
      6. For the final video, compile a final build
         (latexmk -pdf -usepretex='\\def\\ssfinal{}' deck.tex), then export
         without --draft.
    """
    ctx.ensure_object(dict)
    _apply_verbosity(ctx)  # -q/-v given here were recorded while parsing
    ctx.obj["log_file"] = log_file
    ctx.obj["no_log_file"] = no_log_file
    ctx.obj["audio_dir_flag"] = audio_dir is not None
    if audio_dir is not None:
        # The env var is the one channel every resolver (api, GUI, clean) reads,
        # so the flag simply becomes it for the rest of this process.
        os.environ[AUDIO_DIR_ENV] = str(audio_dir.expanduser().resolve())
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@contextmanager
def _cli_errors() -> Iterator[None]:
    """Map expected failures to one-line CLI errors; ``-v`` adds the traceback.

    Expected means the user can fix it: a domain error (SlideSonnetError), a
    malformed sidecar (SidecarError), an existing file (init), a file-system
    problem (a missing folder, no permission), or a PDF PyMuPDF can't read.
    Anything else is a bug and keeps its traceback.
    """
    try:
        yield
    except (SlideSonnetError, SidecarError, FileExistsError) as e:
        _show_traceback()
        raise click.ClickException(str(e)) from e
    except BrokenPipeError:
        raise  # the reader went away (e.g. `| head`); nothing to tell them
    except OSError as e:
        _show_traceback()
        raise click.ClickException(_os_error_message(e)) from e
    except RuntimeError as e:
        if type(e).__name__ != "FileDataError":  # pymupdf's "not a readable PDF"
            raise
        _show_traceback()
        raise click.ClickException(
            f"can't read the PDF ({e}) — is it a complete, compiled PDF? Recompile it and retry"
        ) from e


def _show_traceback() -> None:
    ctx = click.get_current_context(silent=True)
    if ctx is not None and (ctx.find_root().obj or {}).get("verbose"):
        click.echo(traceback.format_exc(), err=True)


def _os_error_message(e: OSError) -> str:
    name = e.filename or ""
    if isinstance(e, FileNotFoundError):
        return f"{name}: no such file or folder — check the path (create the folder first)"
    if isinstance(e, PermissionError):
        return f"{name}: permission denied — choose a location you can write to"
    if isinstance(e, IsADirectoryError):
        return f"{name} is a folder — give a file name"
    return f"{name}: {e.strerror or e}" if name else str(e)


def _stdin_is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _paid_gate(yes: bool, seen: dict[str, SynthesisPlan] | None = None) -> ApproveFn:
    """The ``approve`` hook for synthesis: ask before spending paid API credits.

    Free engines and fully cached decks pass silently. With ``--yes`` paid work
    goes ahead; at a terminal the user is asked; otherwise (a script, CI) the
    run is refused rather than billed unasked.
    """

    def approve(plan: SynthesisPlan) -> bool:
        if seen is not None:
            seen["plan"] = plan
        if not plan.paid or not plan.uncached or yes:
            return True
        what = (
            f"{plan.uncached} new clip(s) with {plan.engine}, which spends paid API credits "
            "(clips already generated are reused for free)"
        )
        if not _stdin_is_tty():
            raise click.ClickException(
                f"This would generate {what}. Re-run with --yes to allow it, "
                "or use --engine kokoro (free, runs locally)."
            )
        return click.confirm(f"Generate {what}?", default=False, abort=True)

    return approve


def _check_timing(timing: str, wpm: float) -> None:
    from slidesonnet.timing import parse_timing

    try:
        parse_timing(timing, wpm=wpm)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="'--timing' / '--wpm'") from e


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
@_PDF_ARG
@NARRATION_OPT
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
        click.echo(
            f"Next: write the narration in {path.name} (or run 'slidesonnet edit {pdf.name}'), "
            f"then 'slidesonnet check {pdf.name}'."
        )


@main.command()
@_PDF_ARG
@NARRATION_OPT
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


_YES_OPT = click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Generate paid (Inworld) clips without asking first",
)


def _subtitle_format(output: Path, fmt: str | None) -> str:
    """The subtitle format: --format if given, else the output's extension, else srt."""
    ext = output.suffix.lower().lstrip(".")
    if fmt is None:
        return ext if ext in {"srt", "vtt"} else "srt"
    if ext in {"srt", "vtt"} and ext != fmt:
        raise click.UsageError(
            f"{output.name} ends in .{ext} but --format {fmt} was asked for — "
            f"drop --format, or name the file {output.with_suffix('.' + fmt).name}"
        )
    return fmt


_ENGINE_OPT = click.option(
    "--engine",
    type=click.Choice(sorted(BACKENDS)),
    help="TTS backend (default: config; kokoro = free/local)",
)


def _run_progress(phases: tuple[str, ...]) -> RunProgress:
    """Progress lines for a CLI run, logged at INFO so ``--quiet`` hides them."""
    return RunProgress(phases, emit=logger.info)


@main.command()
@_PDF_ARG
@NARRATION_OPT
@_ENGINE_OPT
@click.option("--id", "ids", multiple=True, help="Synthesize only these slide-ids (repeatable)")
@_YES_OPT
@click.pass_context
def tts(
    ctx: click.Context,
    pdf: Path,
    narration: Path | None,
    engine: str | None,
    ids: tuple[str, ...],
    yes: bool,
) -> None:
    """Synthesize narration into the content-addressed cache (cache-aware).

    With a paid engine (Inworld), asks before generating new clips; --yes skips
    the question (needed when no terminal is attached, e.g. in a script).
    """
    from slidesonnet.api import synthesize_deck

    _attach_deck_logging(ctx, pdf)
    seen: dict[str, SynthesisPlan] = {}
    with _cli_errors():
        n = synthesize_deck(
            pdf,
            sidecar_path=narration,
            engine=engine,  # type: ignore[arg-type]
            only_ids=set(ids) or None,
            progress=_run_progress(("tts",)),
            approve=_paid_gate(yes, seen),
        )
    plan = seen.get("plan")
    reused = f", {plan.total - n} reused" if plan is not None else ""
    click.echo(f"{n} generated{reused}.")


@main.command()
@_PDF_ARG
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Output video (.mp4); wins over --output-dir. Default: <deck>.mp4 (see below)",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output folder for the video when there is no -o (overrides [video] output_dir; "
    "default: beside the deck). Subtitles then stay beside the deck.",
)
@click.option(
    "--subtitles-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Folder for the subtitle files (overrides [video] subtitles_dir)",
)
@click.option(
    "--where",
    is_flag=True,
    help="Print where the video and subtitles would go, and stop (nothing is rendered)",
)
@NARRATION_OPT
@_ENGINE_OPT
@click.option("--silent", is_flag=True, help="No TTS: silent video, timing from the model")
@click.option("--timing", default="tts", show_default=True, help="tts | estimate | fixed:N")
@click.option("--wpm", default=150.0, show_default=True, help="Words/minute for --timing estimate")
@click.option(
    "--subtitles",
    type=click.Choice(["srt", "vtt", "both", "none"]),
    default="srt",
    show_default=True,
    help="Subtitle files to write",
)
@click.option(
    "--sub-granularity",
    type=click.Choice(["segment", "slide"]),
    default="segment",
    show_default=True,
    help="One cue per speech segment, or per slide",
)
@click.option(
    "--keep-scratch",
    is_flag=True,
    help=(
        "Keep the render intermediates (decoded page audio, assembled track, silent "
        "video) in .slidesonnet/render/ after a successful export, for debugging. What "
        "the next export reuses (page images, encoded slides and sound) is kept either "
        "way; cached speech clips are never touched."
    ),
)
@click.option(
    "--draft",
    is_flag=True,
    help=(
        "Export even though the deck isn't final (a plain build without page numbers, "
        "or review conversations still open). Writes <name>.draft.mp4."
    ),
)
@click.option(
    "--fast",
    is_flag=True,
    help=(
        "Quick look: 720p, plain cuts instead of transitions, encoded in one quick pass. "
        "Same audio and subtitles. Writes <name>.fast.mp4."
    ),
)
@_YES_OPT
@click.pass_context
def export(
    ctx: click.Context,
    pdf: Path,
    output: Path | None,
    output_dir: Path | None,
    subtitles_dir: Path | None,
    where: bool,
    narration: Path | None,
    engine: str | None,
    silent: bool,
    timing: str,
    wpm: float,
    subtitles: str,
    sub_granularity: str,
    keep_scratch: bool,
    draft: bool,
    fast: bool,
    yes: bool,
) -> None:
    """Render the narrated (or silent) video with optional subtitles.

    Refuses a deck that 'slidesonnet check' reports errors for, one with no
    narration yet, and a plain build; --draft exports it anyway as
    <name>.draft.mp4. With a paid engine (Inworld), asks before generating new
    clips; --yes skips the question.

    \b
    Where the files go (--where prints it without rendering):
      video      -o, else <deck>.mp4 in --output-dir, [video] output_dir,
                 or beside the deck
      subtitles  --subtitles-dir, [video] subtitles_dir, else beside the
                 video -- or beside the deck when the video went to an
                 output folder
    """
    from slidesonnet import api

    if output is not None and output.suffix.lower() != ".mp4":
        raise click.UsageError(
            f"{output.name}: only MP4 video can be exported — name the output with .mp4 "
            f"(e.g. -o {output.with_suffix('.mp4').name})"
        )
    if where:
        with _cli_errors():
            paths = api.export_paths(
                pdf,
                output,
                output_dir=output_dir,
                subtitles_dir=subtitles_dir,
                draft=draft,
                fast=fast,
                subtitles=subtitles,  # type: ignore[arg-type]
            )
        _echo_export_paths(paths.video, paths.subtitles)
        return
    _check_timing(timing, wpm)
    _attach_deck_logging(ctx, pdf)
    with _cli_errors():
        progress = _run_progress(api.export_phases(silent=silent, timing=timing, wpm=wpm))
        result = api.export(
            pdf,
            output,
            output_dir=output_dir,
            subtitles_dir=subtitles_dir,
            sidecar_path=narration,
            engine=engine,  # type: ignore[arg-type]
            silent=silent,
            timing=timing,
            wpm=wpm,
            subtitles=subtitles,  # type: ignore[arg-type]
            sub_granularity=sub_granularity,
            keep_scratch=True if keep_scratch else None,
            progress=progress,
            draft=draft,
            approve=_paid_gate(yes),
            fast=fast,
        )
    logger.info(progress.summary())
    kind = "silent " if result.silent else ""
    extras = f" + {', '.join(p.name for p in result.subtitles)}" if result.subtitles else ""
    click.echo(f"Built {result.video.name} ({kind}{result.duration:.1f}s){extras}")
    _echo_export_paths(result.video, result.subtitles)


def _echo_export_paths(video: Path, subtitles: list[Path]) -> None:
    click.echo(f"Video:     {video}")
    click.echo(f"Subtitles: {subtitles[0] if subtitles else 'none'}")
    for path in subtitles[1:]:
        click.echo(f"           {path}")


@main.command()
@_PDF_ARG
@click.option(
    "-o", "--output", required=True, type=click.Path(path_type=Path), help="Output subtitle file"
)
@NARRATION_OPT
@_ENGINE_OPT
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["srt", "vtt"]),
    default=None,
    help="Subtitle format (default: from the output's extension, else srt)",
)
@click.option(
    "--sub-granularity",
    type=click.Choice(["segment", "slide"]),
    default="segment",
    show_default=True,
)
@click.option("--timing", default="tts", show_default=True, help="tts | estimate | fixed:N")
@click.option("--wpm", default=150.0, show_default=True)
@click.option(
    "--allow-estimates",
    is_flag=True,
    help="Under --timing tts, guess times for lines with no generated audio "
    "(they won't match the video)",
)
@click.pass_context
def subs(
    ctx: click.Context,
    pdf: Path,
    output: Path,
    narration: Path | None,
    engine: str | None,
    fmt: str | None,
    sub_granularity: str,
    timing: str,
    wpm: float,
    allow_estimates: bool,
) -> None:
    """Write subtitles without rendering video, timed against the generated audio.

    Pass the same --engine the video was rendered with: each voice keeps its own
    audio cache, so subtitles asked of a different one have nothing to measure.
    Rendering with `export` already writes matching subtitles — prefer those over
    re-deriving them here.
    """
    from slidesonnet.api import write_subs

    fmt = _subtitle_format(output, fmt)
    _check_timing(timing, wpm)
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
            engine=engine,  # type: ignore[arg-type]
            allow_estimates=allow_estimates,
        )
    click.echo(str(path))


@main.command()
@_PDF_ARG
@click.option(
    "--keep",
    type=click.Choice(["nothing", "api", "current", "exact"]),
    default="api",
    show_default=True,
    help=(
        "Which of this deck's speech clips to keep. "
        "api: paid (Inworld) clips only, drop local ones. "
        "current: clips for text the deck still says, on any engine. "
        "exact: only clips the deck would use with its current engine settings. "
        "nothing: none. At every level, clips another deck in the same folder still "
        "says are kept, and paid clips go to .slidesonnet/audio/trash/, never deleted"
    ),
)
@click.option("--dry-run", is_flag=True, help="Show what would be removed; change nothing")
@click.option(
    "--yes", "-y", is_flag=True, help="Don't ask before trashing paid clips or --keep nothing"
)
@NARRATION_OPT
def clean(pdf: Path, keep: str, dry_run: bool, yes: bool, narration: Path | None) -> None:
    """Prune the deck's own audio/render cache (.slidesonnet/ beside the PDF).

    Render scratch and logs always go. What happens to cached speech clips
    depends on --keep. The clip folder is shared by every deck in the same
    folder, so a clip any of them still says is always kept. Paid clips are
    moved to .slidesonnet/audio/trash/ (move one back to restore it), and you
    are asked first unless --yes. When the deck's clips live in a shared pool
    (see "slidesonnet pool status"), the pool is never touched here —
    "slidesonnet pool prune" does that, with every deck that uses the pool in
    view. The review base (what you've already seen, for "slidesonnet review")
    is kept at every level.
    """
    from slidesonnet.cache import cache_root
    from slidesonnet.clean import apply_clean, plan_clean

    if not cache_root(pdf).exists():
        click.echo("Nothing to clean.")
        return
    with _cli_errors():
        plan = plan_clean(pdf, keep, sidecar_path=narration)  # type: ignore[arg-type]
    remove, paid = plan.remove, plan.paid_to_trash
    slow = len(plan.to_trash) - len(paid)
    if dry_run:
        click.echo(
            f"Would remove {len(remove)} files ({_mb(sum(f.stat().st_size for f in remove))})"
        )
        if plan.to_trash:
            click.echo(
                f"Would move {len(paid)} paid and {slow} slow-to-make clip(s) to {plan.trash_dir}:"
            )
            for f in plan.to_trash:
                click.echo(f"    {f.name}")
        if plan.prune is not None:
            click.echo(f"Would keep {len(plan.kept_paid)} paid clip(s)")
        _say_stray_renders(plan.stray_renders, "Would remove")
        click.echo("Dry run: nothing was changed.")
        _say_pool_left_alone(plan.pool)
        return
    if not yes and paid:
        click.confirm(
            f"Move {len(paid)} paid clip(s) to {plan.trash_dir}? (Regenerating them would "
            "cost API credits; move them back from the trash to restore.)",
            default=False,
            abort=True,
        )
    elif not yes and keep == "nothing":
        click.confirm("Remove every speech clip only this deck uses?", default=False, abort=True)
    with _cli_errors():
        result = apply_clean(plan)
    if result.removed_files == 0 and result.trashed_files == 0:
        msg = "Nothing to remove"
    else:
        msg = f"Removed {result.removed_files} files ({result.removed_mb:.1f} MB)"
    if plan.prune is not None:
        msg += f", kept {result.kept_paid} paid clip(s)"
        if result.kept_files > result.kept_paid:
            msg += f" and {result.kept_files - result.kept_paid} other(s)"
    click.echo(msg + ".")
    if result.trashed_files:
        click.echo(
            f"Moved {result.trashed_files} paid/slow clip(s) to {result.trash_dir} "
            "(move one back to restore it)."
        )
    _say_stray_renders(plan.stray_renders, "Removed")
    _say_pool_left_alone(result.pool)


def _say_stray_renders(strays: list[Path], verb: str) -> None:
    if strays:
        click.echo(
            f"{verb} the render scratch of {len(strays)} renamed or deleted deck(s) "
            f"(no PDF here by that name): {', '.join(d.name for d in strays)}."
        )


def _say_pool_left_alone(pool: Path | None) -> None:
    if pool is not None:
        click.echo(
            f"Speech clips live in the shared pool {pool}, which this command "
            "never touches. To prune orphaned clips across every deck that uses it: "
            "slidesonnet pool prune --root <course dir>"
        )


# ---- pool ----------------------------------------------------------------------


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def _course_decks(roots: tuple[Path, ...], verb: str) -> list[Path]:
    """Every deck under *roots* — or a refusal when a scan was cut short.

    Both callers act on what the decks *don't* use (prune deletes it, migrate
    drops local caches), so a deck the scan never reached would lose its audio.
    """
    from slidesonnet.server.library import discover_decks

    found: list[Path] = []
    for root in roots:
        scan = discover_decks(root)
        if scan.truncated:
            raise click.ClickException(
                f"the scan of {root} stopped at its limit of {scan.visited} folders, "
                f"at {scan.stopped_at} ({scan.unvisited} folder(s) not looked into); "
                f"refusing to {verb} with an incomplete list of decks. Pass a narrower "
                "--root (one per course part, repeatable) or name the decks directly"
            )
        found.extend(e.pdf_path for e in scan.decks)
    return found


@main.group()
def pool() -> None:
    """Inspect, fill, or prune a shared speech-clip pool.

    \b
    A pool is an audio directory several decks (or several checkouts of one
    course) share. Clips are content-addressed, so sharing is always safe;
    what needs care is deleting. "pool status" says which pool a deck uses
    and why; "pool migrate" moves old per-deck caches into it; "pool prune"
    keeps every clip *any* deck still uses and parks expensive orphans in
    <pool>/trash/ before anything is lost for good. Where a deck's pool is
    comes from, first match wins:
      1. --audio-dir DIR            (before the subcommand)
      2. $SLIDESONNET_AUDIO_DIR     (shell export, or a .env beside the deck)
      3. [cache] audio_dir          in slidesonnet.toml, relative to the toml
      4. <deck dir>/.slidesonnet/audio/
    """


@pool.command("status")
@click.argument("pdf", required=False, type=click.Path(exists=True, path_type=Path))
@click.pass_context
def pool_status_cmd(ctx: click.Context, pdf: Path | None) -> None:
    """Show which pool DECK.pdf uses, why, and what it holds.

    Prints the resolved directory, which setting chose it (--audio-dir, the env
    var, the toml, or the default), clip counts and sizes per engine, what sits
    in <pool>/trash/, and whether the deck still has clips in its old local
    cache waiting to be migrated. Without a deck, resolves as a deck in the
    current directory would.
    """
    from slidesonnet.cache import default_audio_dir, resolve_audio_dir
    from slidesonnet.clean import stray_render_dirs
    from slidesonnet.config import default_config_path, load_config
    from slidesonnet.pool import pool_status

    deck = pdf if pdf is not None else Path.cwd() / "deck.pdf"
    with _cli_errors():
        config = load_config(deck)
    res = resolve_audio_dir(deck, config)
    if ctx.obj.get("audio_dir_flag"):
        why = "--audio-dir"
    elif res.source == "env":
        why = f"${AUDIO_DIR_ENV}"
    elif res.source == "config":
        why = f"[cache] audio_dir in {default_config_path(deck)}"
    else:
        why = "the default (no pool configured)"
    click.echo(f"Pool:   {res.path}")
    click.echo(f"Chosen by: {why}")
    st = pool_status(res.path)
    if not st.exists:
        click.echo("Contents: (directory does not exist yet)")
    else:
        click.echo(f"Contents: {st.total_files} files, {_mb(st.total_bytes)}")
        for backend, (n, b) in sorted(st.by_backend.items()):
            click.echo(f"  {backend:<8} {n:>6} clips  {_mb(b):>10}")
        if st.unknown[0]:
            click.echo(f"  {'other':<8} {st.unknown[0]:>6} files  {_mb(st.unknown[1]):>10}")
        if st.trash[0]:
            click.echo(
                f"Trash:  {st.trash[0]} quarantined clips, {_mb(st.trash[1])} "
                "(slidesonnet pool prune --empty-trash to delete for good)"
            )
    if res.shared and default_audio_dir(deck).is_dir():
        n = sum(1 for f in default_audio_dir(deck).iterdir() if f.is_file())
        if n:
            click.echo(
                f"Note: {n} file(s) still sit in the deck's old local cache "
                f"{default_audio_dir(deck)}; they are copied into the pool the next time "
                "the deck is synthesized, and 'slidesonnet clean' removes the local copies."
            )
    strays = stray_render_dirs(deck)
    if strays:
        size = sum(f.stat().st_size for d in strays for f in d.rglob("*") if f.is_file())
        click.echo(
            f"Note: {len(strays)} render folder(s) in {strays[0].parent} belong to no PDF "
            f"here (renamed or deleted decks?): {', '.join(d.name for d in strays)}, "
            f"{_mb(size)}. Render scratch only, no audio; 'slidesonnet clean' on any deck "
            "in this folder removes them."
        )


@pool.command("migrate")
@click.argument("decks", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--root",
    "roots",
    multiple=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Folder to scan for decks (*.pdf with a sibling .narration); repeatable",
)
@click.option(
    "--apply",
    is_flag=True,
    help="Actually do it. Without this flag the command only prints what it would do",
)
def pool_migrate_cmd(decks: tuple[Path, ...], roots: tuple[Path, ...], apply: bool) -> None:
    """Move every deck's old local clip cache into its pool. Dry run unless --apply.

    \b
    For each deck under --root (or named directly) that resolves to a pool:
    clips still in <deck dir>/.slidesonnet/audio/ are copied into the pool
    (ones the pool already has are skipped), then the local directory is
    removed. Decks with no pool configured are listed and left alone. This is
    the same step "slidesonnet clean" performs for one deck; migrate does it
    for a whole course at once.
    """
    from slidesonnet.cache import default_audio_dir, paths_overlap, resolve_audio_dir
    from slidesonnet.clean import retire_legacy_audio
    from slidesonnet.config import load_config
    from slidesonnet.hashing import parse_audio_filename

    if not decks and not roots:
        raise click.UsageError("name the decks to migrate: --root <course dir> and/or DECK.pdf ...")
    found = [*decks, *_course_decks(roots, "migrate")]

    seen_local: set[Path] = set()  # decks in one folder share a local cache
    unpooled: list[Path] = []
    moved = skipped = 0
    with _cli_errors():
        for deck in sorted({p.resolve() for p in found}):
            res = resolve_audio_dir(deck, load_config(deck))
            if not res.shared:
                unpooled.append(deck)
                continue
            legacy = default_audio_dir(deck)
            if legacy in seen_local or not legacy.is_dir() or paths_overlap(legacy, res.path):
                continue
            seen_local.add(legacy)
            clips = [
                f
                for f in legacy.iterdir()
                if f.is_file() and parse_audio_filename(f.name) is not None
            ]
            new = [f for f in clips if not (res.path / f.name).exists()]
            size = sum(f.stat().st_size for f in new)
            click.echo(
                f"{legacy}: {len(new)} clip(s) to copy ({_mb(size)}), "
                f"{len(clips) - len(new)} already in pool -> {res.path}"
            )
            if apply:
                moved += retire_legacy_audio(deck, res.path)
                skipped += len(clips) - len(new)
    for deck in unpooled:
        click.echo(f"{deck}: no pool configured (set [cache] audio_dir or --audio-dir); left alone")
    if apply:
        click.echo(
            f"Copied {moved} clip(s) into the pool, skipped {skipped} it already had, "
            f"and removed {len(seen_local)} local cache folder(s)."
        )
    elif seen_local:
        click.echo("Dry run: nothing was changed. Re-run with --apply to do it.")
    else:
        click.echo("Nothing to migrate.")


@pool.command("prune")
@click.argument("decks", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--root",
    "roots",
    multiple=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Folder to scan for decks (*.pdf with a sibling .narration); repeatable",
)
@click.option(
    "--keep",
    type=click.Choice(["current", "exact", "api"]),
    default="current",
    show_default=True,
    help=(
        "What counts as still in use. current: any deck still says the line (any engine). "
        "exact: a deck would synthesize that exact clip under its present engine config. "
        "api: keep paid clips regardless of decks, drop local ones"
    ),
)
@click.option(
    "--apply",
    is_flag=True,
    help="Actually do it. Without this flag the command only prints what it would do",
)
@click.option(
    "--empty-trash",
    is_flag=True,
    help="Also delete the clips previously parked in <pool>/trash/ (with --apply)",
)
def pool_prune_cmd(
    decks: tuple[Path, ...], roots: tuple[Path, ...], keep: str, apply: bool, empty_trash: bool
) -> None:
    """Drop clips no deck uses any more. A dry run unless --apply is given.

    \b
    Every deck found under the --root folders (plus any DECKS named directly)
    is a root: a clip is kept if any of them still needs it. Orphans from paid
    or slow engines (Inworld, Qwen3) are moved to <pool>/trash/, never deleted
    outright — restore one by moving it back. Cheap Kokoro orphans are deleted.
    Decks are grouped by the pool they resolve to, so several pools (or plain
    per-directory caches) are each pruned against their own decks.
    """
    from slidesonnet.cache import resolve_audio_dir
    from slidesonnet.clean import sibling_decks
    from slidesonnet.config import load_config
    from slidesonnet.pool import (
        DeckRoot,
        apply_prune,
        load_index,
        plan_prune,
    )
    from slidesonnet.pool import (
        empty_trash as run_empty_trash,
    )

    if not decks and not roots:
        raise click.UsageError(
            "name the decks that use the pool: --root <course dir> (repeatable) and/or DECK.pdf ..."
        )
    found = [*decks, *_course_decks(roots, "prune")]
    if not found and keep != "api":
        raise click.ClickException("no decks found under the given roots; nothing to keep by")

    by_pool: dict[Path, list[Path]] = {}
    protect: dict[Path, list[DeckRoot]] = {}
    with _cli_errors():
        for deck in sorted({p.resolve() for p in found}):
            res = resolve_audio_dir(deck, load_config(deck))
            by_pool.setdefault(res.path, []).append(deck)
            if not res.shared:  # a folder's own clip dir: every deck in it is a root
                protect.setdefault(res.path, []).extend(sibling_decks(deck))

    for pool_dir, members in by_pool.items():
        extra = [r for r in dict.fromkeys(protect.get(pool_dir, [])) if r.pdf not in members]
        with _cli_errors():
            plan = plan_prune(pool_dir, members, keep=keep, protect=extra)  # type: ignore[arg-type]
        click.echo(f"Pool {pool_dir}  (used by {len(members)} deck(s))")
        kept_b = sum(f.stat().st_size for f in plan.kept)
        del_b = sum(f.stat().st_size for f in plan.delete)
        q_b = sum(f.stat().st_size for f in plan.quarantine)
        click.echo(f"  keep       {len(plan.kept):>6} clips  {_mb(kept_b):>10}")
        click.echo(
            f"  delete     {len(plan.delete):>6} clips  {_mb(del_b):>10}  (cheap local audio)"
        )
        click.echo(
            f"  quarantine {len(plan.quarantine):>6} clips  {_mb(q_b):>10}  (paid/slow → trash/)"
        )
        if plan.unknown:
            click.echo(f"  left alone {len(plan.unknown):>6} files (not clips)")
        if plan.quarantine:
            index = load_index(pool_dir)
            for f in plan.quarantine:
                e = index.get(f.name)
                desc = (
                    f'"{e.text}"  last used by {Path(e.decks[-1]).name}'
                    if e is not None and e.decks
                    else "(no index entry: text unknown)"
                )
                click.echo(f"    {f.name}  {desc}")
        if not apply:
            continue
        result = apply_prune(plan)
        click.echo(
            f"  Deleted {result.deleted_files} clips ({_mb(result.deleted_bytes)}); "
            f"quarantined {result.quarantined_files} ({_mb(result.quarantined_bytes)})"
            + (f" in {result.trash_dir}" if result.trash_dir else "")
        )
        if empty_trash:
            n, b = run_empty_trash(pool_dir)
            click.echo(f"  Emptied trash: {n} clips, {_mb(b)}")
    if not apply:
        click.echo("Dry run: nothing was changed. Re-run with --apply to do it.")


@main.command()
@click.argument("target", required=False, type=click.Path(exists=True, path_type=Path))
@NARRATION_OPT
@click.option(
    "--root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Folder to scan for decks (default: the folder given, else the current one)",
)
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Address to listen on. The default keeps the editor on this machine; anything "
    "else lets other machines reach it (0.0.0.0 = every interface, needs --allow-host).",
)
@click.option("--port", default=8080, show_default=True, type=int, help="Port to listen on")
@click.option(
    "--allow-host",
    "allow_hosts",
    multiple=True,
    metavar="NAME",
    help="Another address or host name the editor answers to, as other machines type it "
    "(e.g. 192.168.1.20 or studio.local). Repeatable.",
)
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
    allow_hosts: tuple[str, ...],
    no_browser: bool,
    browser: str | None,
    app_window: bool,
    dev: bool,
) -> None:
    """Launch the narration editor in your browser.

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
    from slidesonnet.server import run as server_run

    try:
        warning = server_run.check_bind(host, port, list(allow_hosts))
    except server_run.BindRefused as exc:
        raise click.UsageError(str(exc)) from exc
    if warning:
        click.echo(warning, err=True)
    if pdf is not None:
        _attach_deck_logging(ctx, pdf)
    server_run.set_log_preferences(
        override=ctx.obj.get("log_file"), disabled=ctx.obj.get("no_log_file", False)
    )
    if dev:
        server_run.run_dev(
            pdf,
            sidecar_path=narration,
            root=scan_root,
            host=host,
            port=port,
            open_browser=not no_browser,
            browser=browser,
            app_window=app_window,
            allow_hosts=list(allow_hosts),
        )
        return
    server_run.run_editor(
        pdf,
        sidecar_path=narration,
        root=scan_root,
        host=host,
        port=port,
        open_browser=not no_browser,
        browser=browser,
        app_window=app_window,
        allow_hosts=list(allow_hosts),
    )


@main.command()
def doctor() -> None:
    """Check that required tools and dependencies are installed."""
    from slidesonnet.doctor import print_report, run_all_checks

    if not print_report(run_all_checks()):
        raise SystemExit(1)


def _register_review() -> None:
    from slidesonnet.review.cli import review

    main.add_command(review)


_register_review()
_add_verbosity_options(main)
