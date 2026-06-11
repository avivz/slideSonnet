"""Tests for subtitle formatters and text splitting."""

from __future__ import annotations

from slidesonnet.subtitles import (
    SubtitleEntry,
    _split_long_sentence,
    format_srt,
    format_vtt,
    split_text,
)


def test_split_short_text() -> None:
    assert split_text("Hello world.") == ["Hello world."]


def test_split_empty_and_whitespace() -> None:
    assert split_text("") == []
    assert split_text("   \n\t ") == []


def test_split_long_text_at_sentences() -> None:
    text = "First sentence here. Second sentence here. Third one closes it out nicely now."
    chunks = split_text(text, max_chars=40)
    assert len(chunks) >= 2
    assert all(len(c) <= 40 for c in chunks)


def test_split_combines_short_sentences_until_limit() -> None:
    text = "Aa bb. Cc dd. This trailing sentence definitely exceeds twenty characters."
    chunks = split_text(text, max_chars=20)
    # The two short sentences fit together in one cue; the long one is split off.
    assert chunks[0] == "Aa bb. Cc dd."
    assert all(len(c) <= 20 for c in chunks)
    assert " ".join(chunks) == text


def test_split_single_long_sentence_at_clauses() -> None:
    text = "alpha beta gamma delta, epsilon zeta eta theta, iota kappa lambda mu"
    chunks = split_text(text, max_chars=30)
    assert len(chunks) >= 2
    assert all(len(c) <= 30 for c in chunks)
    assert " ".join(chunks) == text


def test_split_combines_short_clauses_until_limit() -> None:
    text = "aa bb, cc dd, ee ff gg hh ii jj"
    chunks = split_text(text, max_chars=20)
    # The first two clauses share a cue; the third overflows into its own.
    assert chunks == ["aa bb, cc dd,", "ee ff gg hh ii jj"]


def test_split_long_sentence_without_clauses_uses_midpoint() -> None:
    text = ("word " * 40).strip()  # 199 chars, no punctuation at all
    chunks = split_text(text, max_chars=60)
    assert len(chunks) >= 4
    assert all(len(c) <= 60 for c in chunks)
    assert " ".join(chunks) == text


def test_split_falls_back_to_midpoint_when_clause_chunk_too_long() -> None:
    text = "x" * 45 + ", tail part"
    chunks = split_text(text, max_chars=40)
    # The clause before the comma is an unbreakable 46-char run, so the clause
    # split is rejected and the midpoint pass keeps it whole.
    assert chunks == ["x" * 45 + ",", "tail part"]


def test_split_midpoint_searches_backwards_for_space() -> None:
    text = "aa " + "b" * 90  # only space is well before the midpoint
    chunks = split_text(text, max_chars=80)
    assert chunks == ["aa", "b" * 90]


def test_split_unbreakable_token_returned_whole() -> None:
    word = "x" * 120  # no spaces anywhere: cannot be split, exceeds the limit
    assert split_text(word, max_chars=80) == [word]


def test_split_long_sentence_blank_input() -> None:
    assert _split_long_sentence("   ", 10) == []


def test_format_srt() -> None:
    entries = [
        SubtitleEntry(1, 0.0, 1.5, "Hello."),
        SubtitleEntry(2, 1.5, 3.0, "World."),
    ]
    srt = format_srt(entries)
    assert "1\n00:00:00,000 --> 00:00:01,500\nHello." in srt
    assert "2\n00:00:01,500 --> 00:00:03,000\nWorld." in srt


def test_format_srt_renumbers() -> None:
    entries = [SubtitleEntry(99, 0.0, 1.0, "Hi.")]
    assert format_srt(entries).startswith("1\n")


def test_format_vtt() -> None:
    entries = [SubtitleEntry(1, 0.0, 1.5, "Hello.")]
    vtt = format_vtt(entries)
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.500\nHello." in vtt


def test_negative_timestamp_clamped_to_zero() -> None:
    srt = format_srt([SubtitleEntry(1, -0.5, 1.0, "early")])
    assert "00:00:00,000 --> 00:00:01,000" in srt


def test_timestamp_hours_and_millis() -> None:
    vtt = format_vtt([SubtitleEntry(1, 3661.25, 3662.0, "late")])
    assert "01:01:01.250 --> 01:01:02.000" in vtt


def test_empty_entries() -> None:
    assert format_srt([]) == ""
    assert format_vtt([]).strip() == "WEBVTT"
