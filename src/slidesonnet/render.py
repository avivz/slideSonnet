"""Render orchestration: deck timeline, subtitles, audio track, and video.

Ties the pure timing model to synthesized audio, the FFmpeg composer, and the
subtitle writers. The deck timeline is the single source of truth shared by the
exported video, the preview cue sheet, and the subtitles.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from slidesonnet.audio.track import Cue, assemble_track, build_page_audio, cue_sheet, page_pieces
from slidesonnet.config import Config
from slidesonnet.models import VideoConfig
from slidesonnet.narration import transitions as transitions_mod
from slidesonnet.narration.model import Deck, PageNarration, Segment, Transition
from slidesonnet.subtitles import SubtitleEntry, split_text
from slidesonnet.timing import PageTiming, TimingMode, compute_page_timing
from slidesonnet.video.composer import (
    compose_silent_segment,
    concatenate_segments,
)

logger = logging.getLogger(__name__)

# Default hold (seconds) for a page with no speech and no explicit pause.
DEFAULT_HOLD = 2.5


@dataclass
class DeckTimeline:
    """Per-page timeline for the whole deck, in PDF page order."""

    pages: list[PageTiming] = field(default_factory=list)

    @property
    def slide_ids(self) -> list[str]:
        return [p.slide_id for p in self.pages]

    @property
    def page_durations(self) -> list[float]:
        return [p.duration for p in self.pages]

    @property
    def page_starts(self) -> list[float]:
        starts: list[float] = []
        t = 0.0
        for p in self.pages:
            starts.append(t)
            t += p.duration
        return starts

    @property
    def total_duration(self) -> float:
        return sum(p.duration for p in self.pages)

    def cue_sheet(self) -> list[Cue]:
        return cue_sheet(self.page_starts, self.slide_ids)


def build_timeline(
    deck: Deck,
    mode: TimingMode,
    *,
    video: VideoConfig,
    speech_durations_by_page: list[list[float]] | None = None,
    default_hold: float = DEFAULT_HOLD,
) -> DeckTimeline:
    """Build the deck timeline under *mode*.

    *speech_durations_by_page* (required for ``tts`` mode) aligns to ``deck.pages``;
    each entry holds that page's speech-segment durations. Pages with no speech
    and no explicit pause are held *default_hold* seconds.
    """
    pages: list[PageTiming] = []
    for i, slide_id in enumerate(deck.pages):
        block = deck.page_narration(slide_id)
        if not block.segments:
            block = PageNarration(slide_id=slide_id, segments=[Segment.pause(default_hold)])
        sd = speech_durations_by_page[i] if speech_durations_by_page is not None else None
        # An explicit edge pause *is* the slide's start/end silence, so the
        # default lead/tail filler applies only when there's no such pause
        # (explicit replaces default). The pause itself is counted in the body.
        lead = 0.0 if block.segments[0].is_pause else video.pre_silence
        tail = 0.0 if block.segments[-1].is_pause else video.tail_seconds
        pages.append(
            compute_page_timing(
                block,
                mode,
                speech_durations=sd,
                lead=lead,
                tail=tail,
            )
        )
    return DeckTimeline(pages=pages)


def subtitle_entries(
    deck: Deck,
    timeline: DeckTimeline,
    *,
    granularity: str = "segment",
    max_chars: int = 80,
) -> list[SubtitleEntry]:
    """Build subtitle cues timed against *timeline* (cue text excludes pauses)."""
    starts = timeline.page_starts
    entries: list[SubtitleEntry] = []
    index = 1
    for page_start, page in zip(starts, timeline.pages, strict=True):
        speech = page.speech_timings
        if not speech:
            continue
        if granularity == "slide":
            block = deck.page_narration(page.slide_id)
            entries.append(
                SubtitleEntry(
                    index=index,
                    start=page_start + speech[0].start,
                    end=page_start + speech[-1].end,
                    text=block.speech_text,
                )
            )
            index += 1
            continue
        # segment granularity: one (or more, if long) cue per speech segment
        for st in speech:
            seg_start = page_start + st.start
            seg_end = page_start + st.end
            chunks = split_text(st.segment.text, max_chars)
            if len(chunks) <= 1:
                entries.append(SubtitleEntry(index, seg_start, seg_end, st.segment.text))
                index += 1
                continue
            total = sum(len(c) for c in chunks) or 1
            t = seg_start
            for chunk in chunks:
                span = (seg_end - seg_start) * len(chunk) / total
                entries.append(SubtitleEntry(index, t, t + span, chunk))
                t += span
                index += 1
    return entries


def _page_fingerprint(timing: PageTiming, speech_clips: list[Path]) -> str:
    """A content key for one page's rendered audio.

    Captures everything :func:`build_page_audio` consumes — the ordered pieces
    (silence durations) and each speech clip's identity + size/mtime — so a page
    whose inputs are unchanged can reuse its WAV instead of re-running ffmpeg.
    """
    parts: list[str] = [timing.slide_id]
    for piece in page_pieces(timing, speech_clips):
        if piece.kind == "speech" and piece.path is not None:
            try:
                st = piece.path.stat()
                parts.append(f"s:{piece.path}:{st.st_size}:{st.st_mtime_ns}")
            except OSError:
                parts.append(f"s:{piece.path}:missing")
        else:
            parts.append(f"z:{piece.seconds:.4f}")
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def render_audio_track(
    timeline: DeckTimeline,
    page_clips: list[list[Path]],
    *,
    render_dir: Path,
) -> tuple[Path, list[Path]]:
    """Build per-page audio (lead+segments+tail) and the assembled deck track.

    The assembly is fingerprint-cached (``track.cache.json``): a page WAV is
    rebuilt only when its clips or timing change, and the whole-deck ``track.wav``
    is re-concatenated only when some page changed — so a repeat preview of an
    unchanged deck does no ffmpeg work at all. Returns ``(track_path,
    page_audio_paths)``.
    """
    render_dir.mkdir(parents=True, exist_ok=True)
    silence_dir = render_dir / "silence"
    silence_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = render_dir / "track.cache.json"
    old: dict[str, object] = {}
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
    raw_pages = old.get("pages")
    old_pages: dict[str, str] = raw_pages if isinstance(raw_pages, dict) else {}

    page_audios: list[Path] = []
    new_pages: dict[str, str] = {}
    for i, page in enumerate(timeline.pages):
        out = render_dir / f"page-{i + 1:04d}.wav"
        fp = _page_fingerprint(page, page_clips[i])
        if not (out.exists() and old_pages.get(out.name) == fp):
            build_page_audio(page, page_clips[i], out, silence_dir=silence_dir)
        new_pages[out.name] = fp
        page_audios.append(out)

    track = render_dir / "track.wav"
    track_fp = hashlib.sha256(
        "\x00".join(new_pages[p.name] for p in page_audios).encode()
    ).hexdigest()
    if not (track.exists() and old.get("track") == track_fp):
        assemble_track(page_audios, track)

    try:
        manifest_path.write_text(
            json.dumps({"pages": new_pages, "track": track_fp}), encoding="utf-8"
        )
    except OSError:
        pass
    return track, page_audios


def transition_morph_seconds(transitions: list[Transition], page_fulls: list[float]) -> list[float]:
    """Per-boundary morph durations, centered on the boundary and clamped to fit.

    ``transitions[i]`` is the boundary between page ``i`` and ``i+1``. A
    ``D``-second animated transition is centered on that boundary — ``D/2`` over
    the tail of page ``i`` and ``D/2`` over the head of page ``i+1`` — so it is
    clamped to ``min(full_i, full_{i+1})``. That bound also guarantees a page
    flanked by two transitions never gives up more than its whole duration
    (each adjacent ``D ≤ full`` ⇒ the two halves sum to ``≤ full``). A cut, or a
    page with no successor, contributes ``0``.
    """
    out: list[float] = []
    for i, tr in enumerate(transitions):
        if not tr.is_animated or i + 1 >= len(page_fulls):
            out.append(0.0)
            continue
        avail = min(page_fulls[i], page_fulls[i + 1])
        d = min(tr.seconds, avail)
        if d < tr.seconds:
            logger.warning(
                "transition '%s' (%.2fs) is longer than the shorter adjacent slide "
                "(%.2fs); clamped to %.2fs — shorten it or lengthen a slide",
                tr.kind,
                tr.seconds,
                avail,
                d,
            )
        out.append(d)
    return out


def compose_video(
    timeline: DeckTimeline,
    page_images: list[Path],
    output: Path,
    *,
    config: Config,
    page_audios: list[Path] | None,
    render_dir: Path,
    transitions: list[Transition] | None = None,
    audio_track: Path | None = None,
) -> Path:
    """Compose page images into the final MP4, with centered-overlay transitions.

    *transitions* (when given) holds the boundary transition between page ``i``
    and ``i+1`` at index ``i`` (length ``len(pages) - 1``). An animated
    transition of ``D`` seconds is a *visual overlay centered on the boundary*:
    page ``i``'s segment is trimmed by ``D/2`` at its end, page ``i+1``'s by
    ``D/2`` at its start, and a ``D``-second morph clip is spliced between them.
    The whole video is assembled silent and *audio_track* (the single continuous
    deck track) is muxed over it at the end, so the morph plays over whatever
    audio sits at the boundary — silence or speech — and the deck's total
    duration is unchanged. With no transitions the segments concatenate
    back-to-back exactly as before. *audio_track* is required to carry sound;
    without it (or for a silent render where *page_audios* is None) the result is
    a silent video.
    """
    # Lazy module-qualified import so tests can patch get_duration at source.
    from slidesonnet.video import composer

    v = config.video
    seg_dir = render_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    boundaries = transitions or []
    n = len(timeline.pages)

    # Real on-screen length of each page: the synthesized audio when audible,
    # else the timing model. The morph geometry and the muxed track both align
    # to these, so the centered overlay never shifts the timeline.
    fulls = [
        page.duration if page_audios is None else composer.get_duration(page_audios[i])
        for i, page in enumerate(timeline.pages)
    ]
    morph = transition_morph_seconds(
        [*boundaries] + [Transition()] * (n - 1 - len(boundaries)), fulls
    )
    xnames = [
        transitions_mod.xfade_name(boundaries[i].kind)
        if i < len(boundaries) and boundaries[i].is_animated and morph[i] > 0
        else None
        for i in range(n - 1)
    ]

    pieces: list[Path] = []
    for i, page in enumerate(timeline.pages):
        s_i = morph[i - 1] / 2 if i > 0 else 0.0  # trimmed at the start by the incoming morph
        e_i = morph[i] / 2 if i < n - 1 else 0.0  # trimmed at the end by the outgoing morph
        seg_duration = max(0.1, fulls[i] - s_i - e_i)
        seg = seg_dir / f"seg-{i + 1:04d}.mp4"
        compose_silent_segment(
            page_images[i],
            seg,
            duration=seg_duration,
            resolution=v.resolution,
            fps=v.fps,
            crf=v.crf,
            preset=v.preset,
        )
        pieces.append(seg)
        xname = xnames[i] if i < n - 1 else None
        if xname is not None:
            tclip = seg_dir / f"trans-{i + 1:04d}.mp4"
            composer.compose_transition_clip(
                page_images[i],
                page_images[i + 1],
                tclip,
                duration=morph[i],
                transition=xname,
                resolution=v.resolution,
                fps=v.fps,
                crf=v.crf,
                preset=v.preset,
            )
            pieces.append(tclip)

    output.parent.mkdir(parents=True, exist_ok=True)
    if page_audios is None or audio_track is None:
        concatenate_segments(pieces, output)
    else:
        silent_video = render_dir / "silent.mp4"
        concatenate_segments(pieces, silent_video)
        composer.mux_audio(silent_video, audio_track, output)
    return output
