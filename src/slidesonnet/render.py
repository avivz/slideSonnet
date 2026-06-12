"""Render orchestration: deck timeline, subtitles, audio track, and video.

Ties the pure timing model to synthesized audio, the FFmpeg composer, and the
subtitle writers. The deck timeline is the single source of truth shared by the
exported video, the preview cue sheet, and the subtitles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from slidesonnet.audio.track import Cue, assemble_track, build_page_audio, cue_sheet
from slidesonnet.config import Config
from slidesonnet.models import VideoConfig
from slidesonnet.narration.model import Deck, PageNarration, Segment
from slidesonnet.subtitles import SubtitleEntry, split_text
from slidesonnet.timing import PageTiming, TimingMode, compute_page_timing
from slidesonnet.video.composer import (
    compose_segment,
    compose_silent_segment,
    concatenate_segments,
)

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
        pages.append(
            compute_page_timing(
                block,
                mode,
                speech_durations=sd,
                lead=video.pre_silence,
                tail=video.tail_seconds,
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


def render_audio_track(
    timeline: DeckTimeline,
    page_clips: list[list[Path]],
    *,
    render_dir: Path,
) -> tuple[Path, list[Path]]:
    """Build per-page audio (lead+segments+tail) and the assembled deck track.

    Returns ``(track_path, page_audio_paths)``.
    """
    render_dir.mkdir(parents=True, exist_ok=True)
    silence_dir = render_dir / "silence"
    silence_dir.mkdir(parents=True, exist_ok=True)
    page_audios: list[Path] = []
    for i, page in enumerate(timeline.pages):
        out = render_dir / f"page-{i + 1:04d}.wav"
        build_page_audio(page, page_clips[i], out, silence_dir=silence_dir)
        page_audios.append(out)
    track = render_dir / "track.wav"
    assemble_track(page_audios, track)
    return track, page_audios


def compose_video(
    timeline: DeckTimeline,
    page_images: list[Path],
    output: Path,
    *,
    config: Config,
    page_audios: list[Path] | None,
    render_dir: Path,
) -> Path:
    """Compose page images + per-page audio (or silence) into the final MP4."""
    # Lazy module-qualified import so tests can patch get_duration at source.
    from slidesonnet.video import composer

    v = config.video
    seg_dir = render_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []
    for i, page in enumerate(timeline.pages):
        seg = seg_dir / f"seg-{i + 1:04d}.mp4"
        if page_audios is None:
            compose_silent_segment(
                page_images[i],
                seg,
                duration=page.duration,
                resolution=v.resolution,
                fps=v.fps,
                crf=v.crf,
                preset=v.preset,
            )
        else:
            compose_segment(
                page_images[i],
                page_audios[i],
                seg,
                duration=composer.get_duration(page_audios[i]),
                resolution=v.resolution,
                fps=v.fps,
                crf=v.crf,
                preset=v.preset,
            )
        segments.append(seg)
    output.parent.mkdir(parents=True, exist_ok=True)
    concatenate_segments(segments, output)
    return output
