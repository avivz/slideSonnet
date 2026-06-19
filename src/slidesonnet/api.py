"""Typed, importable operations for the narration editor.

Every CLI subcommand delegates here, so the whole pipeline — scaffold a sidecar,
check, synthesize TTS, export video, write subtitles — is scriptable from Python
(an LLM/CI loop or a Makefile) without launching the GUI.
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from slidesonnet.deck import dedupe_page_ids, default_sidecar_path, unique_real_ids
from slidesonnet.diagnostics import Diagnostic
from slidesonnet.narration.format import parse_sidecar
from slidesonnet.pdf.reader import read_page_ids

from slidesonnet.models import Backend, ProgressFn

if TYPE_CHECKING:
    from slidesonnet.audio.track import Cue
    from slidesonnet.config import Config
    from slidesonnet.narration.model import Deck
    from slidesonnet.render import DeckTimeline

# Re-export of models.Backend, kept under the public name api.Engine.
Engine = Backend

__all__ = [
    "sty_text",
    "write_sty",
    "scaffold_text",
    "init_sidecar",
    "check_deck",
    "synthesize_deck",
    "ExportResult",
    "export",
    "write_subs",
    "Preview",
    "build_preview",
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
        "# Fill in narration under each @slide-id. '[pause N]' inserts N seconds of silence.",
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

    if sidecar.exists() and not (merge or force):
        raise FileExistsError(
            f"{sidecar} already exists — use merge=True to top up or force=True to overwrite"
        )

    if merge and sidecar.exists():
        existing = parse_sidecar(sidecar.read_text(encoding="utf-8"))
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

    Combines id reconciliation with the portable-voice-layer check: a named
    voice (or the deck default) that has no mapping for the configured engine.
    """
    from slidesonnet.config import load_config
    from slidesonnet.deck import load_deck
    from slidesonnet.diagnostics import (
        sort_diagnostics,
        transition_length_diagnostics,
        voice_diagnostics,
    )
    from slidesonnet.render import build_timeline
    from slidesonnet.timing import TimingMode

    deck, diags = load_deck(pdf_path, sidecar_path=sidecar_path)
    config = load_config(pdf_path)
    voices = {**config.voices, **deck.voices}  # deck wins over the shared library
    voice_diags = voice_diagnostics(
        list(deck.narration.values()), voices, deck.default_voice, config.tts.backend
    )
    # Flag boundary transitions that the centered-overlay renderer would clamp.
    # Estimate timing keeps check audio-free; the clamp itself is duration-driven.
    timeline = build_timeline(deck, TimingMode("estimate"), video=config.video)
    trans_diags = transition_length_diagnostics(deck.pages, deck.narration, timeline.page_durations)
    return sort_diagnostics(diags + voice_diags + trans_diags)


def _load(
    pdf_path: Path,
    sidecar_path: Path | None,
    config_path: Path | None,
    engine: Engine | None,
) -> tuple[Deck, Config]:
    from slidesonnet.config import load_config
    from slidesonnet.deck import load_deck
    from slidesonnet.env import load_env

    # Anchor the .env search at the deck dir so a cloud key is found no matter
    # where the editor/CLI was launched from (the cwd may never reach it upward).
    load_env(pdf_path.parent)
    config = load_config(pdf_path, config_path=config_path)
    if engine is not None:
        config.tts.backend = engine
    deck, _ = load_deck(pdf_path, sidecar_path=sidecar_path)
    return deck, config


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
) -> int:
    """Synthesize narration into the content-addressed cache (cache-aware).

    Returns the number of speech segments newly synthesized (not from cache).
    ``only_segments`` targets specific ``(slide_id, speech_index)`` pairs.
    ``force`` re-synthesizes the targeted segments even when already cached.
    """
    from slidesonnet.audio.synth import synthesize as _synth
    from slidesonnet.cache import audio_dir

    deck, config = _load(pdf_path, sidecar_path, config_path, engine)
    results = _synth(
        deck,
        config,
        audio_dir=audio_dir(pdf_path),
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
    progress: ProgressFn | None = None,
) -> ExportResult:
    """Render the deck to a narrated (or silent) MP4 with optional subtitles."""
    from slidesonnet.audio.synth import (
        page_speech_clips,
        page_speech_durations,
        synthesize as _synth,
    )
    from slidesonnet.cache import audio_dir, render_dir
    from slidesonnet.diagnostics import boundary_transition
    from slidesonnet.render import build_timeline, compose_video, render_audio_track
    from slidesonnet.timing import TimingMode, parse_timing

    deck, config = _load(pdf_path, sidecar_path, config_path, engine)
    mode = parse_timing(timing, wpm=wpm)

    audible = (not silent) and mode.kind == "tts"
    if silent and mode.kind == "tts":
        mode = TimingMode("estimate", wpm=wpm)  # tts is meaningless without audio

    rdir = render_dir(pdf_path)
    page_audios: list[Path] | None = None
    audio_track: Path | None = None
    if audible:
        results = _synth(deck, config, audio_dir=audio_dir(pdf_path), progress=progress)
        timeline = build_timeline(
            deck,
            mode,
            video=config.video,
            speech_durations_by_page=page_speech_durations(deck, results),
        )
        audio_track, page_audios = render_audio_track(
            timeline, page_speech_clips(deck, results), render_dir=rdir
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
    )

    subs_paths = _write_subtitle_files(deck, timeline, output, subtitles, sub_granularity)
    return ExportResult(
        video=output, subtitles=subs_paths, duration=timeline.total_duration, silent=not audible
    )


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
) -> Path:
    """Write subtitles without rendering video (cached audio durations, else timing model)."""
    from slidesonnet.audio.synth import cached_durations
    from slidesonnet.cache import audio_dir
    from slidesonnet.render import build_timeline, subtitle_entries
    from slidesonnet.subtitles import format_srt, format_vtt
    from slidesonnet.timing import parse_timing

    deck, config = _load(pdf_path, sidecar_path, config_path, None)
    mode = parse_timing(timing, wpm=wpm)
    if mode.kind == "tts":
        durations = cached_durations(deck, config, audio_dir(pdf_path), fallback_wpm=wpm)
        timeline = build_timeline(
            deck, mode, video=config.video, speech_durations_by_page=durations
        )
    else:
        timeline = build_timeline(deck, mode, video=config.video)

    entries = subtitle_entries(deck, timeline, granularity=sub_granularity)
    text = format_srt(entries) if fmt == "srt" else format_vtt(entries)
    output.write_text(text, encoding="utf-8")
    return output


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
        p.write_text(format_srt(entries), encoding="utf-8")
        out.append(p)
    if which in {"vtt", "both"}:
        p = video_output.with_suffix(".vtt")
        p.write_text(format_vtt(entries), encoding="utf-8")
        out.append(p)
    return out


def _images(pdf_path: Path, rdir: Path) -> list[Path]:
    from slidesonnet.pdf.reader import rasterize

    return rasterize(pdf_path, rdir / "pages")


@dataclass
class Preview:
    """A whole-deck (or single-slide) preview: one audio track + its cue sheet."""

    track: Path
    cues: list[Cue] = field(default_factory=list)
    total_duration: float = 0.0


def build_preview(
    pdf_path: Path,
    *,
    sidecar_path: Path | None = None,
    config_path: Path | None = None,
    engine: Engine | None = None,
    only_id: str | None = None,
    progress: ProgressFn | None = None,
) -> Preview:
    """Build a sample-accurate preview track + cue sheet (whole deck or one slide)."""
    from slidesonnet.audio.synth import (
        page_speech_clips,
        page_speech_durations,
        synthesize as _synth,
    )
    from slidesonnet.cache import audio_dir, render_dir
    from slidesonnet.render import build_timeline, render_audio_track
    from slidesonnet.timing import TimingMode

    deck, config = _load(pdf_path, sidecar_path, config_path, engine)
    if only_id:  # render a one-page track; other pages' clips aren't synthesized
        deck = deck.restricted_to(only_id)
    only_ids = {only_id} if only_id else None
    results = _synth(
        deck, config, audio_dir=audio_dir(pdf_path), only_ids=only_ids, progress=progress
    )
    rdir = render_dir(pdf_path)
    timeline = build_timeline(
        deck,
        TimingMode("tts"),
        video=config.video,
        speech_durations_by_page=page_speech_durations(deck, results),
    )
    track, _ = render_audio_track(
        timeline, page_speech_clips(deck, results), render_dir=rdir, progress=progress
    )
    return Preview(track=track, cues=timeline.cue_sheet(), total_duration=timeline.total_duration)
