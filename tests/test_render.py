"""Unit tests for the render timeline and subtitle cue construction (no ffmpeg)."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.models import VideoConfig
from slidesonnet.narration.model import Deck, PageNarration, Segment
from slidesonnet.render import build_timeline, subtitle_entries
from slidesonnet.timing import TimingMode


def _deck() -> Deck:
    narration = {
        "a": PageNarration("a", [Segment.speech("one two three")]),
        "b": PageNarration("b", [Segment.pause(2.0)]),
        "c": PageNarration("c", [Segment.speech("four"), Segment.pause(1.0)]),
    }
    return Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b", "c", "d"],  # 'd' un-narrated
        narration=narration,
    )


_VIDEO = VideoConfig(pre_silence=0.3, tail_seconds=0.5)
_MODE = TimingMode("estimate", wpm=60)  # 1 word/sec


def test_page_durations() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    # a: 0.3 + 3 + 0.5; b: 0.3 + 2 + 0.5; c: 0.3 + (1+1) + 0.5; d: 0.3 + 2.5 + 0.5
    assert tl.page_durations == pytest.approx([3.8, 2.8, 2.8, 3.3])


def test_page_starts_and_total() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    assert tl.page_starts == pytest.approx([0.0, 3.8, 6.6, 9.4])
    assert tl.total_duration == pytest.approx(12.7)


def test_cue_sheet() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    cues = tl.cue_sheet()
    assert [c[1] for c in cues] == ["a", "b", "c", "d"]
    assert cues[2][0] == pytest.approx(6.6)


def test_subtitles_segment_granularity() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    entries = subtitle_entries(_deck(), tl, granularity="segment")
    texts = [e.text for e in entries]
    assert texts == ["one two three", "four"]
    assert entries[0].start == pytest.approx(0.3)
    assert entries[1].start == pytest.approx(6.9)  # 6.6 + lead 0.3


def test_subtitles_slide_granularity() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    entries = subtitle_entries(_deck(), tl, granularity="slide")
    assert [e.text for e in entries] == ["one two three", "four"]


def test_tts_timeline_uses_supplied_durations() -> None:
    deck = _deck()
    # one speech segment on page a, one on page c
    durations = [[1.5], [], [2.0], []]
    tl = build_timeline(
        deck, TimingMode("tts"), video=_VIDEO, speech_durations_by_page=durations, default_hold=2.5
    )
    assert tl.page_durations[0] == pytest.approx(0.3 + 1.5 + 0.5)
    assert tl.page_durations[2] == pytest.approx(0.3 + 2.0 + 1.0 + 0.5)
