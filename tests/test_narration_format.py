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


# ---- raw round-trip preservation (non-destructive save) --------------------

MESSY = """\
# deck-wide notes: keep the tone warm
# (reviewed 2026-06-12)

@intro-title
  utterance:
    text: Welcome to the course
      on the Basel problem.
  pause: 1.5

# the overview slide stays silent on purpose
@intro-overview
  pause: 3   # hold while they read

@euler-setup
  utterance:
    voice: narrator
    text: Here is the setup.

# postscript: re-record euler-setup with more energy
"""


def test_unedited_roundtrip_is_byte_identical() -> None:
    assert serialize_sidecar(parse_sidecar(MESSY)) == MESSY


def test_wrapped_text_joins_continuation_lines() -> None:
    intro = parse_sidecar(MESSY)[0]
    assert intro.segments[0].text == "Welcome to the course on the Basel problem."


def test_edited_block_rewrites_only_itself() -> None:
    blocks = parse_sidecar(MESSY)
    blocks[1].segments = [Segment.pause(4)]
    out = serialize_sidecar(blocks)
    # the edited block is canonical now...
    assert "@intro-overview\n  pause: 4\n" in out
    # ...but its neighbours keep their raw text, wrapping included
    assert "    text: Welcome to the course\n      on the Basel problem.\n" in out
    assert "  pause: 3   # hold while they read" not in out


def test_comment_above_edited_block_survives() -> None:
    blocks = parse_sidecar(MESSY)
    blocks[1].segments = [Segment.pause(4)]
    out = serialize_sidecar(blocks)
    assert "# the overview slide stays silent on purpose\n@intro-overview\n" in out


def test_trailing_comment_survives_edit_of_last_block() -> None:
    blocks = parse_sidecar(MESSY)
    blocks[2].segments = [Segment.speech("Redone.", voice="narrator")]
    out = serialize_sidecar(blocks)
    assert "# postscript: re-record euler-setup with more energy\n" in out
    assert "    text: Redone.\n" in out


def test_reverted_edit_restores_raw_text() -> None:
    blocks = parse_sidecar(MESSY)
    original = blocks[1].segments
    blocks[1].segments = [Segment.pause(4)]
    blocks[1].segments = original
    assert serialize_sidecar(blocks) == MESSY


def test_directive_like_line_inside_text_is_continuation() -> None:
    block = parse_sidecar("@a\n  utterance:\n    text: First.\n    nb: second line\n")[0]
    assert block.segments[0].text == "First. nb: second line"


def test_fresh_blocks_still_serialize_canonically() -> None:
    blocks = [
        PageNarration(slide_id="a", segments=[Segment.speech("Hi.")]),
        PageNarration(slide_id="b", segments=[Segment.pause(1)]),
    ]
    assert serialize_sidecar(blocks) == "@a\n  utterance:\n    text: Hi.\n\n@b\n  pause: 1\n"


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
