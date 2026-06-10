"""Tests for the narration sidecar parser/serializer."""

from __future__ import annotations

import pytest

from slidesonnet.narration.format import (
    SidecarError,
    parse_segments,
    parse_sidecar,
    serialize_block,
    serialize_sidecar,
)
from slidesonnet.narration.model import PageNarration, Segment

SAMPLE = """\
# slideSonnet narration v1   deck: lecture.pdf

@intro-title
Welcome to the course on the Basel problem. [pause 1.5]
Today we'll see how Euler summed the reciprocals of the squares.

@intro-overview
[pause 3]            # silent slide — hold 3s while they read the outline

@euler-setup
:voice narrator
Here is the setup. We want the sum of one over n squared. [pause 0.8]

@euler-trick
:pace slow
Watch the denominators carefully. [pause 1] This is the whole trick.
"""


def test_parse_block_count_and_ids() -> None:
    blocks = parse_sidecar(SAMPLE)
    assert [b.slide_id for b in blocks] == [
        "intro-title",
        "intro-overview",
        "euler-setup",
        "euler-trick",
    ]


def test_parse_inline_pause_splits_speech() -> None:
    blocks = parse_sidecar(SAMPLE)
    intro = blocks[0]
    assert intro.segments[0] == Segment.speech("Welcome to the course on the Basel problem.")
    assert intro.segments[1] == Segment.pause(1.5)
    assert intro.segments[2].kind == "speech"
    assert "Euler" in intro.segments[2].text


def test_silent_slide_is_pause_only() -> None:
    blocks = parse_sidecar(SAMPLE)
    overview = blocks[1]
    assert overview.is_silent
    assert overview.segments == [Segment.pause(3)]
    assert overview.total_pause_seconds == 3


def test_directives_parsed() -> None:
    blocks = parse_sidecar(SAMPLE)
    assert blocks[2].voice == "narrator"
    assert blocks[3].pace == "slow"


def test_inline_comment_stripped() -> None:
    blocks = parse_sidecar(SAMPLE)
    assert blocks[1].segments == [Segment.pause(3)]  # comment after [pause 3] gone


def test_round_trip_stable() -> None:
    blocks = parse_sidecar(SAMPLE)
    once = serialize_sidecar(blocks)
    twice = serialize_sidecar(parse_sidecar(once))
    assert once == twice


def test_round_trip_preserves_model() -> None:
    blocks = parse_sidecar(SAMPLE)
    reparsed = parse_sidecar(serialize_sidecar(blocks))
    assert reparsed == blocks


def test_parse_segments_basic() -> None:
    segs = parse_segments("Hello there. [pause 2] Goodbye.")
    assert segs == [
        Segment.speech("Hello there."),
        Segment.pause(2),
        Segment.speech("Goodbye."),
    ]


def test_whitespace_collapsed() -> None:
    segs = parse_segments("Hello    there\tworld")
    assert segs == [Segment.speech("Hello there world")]


def test_serialize_silent_block() -> None:
    block = PageNarration(slide_id="hold", segments=[Segment.pause(2.5)])
    assert serialize_block(block) == "@hold\n[pause 2.5]"


def test_serialize_empty_block() -> None:
    block = PageNarration(slide_id="blank")
    assert serialize_block(block) == "@blank"


def test_directive_before_header_errors() -> None:
    with pytest.raises(SidecarError):
        parse_sidecar(":voice narrator\n@a\nhi")


def test_text_before_header_errors() -> None:
    with pytest.raises(SidecarError):
        parse_sidecar("loose text\n@a\nhi")


def test_invalid_pace_errors() -> None:
    with pytest.raises(SidecarError):
        parse_sidecar("@a\n:pace turbo\nhi")


def test_pause_integer_formatting() -> None:
    block = PageNarration(slide_id="x", segments=[Segment.speech("Hi."), Segment.pause(1)])
    assert serialize_block(block) == "@x\nHi. [pause 1]"
