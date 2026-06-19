"""Tests for the narration sidecar parser/serializer (structured block grammar)."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.models import VoiceConfig
from slidesonnet.narration.format import (
    SidecarError,
    parse_document,
    parse_segments,
    parse_sidecar,
    serialize_block,
    serialize_preamble,
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
        parse_sidecar("@a\n  transition-in: teleport\n")


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


class TestFormatVersionHeader:
    def test_current_version_parses_silently(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        from slidesonnet.narration.format import FORMAT_VERSION

        text = f"# slidesonnet-format: {FORMAT_VERSION}\n@a\n  utterance:\n    text: Hi.\n"
        with caplog.at_level(logging.WARNING):
            blocks = parse_sidecar(text)
        assert blocks[0].slide_id == "a"
        assert "slidesonnet-format" not in caplog.text

    def test_future_version_warns_but_parses(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        text = "# slidesonnet-format: 99\n@a\n  utterance:\n    text: Hi.\n"
        with caplog.at_level(logging.WARNING):
            blocks = parse_sidecar(text)
        assert blocks[0].slide_id == "a"  # best-effort read, never a hard fail
        assert "slidesonnet-format" in caplog.text and "99" in caplog.text

    def test_scaffold_declares_format_version(self, tmp_path: Path) -> None:
        from slidesonnet.api import scaffold_text
        from slidesonnet.narration.format import FORMAT_VERSION

        text = scaffold_text(tmp_path / "deck.pdf", ["a", "b"])
        assert f"# slidesonnet-format: {FORMAT_VERSION}" in text
        parse_sidecar(text)  # and it round-trips through the parser


# ---- the deck-level voice preamble (portable voice layer, v2) ---------------

V2_SAMPLE = """\
# slidesonnet-format: 2
default-voice: lecturer
voices:
  lecturer:
    kokoro: am_michael
    qwen3: voice/lecturer.pt
    inworld: abc123
  guest:
    kokoro: af_bella

@intro
  utterance:
    voice: guest
    text: Hello from the guest.
  utterance:
    text: And back to the default voice.
"""


def test_parse_document_reads_voice_preamble() -> None:
    doc = parse_document(V2_SAMPLE)
    assert doc.default_voice == "lecturer"
    assert set(doc.voices) == {"lecturer", "guest"}
    assert doc.voices["lecturer"].backend_voices == {
        "kokoro": "am_michael",
        "qwen3": "voice/lecturer.pt",
        "inworld": "abc123",
    }
    assert doc.voices["guest"].backend_voices == {"kokoro": "af_bella"}
    # the blocks still parse, and an utterance names an internal voice
    assert [b.slide_id for b in doc.blocks] == ["intro"]
    assert doc.blocks[0].speech_segments[0].voice == "guest"


def test_parse_sidecar_ignores_preamble() -> None:
    # back-compat: the list-only entry point still returns just the blocks
    blocks = parse_sidecar(V2_SAMPLE)
    assert [b.slide_id for b in blocks] == ["intro"]


def test_v2_document_round_trips_byte_stable() -> None:
    doc = parse_document(V2_SAMPLE)
    out = serialize_sidecar(
        doc.blocks,
        voices=doc.voices,
        default_voice=doc.default_voice,
        preamble_source=doc.preamble_source,
    )
    assert out == V2_SAMPLE


def test_v1_file_has_no_preamble_and_is_unchanged() -> None:
    doc = parse_document(SAMPLE)
    assert doc.voices == {}
    assert doc.default_voice is None
    assert doc.preamble_source is None
    # serializing a v1 deck adds no format header / preamble
    assert serialize_sidecar(doc.blocks) == serialize_sidecar(doc.blocks, voices={})


def test_serialize_preamble_canonical_form() -> None:
    voices = {"narrator": VoiceConfig(name="narrator", backend_voices={"kokoro": "af_heart"})}
    text = serialize_preamble(voices, "narrator")
    assert text == (
        "# slidesonnet-format: 2\n"
        "default-voice: narrator\n"
        "voices:\n"
        "  narrator:\n"
        "    kokoro: af_heart"
    )
    assert serialize_preamble({}, None) == ""


def test_serialize_sidecar_regenerates_canonical_preamble() -> None:
    # no preamble_source => the preamble is regenerated canonically
    voices = {"narrator": VoiceConfig(name="narrator", backend_voices={"kokoro": "af_heart"})}
    blocks = [PageNarration(slide_id="a", segments=[Segment.speech("Hi.")])]
    out = serialize_sidecar(blocks, voices=voices, default_voice="narrator")
    assert out == (
        "# slidesonnet-format: 2\n"
        "default-voice: narrator\n"
        "voices:\n"
        "  narrator:\n"
        "    kokoro: af_heart\n"
        "\n"
        "@a\n  utterance:\n    text: Hi.\n"
    )


def test_default_voice_without_voices_block() -> None:
    doc = parse_document("default-voice: lecturer\n\n@a\n  utterance:\n    text: Hi.\n")
    assert doc.default_voice == "lecturer"
    assert doc.voices == {}


def test_voices_with_value_errors() -> None:
    with pytest.raises(SidecarError, match="takes no value"):
        parse_document("voices: oops\n@a\n  utterance:\n    text: Hi.\n")
