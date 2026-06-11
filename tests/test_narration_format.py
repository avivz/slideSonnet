"""Tests for the narration sidecar parser/serializer (structured block grammar)."""

from __future__ import annotations

import pytest

from slidesonnet.narration.format import (
    SidecarError,
    parse_segments,
    parse_sidecar,
    serialize_block,
    serialize_sidecar,
)
from slidesonnet.narration.model import PageNarration, Segment, Transition

SAMPLE = """\
# slideSonnet narration   deck: lecture.pdf

@intro-title
  transition-in: crossfade 0.5
  utterance:
    text: Welcome to the course on the Basel problem.
  pause: 1.5
  utterance:
    text: Today we'll see how Euler summed the reciprocals of the squares.

@intro-overview
  pause: 3            # silent slide — hold 3s while they read the outline

@euler-setup
  utterance:
    voice: narrator
    text: Here is the setup. We want the sum of one over n squared.
  pause: 0.8

@euler-trick
  utterance:
    pace: slow
    direct: deliberate, emphatic
    text: Watch the denominators carefully.
  transition-out: crossfade 0.3
"""


def test_parse_block_count_and_ids() -> None:
    blocks = parse_sidecar(SAMPLE)
    assert [b.slide_id for b in blocks] == [
        "intro-title",
        "intro-overview",
        "euler-setup",
        "euler-trick",
    ]


def test_parse_utterances_and_pauses() -> None:
    intro = parse_sidecar(SAMPLE)[0]
    assert intro.segments[0] == Segment.speech("Welcome to the course on the Basel problem.")
    assert intro.segments[1] == Segment.pause(1.5)
    assert intro.segments[2].kind == "speech"
    assert "Euler" in intro.segments[2].text


def test_parse_per_utterance_attributes() -> None:
    blocks = parse_sidecar(SAMPLE)
    assert blocks[2].segments[0].voice == "narrator"
    trick = blocks[3].segments[0]
    assert trick.pace == "slow"
    assert trick.direction == "deliberate, emphatic"


def test_parse_transitions() -> None:
    blocks = parse_sidecar(SAMPLE)
    assert blocks[0].transition_in == Transition("crossfade", 0.5)
    assert blocks[0].transition_out == Transition("cut", 0.0)  # default
    assert blocks[3].transition_out == Transition("crossfade", 0.3)


def test_silent_slide_is_pause_only() -> None:
    overview = parse_sidecar(SAMPLE)[1]
    assert overview.is_silent
    assert overview.segments == [Segment.pause(3)]
    assert overview.total_pause_seconds == 3


def test_inline_comment_stripped() -> None:
    overview = parse_sidecar(SAMPLE)[1]
    assert overview.segments == [Segment.pause(3)]  # trailing comment gone


def test_round_trip_stable() -> None:
    blocks = parse_sidecar(SAMPLE)
    once = serialize_sidecar(blocks)
    twice = serialize_sidecar(parse_sidecar(once))
    assert once == twice


def test_round_trip_preserves_model() -> None:
    blocks = parse_sidecar(SAMPLE)
    reparsed = parse_sidecar(serialize_sidecar(blocks))
    assert reparsed == blocks


def test_default_transitions_not_serialized() -> None:
    block = PageNarration(slide_id="x", segments=[Segment.speech("Hi.")])
    assert serialize_block(block) == "@x\n  utterance:\n    text: Hi."


def test_serialize_full_utterance_order() -> None:
    block = PageNarration(
        slide_id="x",
        segments=[Segment.speech("Hi.", voice="narrator", pace="slow", direction="warm")],
        transition_in=Transition("crossfade", 0.4),
    )
    assert serialize_block(block) == (
        "@x\n"
        "  transition-in: crossfade 0.4\n"
        "  utterance:\n"
        "    voice: narrator\n"
        "    pace: slow\n"
        "    direct: warm\n"
        "    text: Hi."
    )


def test_serialize_silent_block() -> None:
    block = PageNarration(slide_id="hold", segments=[Segment.pause(2.5)])
    assert serialize_block(block) == "@hold\n  pause: 2.5"


def test_serialize_empty_block() -> None:
    assert serialize_block(PageNarration(slide_id="blank")) == "@blank"


def test_text_with_colon_survives() -> None:
    block = parse_sidecar("@a\n  utterance:\n    text: The ratio is 2:1, precisely.\n")[0]
    assert block.segments[0].text == "The ratio is 2:1, precisely."


# ---- error paths -----------------------------------------------------------


def test_content_before_header_errors() -> None:
    with pytest.raises(SidecarError):
        parse_sidecar("  utterance:\n    text: hi\n@a\n")


def test_attribute_outside_utterance_errors() -> None:
    with pytest.raises(SidecarError, match="outside an 'utterance:'"):
        parse_sidecar("@a\n  voice: narrator\n")


def test_invalid_pace_errors() -> None:
    with pytest.raises(SidecarError, match="invalid pace"):
        parse_sidecar("@a\n  utterance:\n    pace: turbo\n    text: hi\n")


def test_invalid_transition_errors() -> None:
    with pytest.raises(SidecarError, match="invalid transition"):
        parse_sidecar("@a\n  transition-in: dissolve\n")


def test_non_numeric_pause_errors() -> None:
    with pytest.raises(SidecarError, match="not a number"):
        parse_sidecar("@a\n  pause: soon\n")


def test_unknown_directive_errors() -> None:
    with pytest.raises(SidecarError, match="unknown directive"):
        parse_sidecar("@a\n  tempo: fast\n")


# ---- the plain-text editing helper (lossy) ---------------------------------


def test_parse_segments_basic() -> None:
    segs = parse_segments("Hello there. [pause 2] Goodbye.")
    assert segs == [
        Segment.speech("Hello there."),
        Segment.pause(2),
        Segment.speech("Goodbye."),
    ]


def test_parse_segments_collapses_whitespace() -> None:
    assert parse_segments("Hello    there\tworld") == [Segment.speech("Hello there world")]


def test_negative_pause_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Segment.pause(-0.5)


def test_negative_transition_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Transition("crossfade", -1.0)
