"""Tests for subtitle formatters and text splitting."""

from __future__ import annotations

from slidesonnet.subtitles import SubtitleEntry, format_srt, format_vtt, split_text


def test_split_short_text() -> None:
    assert split_text("Hello world.") == ["Hello world."]


def test_split_long_text_at_sentences() -> None:
    text = "First sentence here. Second sentence here. Third one closes it out nicely now."
    chunks = split_text(text, max_chars=40)
    assert len(chunks) >= 2
    assert all(len(c) <= 40 for c in chunks)


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


def test_empty_entries() -> None:
    assert format_srt([]) == ""
    assert format_vtt([]).strip() == "WEBVTT"
