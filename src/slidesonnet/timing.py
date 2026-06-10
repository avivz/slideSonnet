"""Page-duration model: tts / estimate(wpm) / fixed.

A page's on-screen duration is the sum of its speech-segment durations plus its
explicit ``[pause N]`` seconds, with an optional lead-in and tail. Three modes
decide how long each *speech* segment lasts:

- ``tts``      real synthesized audio length (provided by the caller).
- ``estimate`` word count / WPM — a rough cut with no audio.
- ``fixed:N``  the page's speech is held N seconds total (pauses add on top).

The same timeline drives the preview cue sheet, the exported video, and the
subtitles, so what you preview is what you export.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from slidesonnet.narration.model import PageNarration, Segment

_DEFAULT_WPM = 150.0
_DEFAULT_FIXED = 5.0


@dataclass(frozen=True)
class TimingMode:
    """How to derive speech durations."""

    kind: str  # "tts" | "estimate" | "fixed"
    wpm: float = _DEFAULT_WPM
    fixed_seconds: float = _DEFAULT_FIXED

    def __post_init__(self) -> None:
        if self.kind not in {"tts", "estimate", "fixed"}:
            raise ValueError(f"unknown timing kind '{self.kind}'")
        if self.wpm <= 0:
            raise ValueError(f"wpm must be positive, got {self.wpm}")
        if self.fixed_seconds < 0:
            raise ValueError(f"fixed_seconds must be non-negative, got {self.fixed_seconds}")


def parse_timing(spec: str, *, wpm: float = _DEFAULT_WPM) -> TimingMode:
    """Parse a ``--timing`` spec: ``tts`` | ``estimate`` | ``fixed:N``."""
    spec = spec.strip()
    if spec in {"tts", "estimate"}:
        return TimingMode(kind=spec, wpm=wpm)
    m = re.fullmatch(r"fixed:([0-9]*\.?[0-9]+)", spec)
    if m:
        return TimingMode(kind="fixed", wpm=wpm, fixed_seconds=float(m.group(1)))
    raise ValueError(f"invalid timing spec '{spec}' (expected tts | estimate | fixed:N)")


def word_count(text: str) -> int:
    return len(text.split())


@dataclass(frozen=True)
class SegmentTiming:
    """A segment placed on the page timeline."""

    segment: Segment
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class PageTiming:
    """The full timeline for one page."""

    slide_id: str
    duration: float
    lead: float
    tail: float
    segments: list[SegmentTiming] = field(default_factory=list)

    @property
    def speech_timings(self) -> list[SegmentTiming]:
        return [s for s in self.segments if s.segment.is_speech]


def _estimate_speech_seconds(text: str, wpm: float) -> float:
    return word_count(text) / wpm * 60.0


def compute_page_timing(
    block: PageNarration,
    mode: TimingMode,
    *,
    speech_durations: list[float] | None = None,
    lead: float = 0.0,
    tail: float = 0.0,
) -> PageTiming:
    """Build the timeline for *block* under *mode*.

    *speech_durations* aligns to ``block.speech_segments`` order and is required
    for ``tts`` mode (real audio lengths). For ``estimate``/``fixed`` it is
    ignored.
    """
    speech_segs = block.speech_segments
    durations = _speech_durations(block, mode, speech_durations, speech_segs)

    timeline: list[SegmentTiming] = []
    t = lead
    speech_idx = 0
    for seg in block.segments:
        if seg.is_pause:
            dur = seg.seconds
        else:
            dur = durations[speech_idx]
            speech_idx += 1
        timeline.append(SegmentTiming(segment=seg, start=t, end=t + dur))
        t += dur

    return PageTiming(
        slide_id=block.slide_id,
        duration=t + tail,
        lead=lead,
        tail=tail,
        segments=timeline,
    )


def _speech_durations(
    block: PageNarration,
    mode: TimingMode,
    speech_durations: list[float] | None,
    speech_segs: list[Segment],
) -> list[float]:
    """Per-speech-segment durations, aligned to *speech_segs*."""
    if mode.kind == "tts":
        if speech_durations is None or len(speech_durations) != len(speech_segs):
            raise ValueError(
                "tts timing requires speech_durations aligned to the block's speech segments"
            )
        return list(speech_durations)

    if mode.kind == "estimate":
        return [_estimate_speech_seconds(s.text, mode.wpm) for s in speech_segs]

    # fixed: distribute fixed_seconds across speech segments by word proportion.
    if not speech_segs:
        return []
    words = [max(word_count(s.text), 1) for s in speech_segs]
    total = sum(words)
    return [mode.fixed_seconds * w / total for w in words]
