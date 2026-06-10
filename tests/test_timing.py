"""Tests for the page-duration timing model."""

from __future__ import annotations

import pytest

from slidesonnet.narration.model import PageNarration, Segment
from slidesonnet.timing import (
    TimingMode,
    compute_page_timing,
    parse_timing,
    word_count,
)


def test_parse_timing_modes() -> None:
    assert parse_timing("tts").kind == "tts"
    assert parse_timing("estimate").kind == "estimate"
    fixed = parse_timing("fixed:7.5")
    assert fixed.kind == "fixed" and fixed.fixed_seconds == 7.5


def test_parse_timing_invalid() -> None:
    with pytest.raises(ValueError):
        parse_timing("bogus")


def test_word_count() -> None:
    assert word_count("one two three") == 3
    assert word_count("") == 0


def _block() -> PageNarration:
    return PageNarration(
        slide_id="p",
        segments=[Segment.speech("a b c"), Segment.pause(2.0), Segment.speech("d e")],
    )


def test_tts_uses_supplied_durations() -> None:
    t = compute_page_timing(_block(), TimingMode("tts"), speech_durations=[3.0, 1.0], tail=0.5)
    assert t.duration == pytest.approx(3.0 + 2.0 + 1.0 + 0.5)
    assert [st.duration for st in t.speech_timings] == pytest.approx([3.0, 1.0])


def test_tts_requires_aligned_durations() -> None:
    with pytest.raises(ValueError):
        compute_page_timing(_block(), TimingMode("tts"), speech_durations=[3.0])


def test_estimate_from_wpm() -> None:
    mode = TimingMode("estimate", wpm=60)  # 1 word/sec
    t = compute_page_timing(_block(), mode)
    # 3 words + pause 2 + 2 words = 3 + 2 + 2 = 7s
    assert t.duration == pytest.approx(7.0)


def test_fixed_distributes_by_words() -> None:
    mode = TimingMode("fixed", fixed_seconds=10)
    t = compute_page_timing(_block(), mode)
    # 5 speech words total -> 3/5*10=6 and 2/5*10=4, + pause 2 = 12
    assert t.duration == pytest.approx(12.0)
    assert [st.duration for st in t.speech_timings] == pytest.approx([6.0, 4.0])


def test_lead_offsets_first_segment() -> None:
    t = compute_page_timing(_block(), TimingMode("estimate", wpm=60), lead=1.0)
    assert t.segments[0].start == pytest.approx(1.0)


def test_silent_page_fixed_is_pause_only() -> None:
    block = PageNarration(slide_id="s", segments=[Segment.pause(3.0)])
    t = compute_page_timing(block, TimingMode("fixed", fixed_seconds=5))
    assert t.duration == pytest.approx(3.0)  # no speech -> only the pause
