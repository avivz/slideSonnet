"""Typed, importable operations for the narration editor.

Every CLI subcommand delegates here, so the whole pipeline — scaffold a sidecar,
check, synthesize TTS, export video, write subtitles — is scriptable from Python
(an LLM/CI loop or a Makefile) without launching the GUI.
"""

from __future__ import annotations

import difflib
import importlib.resources
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from slidesonnet.deck import dedupe_page_ids, default_sidecar_path, unique_real_ids
from slidesonnet.diagnostics import Diagnostic
from slidesonnet.exceptions import (
    ExportRefused,
    NarrationNotFound,
    SlideSonnetError,
    SynthesisDeclined,
    UnknownSlideId,
)
from slidesonnet.models import Backend, ProgressFn
from slidesonnet.narration.format import SidecarError, parse_sidecar
from slidesonnet.pdf.reader import read_page_ids
from slidesonnet.progress import EXPORT_PHASES, SILENT_EXPORT_PHASES

if TYPE_CHECKING:
    from slidesonnet.audio.synth import CachedDurations
    from slidesonnet.audio.track import Cue
    from slidesonnet.config import Config
    from slidesonnet.narration.model import Deck
    from slidesonnet.render import DeckTimeline

logger = logging.getLogger(__name__)

# Re-export of models.Backend, kept under the public name api.Engine.
Engine = Backend

__all__ = [
    "ExportResult",
    "Preview",
    "SynthesisPlan",
    "build_preview",
    "check_deck",
    "export",
    "init_sidecar",
    "scaffold_text",
    "sty_text",
    "synthesize_deck",
    "write_sty",
    "write_subs",
]


def sty_text() -> str:
    """Return the packaged ``slidesonnet.sty`` LaTeX macro source."""
    return (
        importlib.resources.files("slidesonnet.templates")
        .joinpath("slidesonnet.sty")
        .read_text(encoding="utf-8")
    )


def write_sty(target: Path) -> Path:
    """Write ``slidesonnet.sty`` to *target* (a file or a directory)."""
    if target.is_dir():
        target = target / "slidesonnet.sty"
    target.write_text(sty_text(), encoding="utf-8")
    return target


def scaffold_text(pdf_path: Path, pages: list[str]) -> str:
    """Build a blank sidecar: one ``@<id>`` block per page with a page-number comment."""
    from slidesonnet.narration.format import FORMAT_VERSION

    lines = [
        f"# slidesonnet-format: {FORMAT_VERSION}",
        f"# slideSonnet narration — deck: {pdf_path.name}",
        "# Write what each slide says under its @slide-id, indented like this:",
        "#",
        "# @intro-title",
        "#   utterance:",
        "#     text: Welcome to the course.",
        "#   pause: 1.5                  # seconds of silence",
        "#   utterance:",
        "#     voice: af_heart           # optional; so is pace: slow | normal | fast",
        "#     text: Let's begin.",
        "#",
        "# A slide with no narration stays silent. Full grammar:",
        "# https://github.com/avivz/slideSonnet/blob/main/docs/authoring.md",
        "",
    ]
    page_of: dict[str, int] = {}
    for i, pid in enumerate(pages, start=1):
        if pid and pid not in page_of:
            page_of[pid] = i
    for pid in unique_real_ids(pages):
        lines.append(f"@{pid}")
        lines.append(f"# page {page_of[pid]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def init_sidecar(
    pdf_path: Path,
    *,
    sidecar_path: Path | None = None,
    merge: bool = False,
    force: bool = False,
) -> Path:
    """Scaffold a blank narration sidecar from *pdf_path*'s slide-ids.

    - default: write a fresh blank sidecar (one block per page, in PDF order).
    - ``merge``: append blocks for ids missing from an existing sidecar, leaving
      existing narration untouched; safe to re-run after the deck drifts.
    - ``force``: overwrite an existing sidecar.

    Returns the sidecar path. Raises ``FileExistsError`` if it exists and neither
    ``merge`` nor ``force`` was given.
    """
    pdf_path = pdf_path.resolve()
    sidecar = sidecar_path or default_sidecar_path(pdf_path)
    pages, _ = dedupe_page_ids(read_page_ids(pdf_path))  # scaffold the effective ids
    if pages and not any(pages):
        raise SlideSonnetError(no_slide_ids_message(pdf_path, len(pages)))

    if sidecar.exists() and not (merge or force):
        raise FileExistsError(
            f"{sidecar} already exists — use --merge to add blocks for new slides, "
            "or --force to overwrite it"
        )

    if merge and sidecar.exists():
        existing = _parse_named(sidecar, lambda: parse_sidecar(sidecar.read_text(encoding="utf-8")))
        existing_ids = {b.slide_id for b in existing}
        missing = [pid for pid in unique_real_ids(pages) if pid not in existing_ids]
        if missing:
            page_of = {pid: i for i, pid in enumerate(pages, start=1) if pid}
            chunk = ["", "# --- added by `init --merge` ---"]
            for pid in missing:
                chunk.append("")
                chunk.append(f"@{pid}")
                chunk.append(f"# page {page_of[pid]}")
            text = sidecar.read_text(encoding="utf-8").rstrip() + "\n" + "\n".join(chunk) + "\n"
            sidecar.write_text(text, encoding="utf-8")
        return sidecar

    sidecar.write_text(scaffold_text(pdf_path, pages), encoding="utf-8")
    return sidecar


def check_deck(pdf_path: Path, *, sidecar_path: Path | None = None) -> list[Diagnostic]:
    """Run reconciliation diagnostics for *pdf_path* + its sidecar.

    Combines id reconciliation with the voice checks (a named voice with no
    mapping for the configured engine, or a voice the engine doesn't have),
    transition lengths, and a warning that a plain build can only be exported
    as a draft. A PDF with no slide-ids at all, and a slide-id with more than
    one narration block, are errors.
    """
    deck, config, load_diags = _load(pdf_path, sidecar_path, None, None)
    return _deck_diagnostics(pdf_path, deck, config, load_diags)


def no_slide_ids_message(pdf_path: Path, n_pages: int) -> str:
    """Why a PDF with no ``\\ssid`` markers can't be narrated, and the fix."""
    return (
        f"{pdf_path.name} has no slide-ids: none of its {n_pages} pages carries an \\ssid "
        "marker. Run 'slidesonnet sty' to write slidesonnet.sty next to your .tex, add "
        "\\usepackage{slidesonnet} to its preamble and \\ssid{some-name} to every frame, "
        "then recompile the PDF."
    )


def _deck_diagnostics(
    pdf_path: Path, deck: Deck, config: Config, load_diags: list[Diagnostic]
) -> list[Diagnostic]:
    """Everything ``check`` reports for a loaded deck (see :func:`check_deck`)."""
    from slidesonnet.diagnostics import (
        sort_diagnostics,
        transition_length_diagnostics,
        voice_diagnostics,
    )
    from slidesonnet.pdf.reader import is_plain_build
    from slidesonnet.render import build_timeline
    from slidesonnet.timing import TimingMode

    diags = list(load_diags)
    if deck.pages and not any(deck.pages):
        # One actionable error instead of an "unmarked page" warning per page.
        diags = [d for d in diags if d.code != "unmarked-page"]
        diags.append(
            Diagnostic("error", "no-slide-ids", no_slide_ids_message(pdf_path, len(deck.pages)))
        )
    diags = _duplicate_block_diagnostics(deck, diags)
    voices = {**config.voices, **deck.voices}  # deck wins over the shared library
    diags += voice_diagnostics(
        list(deck.narration.values()), voices, deck.default_voice, config.tts.backend
    )
    diags += _unknown_voice_diagnostics(deck, config)
    # Flag boundary transitions that the centered-overlay renderer would clamp.
    # Estimate timing keeps check audio-free; the clamp itself is duration-driven.
    timeline = build_timeline(deck, TimingMode("estimate"), video=config.video)
    diags += transition_length_diagnostics(deck.pages, deck.narration, timeline.page_durations)
    if is_plain_build(pdf_path):
        diags.append(
            Diagnostic(
                "warning",
                "plain-build",
                f"{pdf_path.name} is a plain build (page numbers and progress bars hidden), so "
                "'slidesonnet export' will only make a draft: add --draft for a preview "
                "video, or compile a final build first: "
                "latexmk -pdf -usepretex='\\def\\ssfinal{}' <deck>.tex",
            )
        )
    return sort_diagnostics(diags)


_HEADER_LINE_RE = re.compile(r"^\s*@(?P<id>\S+)\s*(?:#.*)?$")


def _duplicate_block_diagnostics(deck: Deck, diags: list[Diagnostic]) -> list[Diagnostic]:
    """Report a slide-id with several ``@`` blocks as one error, with their line numbers.

    Loading keeps every block by renaming the later ones (``intro`` → ``intro-2``),
    which would otherwise surface as a confusing orphan ``intro-2``.
    """
    if not deck.sidecar_path.exists():
        return diags
    lines: dict[str, list[int]] = {}
    text = deck.sidecar_path.read_text(encoding="utf-8")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        m = _HEADER_LINE_RE.match(raw)
        if m:
            lines.setdefault(m.group("id"), []).append(lineno)
    renamed = set(deck.narration) - set(lines)  # the ids loading made up
    kept = [d for d in diags if d.code != "duplicate-block" and d.slide_id not in renamed]
    for sid, where in lines.items():
        if len(where) > 1:
            at = ", ".join(str(n) for n in where[:-1]) + f" and {where[-1]}"
            kept.append(
                Diagnostic(
                    "error",
                    "duplicate-block",
                    f"slide-id '{sid}' has more than one narration block (lines {at} of "
                    f"{deck.sidecar_path.name}) — merge them into a single @{sid} block",
                    sid,
                )
            )
    return kept


def _unknown_voice_diagnostics(deck: Deck, config: Config) -> list[Diagnostic]:
    """Error where an utterance asks the engine for a voice it doesn't have.

    Only engines that publish their voice list (Kokoro; Qwen3's CustomVoice
    model) can be checked; cloud voices are account-specific and pass through.
    A voice-map name resolves to its engine voice first, as synthesis does.
    """
    from slidesonnet.models import resolve_voice
    from slidesonnet.tts import BACKENDS

    backend = config.tts.backend
    engine = BACKENDS[backend].factory(config.tts)
    known = engine.list_voices()
    if not known:
        return []
    voices = {**config.voices, **deck.voices}
    diags: list[Diagnostic] = []
    reported: set[tuple[str | None, str]] = set()

    def flag(name: str, resolved: str, slide_id: str | None) -> None:
        if resolved in known or resolved.endswith(".pt") or (slide_id, name) in reported:
            return
        reported.add((slide_id, name))
        via = f" (the voice map sends '{name}' to '{resolved}')" if resolved != name else ""
        close = difflib.get_close_matches(resolved, known, n=1, cutoff=0.6)
        fix = (
            f"did you mean '{close[0]}'?"
            if close
            else f"use one of {', '.join(known[:4])}, … ('slidesonnet edit' lists them all)"
        )
        diags.append(
            Diagnostic(
                "error",
                "unknown-voice",
                f"voice '{name}' isn't a {backend} voice{via} — {fix}",
                slide_id,
            )
        )

    default = engine.default_voice()
    if default:
        flag(default, default, None)
    for block in deck.narration.values():
        for seg in block.speech_segments:
            name = seg.voice or deck.default_voice
            resolved = resolve_voice(name, voices, backend) if name else None
            if name and resolved:
                flag(name, resolved, block.slide_id)
    return diags


def _audio_dir(pdf_path: Path, config: Config) -> Path:
    """The deck's clip directory — a shared pool when one is configured.

    Migration on touch: when a pool is in use, clips still sitting in the
    deck's old local cache are copied in first, so a deck that predates the
    pool setting never re-buys what it already had.
    """
    from slidesonnet.cache import adopt_legacy_audio, resolve_audio_dir

    res = resolve_audio_dir(pdf_path, config)
    if res.shared:
        adopt_legacy_audio(pdf_path, res.path)
    return res.path


def _load(
    pdf_path: Path,
    sidecar_path: Path | None,
    config_path: Path | None,
    engine: Engine | None,
) -> tuple[Deck, Config, list[Diagnostic]]:
    """Load the deck and its config, plus the id diagnostics found while loading.

    The fuller report (voices, transitions, build type) is
    :func:`_deck_diagnostics`, computed only where it's needed: ``check`` and a
    final export. Synthesis and previews run per edit and skip it.
    """
    from slidesonnet.config import load_config
    from slidesonnet.deck import load_deck

    if sidecar_path is not None and not sidecar_path.exists():
        # Named on purpose, so a miss is a typo — not an un-narrated deck.
        raise NarrationNotFound(
            f"narration file {sidecar_path} not found — check the --narration path, or "
            f"create it with: slidesonnet init {pdf_path.name} --narration {sidecar_path}"
        )
    config = load_config(pdf_path, config_path=config_path)
    # The engine reads its API key from this deck's .env (never os.environ-wide:
    # one editor process serves many decks), found wherever the cwd is.
    config.tts.env_dir = pdf_path.resolve().parent
    if engine is not None:
        config.tts.backend = engine
    sidecar = sidecar_path or default_sidecar_path(pdf_path.resolve())
    deck, load_diags = _parse_named(sidecar, lambda: load_deck(pdf_path, sidecar_path=sidecar_path))
    return deck, config, load_diags


def _parse_named[T](sidecar: Path, parse: Callable[[], T]) -> T:
    """Run *parse* (which reads *sidecar*), naming the file in any syntax error."""
    try:
        return parse()
    except SidecarError as e:
        raise SidecarError(f"{sidecar.name}, {e} — fix that line and re-run") from e


@dataclass(frozen=True)
class SynthesisPlan:
    """What a synthesis run is about to do, handed to an ``approve`` hook first."""

    engine: str
    paid: bool  # the engine spends metered API credits
    total: int  # utterances in scope
    uncached: int  # distinct clips that would be generated (not already cached)


ApproveFn = Callable[[SynthesisPlan], bool]


def _plan(deck: Deck, config: Config, audio_dir: Path, only_ids: set[str] | None) -> SynthesisPlan:
    from slidesonnet.audio.synth import ref_cache_status
    from slidesonnet.tts import BACKENDS

    status = [
        (ref, cached)
        for ref, cached in ref_cache_status(deck, config, audio_dir)
        if only_ids is None or ref.slide_id in only_ids
    ]
    uncached = {(r.text, r.voice, r.pace) for r, cached in status if not cached}
    backend = config.tts.backend
    return SynthesisPlan(backend, BACKENDS[backend].paid, len(status), len(uncached))


def _approve(plan: SynthesisPlan, approve: ApproveFn) -> None:
    if not approve(plan):
        raise SynthesisDeclined(
            f"Nothing was generated: {plan.uncached} new {plan.engine} clip(s) weren't approved."
        )


def _check_ids(deck: Deck, pdf_path: Path, only_ids: set[str] | None) -> None:
    """Refuse slide-ids the deck doesn't have, suggesting the closest real one."""
    known = unique_real_ids(deck.pages)
    for sid in sorted((only_ids or set()) - set(known)):
        close = difflib.get_close_matches(sid, known, n=1, cutoff=0.6)
        hint = (
            f"did you mean '{close[0]}'?"
            if close
            else f"'slidesonnet check {pdf_path.name}' lists the deck's slides"
        )
        raise UnknownSlideId(f"Unknown slide-id '{sid}' — {hint}")


def synthesize_deck(
    pdf_path: Path,
    *,
    sidecar_path: Path | None = None,
    config_path: Path | None = None,
    engine: Engine | None = None,
    only_ids: set[str] | None = None,
    only_segments: set[tuple[str, int]] | None = None,
    force: bool = False,
    progress: ProgressFn | None = None,
    approve: ApproveFn | None = None,
) -> int:
    """Synthesize narration into the content-addressed cache (cache-aware).

    Returns the number of speech segments newly synthesized (not from cache).
    ``only_ids`` must name slides the deck has (:class:`UnknownSlideId`).
    ``only_segments`` targets specific ``(slide_id, speech_index)`` pairs.
    ``force`` re-synthesizes the targeted segments even when already cached.
    *approve*, when given, sees the :class:`SynthesisPlan` first; returning
    False raises :class:`SynthesisDeclined` before anything is generated.
    """
    from slidesonnet.audio.synth import synthesize as _synth

    deck, config, _ = _load(pdf_path, sidecar_path, config_path, engine)
    _check_ids(deck, pdf_path, only_ids)
    audio_dir = _audio_dir(pdf_path, config)
    if approve is not None:
        _approve(_plan(deck, config, audio_dir, only_ids), approve)
    results = _synth(
        deck,
        config,
        audio_dir=audio_dir,
        only_ids=only_ids,
        only_segments=only_segments,
        force=force,
        progress=progress,
    )
    return sum(1 for r in results.values() if not r.from_cache)


@dataclass
class ExportResult:
    """Outputs of an export run."""

    video: Path
    subtitles: list[Path] = field(default_factory=list)
    duration: float = 0.0
    silent: bool = False


def export_phases(
    *, silent: bool = False, timing: str = "tts", wpm: float = 150.0
) -> tuple[str, ...]:
    """The progress phases :func:`export` reports for these options, in order.

    Only a ``tts``-timed, non-silent export has speech to synthesize, assemble,
    and mux; everything else renders the video and concatenates it. Hand the
    result to :class:`slidesonnet.progress.RunProgress` to get one overall
    percentage across the whole export.
    """
    from slidesonnet.timing import parse_timing

    if not silent and parse_timing(timing, wpm=wpm).kind == "tts":
        return EXPORT_PHASES
    return SILENT_EXPORT_PHASES


def draft_output(output: Path) -> Path:
    """``deck.mp4`` → ``deck.draft.mp4`` (unchanged if it already says draft)."""
    if output.stem.endswith(".draft"):
        return output
    return output.with_name(f"{output.stem}.draft{output.suffix}")


def export_blockers(pdf_path: Path) -> list[str]:
    """Why *pdf_path* isn't ready for a final video; empty when it is.

    A plain build hides page numbers and progress bars; open review
    conversations about slides mean changes still await a verdict (the deck
    conversation never counts). A PDF from an older ``slidesonnet.sty`` carries
    no build marker and isn't held back.
    """
    from slidesonnet.pdf.reader import is_plain_build
    from slidesonnet.review.ops import open_slide_conversations

    reasons: list[str] = []
    if is_plain_build(pdf_path):
        reasons.append(
            f"{pdf_path.name} is a plain build (page numbers and progress bars hidden) — "
            "compile it as a final build: latexmk -pdf -usepretex='\\def\\ssfinal{}' ..."
        )
    open_convs = open_slide_conversations(pdf_path)
    if open_convs:
        ids = ", ".join(c.id for c in open_convs)
        reasons.append(f"{len(open_convs)} review conversation(s) still open: {ids}")
    return reasons


def export(
    pdf_path: Path,
    output: Path,
    *,
    sidecar_path: Path | None = None,
    config_path: Path | None = None,
    engine: Engine | None = None,
    silent: bool = False,
    timing: str = "tts",
    wpm: float = 150.0,
    subtitles: Literal["srt", "vtt", "both", "none"] = "srt",
    sub_granularity: str = "segment",
    keep_scratch: bool | None = None,
    progress: ProgressFn | None = None,
    draft: bool = False,
    approve: ApproveFn | None = None,
) -> ExportResult:
    """Render the deck to a narrated (or silent) MP4 with optional subtitles.

    Refuses (:class:`ExportRefused`) when :func:`export_blockers` finds the deck
    unready for a final video — a plain build, or open review conversations —
    or when the deck has errors ``check`` would report, or (for a narrated
    video) no slide has narration yet. A *draft* skips those checks and writes
    ``<name>.draft.mp4`` instead of *output*. *approve* is consulted before any
    synthesis, as in :func:`synthesize_deck`.

    On success the render intermediates (decoded page audio, assembled track,
    per-slide clips) are deleted unless *keep_scratch* is true — or, when it is
    ``None``, unless ``[video] keep_scratch`` is set in the config. A failed
    render always leaves them for debugging.
    """
    from slidesonnet.audio.synth import (
        page_speech_clips,
        page_speech_durations,
    )
    from slidesonnet.audio.synth import (
        synthesize as _synth,
    )
    from slidesonnet.cache import render_dir
    from slidesonnet.diagnostics import boundary_transition
    from slidesonnet.render import (
        build_timeline,
        compose_video,
        prune_render_scratch,
        render_audio_track,
    )
    from slidesonnet.timing import TimingMode, parse_timing

    if draft:
        output = draft_output(output)
    else:
        reasons = export_blockers(pdf_path)
        if reasons:
            raise ExportRefused(reasons)
    deck, config, load_diags = _load(pdf_path, sidecar_path, config_path, engine)
    mode = parse_timing(timing, wpm=wpm)

    audible = export_phases(silent=silent, timing=timing, wpm=wpm) == EXPORT_PHASES
    if not draft:
        diags = _deck_diagnostics(pdf_path, deck, config, load_diags)
        _refuse_unready(pdf_path, deck, diags, audible=audible)
    if silent and mode.kind == "tts":
        mode = TimingMode("estimate", wpm=wpm)  # tts is meaningless without audio

    rdir = render_dir(pdf_path)
    page_audios: list[Path] | None = None
    audio_track: Path | None = None
    if audible:
        audio_dir = _audio_dir(pdf_path, config)
        if approve is not None:
            _approve(_plan(deck, config, audio_dir, None), approve)
        results = _synth(deck, config, audio_dir=audio_dir, progress=progress)
        timeline = build_timeline(
            deck,
            mode,
            video=config.video,
            speech_durations_by_page=page_speech_durations(deck, results),
        )
        audio_track, page_audios = render_audio_track(
            timeline, page_speech_clips(deck, results), render_dir=rdir, progress=progress
        )
    else:
        timeline = build_timeline(deck, mode, video=config.video)
    pages = deck.pages
    boundaries = [
        boundary_transition(deck.page_narration(pages[i]), deck.page_narration(pages[i + 1]))
        for i in range(len(pages) - 1)
    ]
    compose_video(
        timeline,
        _images(pdf_path, rdir),
        output,
        config=config,
        page_audios=page_audios,
        render_dir=rdir,
        transitions=boundaries,
        audio_track=audio_track,
        progress=progress,
    )

    subs_paths = _write_subtitle_files(deck, timeline, output, subtitles, sub_granularity)
    if not (config.video.keep_scratch if keep_scratch is None else keep_scratch):
        freed = prune_render_scratch(rdir)
        logger.debug("pruned %.1f MB of render scratch under %s", freed / 1e6, rdir)
    return ExportResult(
        video=output, subtitles=subs_paths, duration=timeline.total_duration, silent=not audible
    )


def _refuse_unready(pdf_path: Path, deck: Deck, diags: list[Diagnostic], *, audible: bool) -> None:
    """Refuse a final export of a deck ``check`` finds broken, or with nothing to say."""
    reasons = [d.message for d in diags if d.severity == "error"]
    narrated = any(deck.page_narration(pid).speech_segments for pid in deck.pages if pid)
    if audible and not narrated and any(deck.pages):
        reasons.append(
            f"no slide has narration yet — write some in {deck.sidecar_path.name} (or run "
            f"'slidesonnet edit {pdf_path.name}'), or make a silent video with --silent"
        )
    if reasons:
        raise ExportRefused(reasons)


def write_subs(
    pdf_path: Path,
    output: Path,
    *,
    fmt: Literal["srt", "vtt"] = "srt",
    sub_granularity: str = "segment",
    timing: str = "tts",
    wpm: float = 150.0,
    sidecar_path: Path | None = None,
    config_path: Path | None = None,
    engine: Engine | None = None,
    allow_estimates: bool = False,
) -> Path:
    """Write subtitles without rendering video, timed against the cached audio.

    *engine* must name the engine whose audio this deck was rendered with — the
    cache key embeds the backend, so subtitles asked of a different engine than
    the video find nothing. Under ``timing="tts"`` any utterance without cached
    audio raises :class:`SubtitleTimingError` rather than quietly standing in a
    words-per-minute guess; pass *allow_estimates* (or ``timing="estimate"``) to
    accept guessed times on purpose.
    """
    from slidesonnet.audio.synth import cached_durations
    from slidesonnet.exceptions import SubtitleTimingError
    from slidesonnet.render import build_timeline, subtitle_entries
    from slidesonnet.subtitles import format_srt, format_vtt
    from slidesonnet.timing import parse_timing

    deck, config, _ = _load(pdf_path, sidecar_path, config_path, engine)
    mode = parse_timing(timing, wpm=wpm)
    if mode.kind == "tts":
        cached = cached_durations(deck, config, _audio_dir(pdf_path, config), fallback_wpm=wpm)
        if cached.estimated:
            message = _estimated_timing_message(cached, config.tts.backend, wpm)
            if not allow_estimates:
                raise SubtitleTimingError(message)
            logger.warning("%s", message)
        timeline = build_timeline(
            deck, mode, video=config.video, speech_durations_by_page=cached.per_page
        )
    else:
        timeline = build_timeline(deck, mode, video=config.video)

    entries = subtitle_entries(deck, timeline, granularity=sub_granularity)
    text = format_srt(entries) if fmt == "srt" else format_vtt(entries)
    _write_if_changed(output, text)
    return output


def _estimated_timing_message(cached: CachedDurations, backend: str, wpm: float) -> str:
    """Explain which lines have no audio, and the three ways out."""
    # Several utterances can share a slide, so name distinct slides — and count
    # the overflow against that same deduped list, not the raw utterances.
    slides = list(dict.fromkeys(r.slide_id for r in cached.estimated))
    shown = ", ".join(slides[:3])
    more = f" (and {len(slides) - 3} more)" if len(slides) > 3 else ""
    return (
        f"{len(cached.estimated)} of {cached.total} narration lines have no generated audio for the "
        f"'{backend}' voice, so their subtitle times would be guessed at {wpm:g} words per "
        f"minute — and every cue after the first guess slides out of step with the video. "
        f"Slides without audio: {shown}{more}. "
        f"Either generate the narration first ('slidesonnet tts'), or point subs at the voice "
        f"the video was made with ('--engine'), or ask for guessed times on purpose "
        f"('--allow-estimates')."
    )


def _write_subtitle_files(
    deck: Deck,
    timeline: DeckTimeline,
    video_output: Path,
    which: str,
    granularity: str,
) -> list[Path]:
    from slidesonnet.render import subtitle_entries
    from slidesonnet.subtitles import format_srt, format_vtt

    if which == "none":
        return []
    entries = subtitle_entries(deck, timeline, granularity=granularity)
    out: list[Path] = []
    if which in {"srt", "both"}:
        p = video_output.with_suffix(".srt")
        _write_if_changed(p, format_srt(entries))
        out.append(p)
    if which in {"vtt", "both"}:
        p = video_output.with_suffix(".vtt")
        _write_if_changed(p, format_vtt(entries))
        out.append(p)
    return out


def _write_if_changed(path: Path, text: str) -> bool:
    """Write *text* to *path* unless the file already holds exactly those bytes.

    Subtitles come out byte-identical whenever the narration didn't move, and a
    rewrite would only bump the mtime — which is what make-style build graphs,
    file watchers, and rsync key freshness on. A write goes through a temp file
    and a rename, so an interrupted export never leaves half a subtitle file.
    Returns whether a write happened.
    """
    from slidesonnet.atomic import atomic_write_text

    data = text.encode("utf-8")
    try:
        if path.read_bytes() == data:
            return False
    except OSError:
        pass
    atomic_write_text(path, text)
    return True


def _images(pdf_path: Path, rdir: Path) -> list[Path]:
    from slidesonnet.pdf.reader import rasterize

    return rasterize(pdf_path, rdir / "pages")


@dataclass
class Preview:
    """A whole-deck (or single-slide) preview: one audio track + its cue sheet."""

    track: Path
    cues: list[Cue] = field(default_factory=list)
    total_duration: float = 0.0
    #: Every utterance's span in the track (the editor follows the spoken word).
    speech: list[SpeechSpan] = field(default_factory=list)


@dataclass(frozen=True)
class SpeechSpan:
    """Where one utterance plays in a preview track, in seconds."""

    slide_id: str
    index: int  # the utterance's position among the slide's spoken lines
    start: float
    end: float


def build_preview(
    pdf_path: Path,
    *,
    sidecar_path: Path | None = None,
    config_path: Path | None = None,
    engine: Engine | None = None,
    only_id: str | None = None,
    progress: ProgressFn | None = None,
    render_dir: Path | None = None,
) -> Preview:
    """Build a sample-accurate preview track + cue sheet (whole deck or one slide).

    *render_dir* overrides where the page WAVs and ``track.wav`` are assembled
    (default: the deck's render directory, shared with export so an unchanged
    deck reuses its page audio).
    """
    from slidesonnet.audio.synth import (
        page_speech_clips,
        page_speech_durations,
    )
    from slidesonnet.audio.synth import (
        synthesize as _synth,
    )
    from slidesonnet.cache import render_dir as deck_render_dir
    from slidesonnet.render import build_timeline, render_audio_track
    from slidesonnet.timing import TimingMode

    deck, config, _ = _load(pdf_path, sidecar_path, config_path, engine)
    if only_id:  # render a one-page track; other pages' clips aren't synthesized
        deck = deck.restricted_to(only_id)
    only_ids = {only_id} if only_id else None
    results = _synth(
        deck, config, audio_dir=_audio_dir(pdf_path, config), only_ids=only_ids, progress=progress
    )
    rdir = render_dir or deck_render_dir(pdf_path)
    timeline = build_timeline(
        deck,
        TimingMode("tts"),
        video=config.video,
        speech_durations_by_page=page_speech_durations(deck, results),
    )
    track, _ = render_audio_track(
        timeline, page_speech_clips(deck, results), render_dir=rdir, progress=progress
    )
    speech = [
        SpeechSpan(page.slide_id, i, page_start + st.start, page_start + st.end)
        for page_start, page in zip(timeline.page_starts, timeline.pages, strict=True)
        for i, st in enumerate(page.speech_timings)
    ]
    return Preview(
        track=track,
        cues=timeline.cue_sheet(),
        total_duration=timeline.total_duration,
        speech=speech,
    )
