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
from slidesonnet.cache import AUDIO_DIR_ENV
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
    quiet: bool,
    verbose: bool,
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
      4. slidesonnet export deck.pdf -o deck.mp4

    \b
    Commands:
      sty     [-o PATH]                    write the slidesonnet.sty LaTeX macro
      init    deck.pdf [--merge|--force]   scaffold a blank narration sidecar
      check   deck.pdf                     reconcile sidecar ids against the PDF
      tts     deck.pdf [--engine ...]      synthesize narration into the cache
      export  deck.pdf -o OUT.mp4          render the narrated (or silent) video
      subs    deck.pdf -o OUT.srt          subtitles alone (export already writes them)
      edit    deck.pdf                     launch the NiceGUI editor
      clean   deck.pdf [--keep ...]        prune the deck's own audio/render cache
      pool    status | migrate | prune     inspect / fill / prune a shared clip pool
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
    ctx.obj["audio_dir_flag"] = audio_dir is not None
    if audio_dir is not None:
        # The env var is the one channel every resolver (api, GUI, clean) reads,
        # so the flag simply becomes it for the rest of this process.
        os.environ[AUDIO_DIR_ENV] = str(audio_dir.expanduser().resolve())
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
@click.option(
    "--keep-scratch",
    is_flag=True,
    help=(
        "Keep the render intermediates (decoded page audio, assembled track, per-slide "
        "clips) in .slidesonnet/render/ after a successful export, for debugging. "
        "By default they are deleted; cached speech clips are never touched."
    ),
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
    keep_scratch: bool,
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
            keep_scratch=True if keep_scratch else None,
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
@_ENGINE_OPT
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
    fmt: str,
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
    """Prune the deck's own audio/render cache (.slidesonnet/ beside the PDF).

    Render scratch and logs always go. What happens to cached speech clips
    depends on --keep. When the deck's clips live in a shared pool (see
    "slidesonnet pool status"), --keep only governs the local directory: the
    pool is never touched here — "slidesonnet pool prune" does that, with every
    deck that uses the pool in view.
    """
    from slidesonnet.cache import cache_root
    from slidesonnet.clean import clean as run_clean

    if not cache_root(pdf).exists():
        click.echo("Nothing to clean.")
        return
    if keep == "nothing" and not yes:
        click.confirm(
            "Delete ALL of this deck's cached audio (including paid API audio)?",
            default=False,
            abort=True,
        )
    result = run_clean(pdf, keep=keep)  # type: ignore[arg-type]
    if result.removed_files == 0:
        click.echo("Nothing to remove.")
    else:
        msg = f"Removed {result.removed_files} files ({result.removed_mb:.1f} MB)"
        if result.kept_files:
            msg += f", kept {result.kept_files}"
        click.echo(msg)
    if result.pool is not None:
        click.echo(
            f"Speech clips live in the shared pool {result.pool}, which this command "
            "never touches. To prune orphaned clips across every deck that uses it: "
            "slidesonnet pool prune --root <course dir>"
        )


# ---- pool ----------------------------------------------------------------------


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


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
    from slidesonnet.cache import default_audio_dir, resolve_audio_dir
    from slidesonnet.clean import retire_legacy_audio
    from slidesonnet.config import load_config
    from slidesonnet.gui.library import discover_decks
    from slidesonnet.hashing import parse_audio_filename

    if not decks and not roots:
        raise click.UsageError("name the decks to migrate: --root <course dir> and/or DECK.pdf ...")
    found: list[Path] = list(decks)
    for root in roots:
        found.extend(e.pdf_path for e in discover_decks(root).decks)

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
            if legacy in seen_local or not legacy.is_dir():
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
    from slidesonnet.config import load_config
    from slidesonnet.gui.library import discover_decks
    from slidesonnet.pool import (
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
    found: list[Path] = list(decks)
    for root in roots:
        scan = discover_decks(root)
        found.extend(e.pdf_path for e in scan.decks)
        if scan.truncated:
            raise click.ClickException(
                f"the scan of {root} was cut short (too deep or too many folders); "
                "refusing to prune with an incomplete list of decks"
            )
    if not found and keep != "api":
        raise click.ClickException("no decks found under the given roots; nothing to keep by")

    by_pool: dict[Path, list[Path]] = {}
    with _cli_errors():
        for deck in sorted({p.resolve() for p in found}):
            by_pool.setdefault(resolve_audio_dir(deck, load_config(deck)).path, []).append(deck)

    for pool_dir, members in by_pool.items():
        with _cli_errors():
            plan = plan_prune(pool_dir, members, keep=keep)  # type: ignore[arg-type]
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
