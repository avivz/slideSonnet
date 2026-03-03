"""Tests for SRT subtitle generation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.models import (
    ModuleType,
    PlaylistEntry,
    ProjectConfig,
    SlideAnnotation,
    SlideNarration,
    TTSConfig,
    VideoConfig,
)
from slidesonnet.subtitles import (
    SubtitleEntry,
    _format_srt_time,
    _split_sentences,
    format_srt,
    generate_subtitles,
    split_text,
)


# ---- _split_sentences() tests ----


class TestSplitSentences:
    def test_basic(self) -> None:
        result = _split_sentences("Hello world. How are you?")
        assert result == ["Hello world.", "How are you?"]

    def test_multiple_punctuation(self) -> None:
        result = _split_sentences("Wow! Really? Yes.")
        assert result == ["Wow!", "Really?", "Yes."]

    def test_single_sentence(self) -> None:
        result = _split_sentences("Just one sentence.")
        assert result == ["Just one sentence."]

    def test_empty(self) -> None:
        result = _split_sentences("")
        assert result == []

    def test_no_punctuation(self) -> None:
        result = _split_sentences("No ending punctuation here")
        assert result == ["No ending punctuation here"]


# ---- split_text() tests ----


class TestSplitText:
    def test_short_no_split(self) -> None:
        text = "Short text."
        result = split_text(text, max_chars=80)
        assert result == ["Short text."]

    def test_empty(self) -> None:
        assert split_text("") == []
        assert split_text("   ") == []

    def test_multi_sentence_grouping(self) -> None:
        text = "First sentence. Second sentence. Third sentence is a bit longer than before."
        result = split_text(text, max_chars=50)
        # Should group sentences that fit within max_chars
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 50

    def test_long_sentence_clause_split(self) -> None:
        text = "This is a very long sentence, with a clause break, and another clause here."
        result = split_text(text, max_chars=40)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 40

    def test_long_sentence_word_split(self) -> None:
        # No punctuation to split on — forces word-boundary split
        text = "This is a very long sentence without any punctuation marks to help splitting"
        result = split_text(text, max_chars=40)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 40

    def test_all_chunks_within_limit(self) -> None:
        text = (
            "The quick brown fox jumps over the lazy dog. "
            "Meanwhile, the cat sat on the mat. "
            "Everything was peaceful in the garden."
        )
        result = split_text(text, max_chars=60)
        for chunk in result:
            assert len(chunk) <= 60

    def test_exact_limit(self) -> None:
        text = "A" * 80
        result = split_text(text, max_chars=80)
        assert result == [text]


# ---- _format_srt_time() tests ----


class TestFormatSrtTime:
    def test_zero(self) -> None:
        assert _format_srt_time(0) == "00:00:00,000"

    def test_seconds(self) -> None:
        assert _format_srt_time(5.0) == "00:00:05,000"

    def test_minutes(self) -> None:
        assert _format_srt_time(125.0) == "00:02:05,000"

    def test_hours(self) -> None:
        assert _format_srt_time(3661.0) == "01:01:01,000"

    def test_milliseconds(self) -> None:
        assert _format_srt_time(1.5) == "00:00:01,500"

    def test_negative_clamps_to_zero(self) -> None:
        assert _format_srt_time(-1.0) == "00:00:00,000"

    def test_fractional(self) -> None:
        assert _format_srt_time(0.123) == "00:00:00,123"


# ---- format_srt() tests ----


class TestFormatSrt:
    def test_single_entry(self) -> None:
        entries = [SubtitleEntry(index=1, start=0.0, end=2.5, text="Hello world.")]
        result = format_srt(entries)
        assert "1\n" in result
        assert "00:00:00,000 --> 00:00:02,500" in result
        assert "Hello world." in result

    def test_multiple_entries(self) -> None:
        entries = [
            SubtitleEntry(index=1, start=0.0, end=2.0, text="First."),
            SubtitleEntry(index=2, start=3.0, end=5.0, text="Second."),
        ]
        result = format_srt(entries)
        assert "1\n" in result
        assert "2\n" in result
        assert "First." in result
        assert "Second." in result

    def test_srt_structure(self) -> None:
        entries = [
            SubtitleEntry(index=1, start=1.0, end=3.0, text="Line one."),
            SubtitleEntry(index=2, start=4.0, end=6.0, text="Line two."),
        ]
        result = format_srt(entries)
        blocks = result.strip().split("\n\n")
        assert len(blocks) == 2
        # Each block: index, timestamp, text
        for block in blocks:
            lines = block.strip().split("\n")
            assert len(lines) == 3

    def test_empty(self) -> None:
        assert format_srt([]) == ""


# ---- generate_subtitles() tests ----


def _make_config(
    pre_silence: float = 1.0,
    pad_seconds: float = 1.5,
    crossfade: float = 0.5,
    silence_duration: float = 3.0,
) -> ProjectConfig:
    return ProjectConfig(
        tts=TTSConfig(backend="piper"),
        video=VideoConfig(
            pre_silence=pre_silence,
            pad_seconds=pad_seconds,
            crossfade=crossfade,
            silence_duration=silence_duration,
        ),
    )


def _make_slide(
    index: int,
    annotation: SlideAnnotation = SlideAnnotation.SAY,
    narration_raw: str = "Hello.",
    silence_override: float | None = None,
    voice: str | None = None,
) -> SlideNarration:
    slide = SlideNarration(
        index=index,
        annotation=annotation,
        narration_raw=narration_raw,
        narration_processed=narration_raw,
        narration_parts=[narration_raw] if annotation == SlideAnnotation.SAY else [],
        narration_parts_processed=[narration_raw] if annotation == SlideAnnotation.SAY else [],
        silence_override=silence_override,
        voice=voice,
    )
    return slide


def _make_tts() -> MagicMock:
    tts = MagicMock()
    tts.name.return_value = "piper"
    tts.cache_key.return_value = "test_key"
    return tts


class TestGenerateSubtitles:
    def test_single_narrated_slide(self, tmp_path: Path) -> None:
        """A single narrated slide produces one subtitle entry."""
        config = _make_config(pre_silence=1.0, pad_seconds=1.5, crossfade=0.0)
        tts = _make_tts()
        entries = [PlaylistEntry(path=Path("slides.md"), module_type=ModuleType.MARP)]

        slides = [_make_slide(1, narration_raw="Welcome to the lecture.")]

        build_dir = tmp_path / "cache"
        audio_dir = build_dir / "audio"
        audio_dir.mkdir(parents=True)

        # Create a fake audio file
        fake_audio = audio_dir / "fake.wav"
        fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

        with (
            patch("slidesonnet.subtitles.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.subtitles.get_duration", return_value=3.0),
            patch("slidesonnet.subtitles._find_audio_path", return_value=fake_audio),
        ):
            mock_parser = MagicMock()
            mock_parser.parse.return_value = slides
            mock_gpe.return_value = (lambda: mock_parser, None)
            (tmp_path / "slides.md").touch()

            result = generate_subtitles(entries, config, tts, build_dir, tmp_path)

        assert len(result) == 1
        assert result[0].text == "Welcome to the lecture."
        # start = 0 + pre_silence = 1.0
        assert result[0].start == pytest.approx(1.0)
        # end = 0 + pre_silence + audio_duration = 1.0 + 3.0 = 4.0
        assert result[0].end == pytest.approx(4.0)

    def test_timing_with_crossfade(self, tmp_path: Path) -> None:
        """Two narrated slides: second subtitle offset accounts for crossfade."""
        config = _make_config(pre_silence=1.0, pad_seconds=1.5, crossfade=0.5)
        tts = _make_tts()
        entries = [PlaylistEntry(path=Path("slides.md"), module_type=ModuleType.MARP)]

        slides = [
            _make_slide(1, narration_raw="First slide."),
            _make_slide(2, narration_raw="Second slide."),
        ]

        build_dir = tmp_path / "cache"
        audio_dir = build_dir / "audio"
        audio_dir.mkdir(parents=True)
        fake_audio = audio_dir / "fake.wav"
        fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

        with (
            patch("slidesonnet.subtitles.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.subtitles.get_duration", return_value=2.0),
            patch("slidesonnet.subtitles._find_audio_path", return_value=fake_audio),
        ):
            mock_parser = MagicMock()
            mock_parser.parse.return_value = slides
            mock_gpe.return_value = (lambda: mock_parser, None)
            (tmp_path / "slides.md").touch()

            result = generate_subtitles(entries, config, tts, build_dir, tmp_path)

        assert len(result) == 2
        # Slide 1: offset=0, start=0+1.0=1.0, end=1.0+2.0=3.0
        assert result[0].start == pytest.approx(1.0)
        assert result[0].end == pytest.approx(3.0)
        # Slide 1 duration = 1.0+2.0+1.5 = 4.5
        # Slide 2 offset = 4.5 - 0.5 = 4.0, start=4.0+1.0=5.0, end=5.0+2.0=7.0
        assert result[1].start == pytest.approx(5.0)
        assert result[1].end == pytest.approx(7.0)

    def test_silent_slides_no_subtitle(self, tmp_path: Path) -> None:
        """Silent slides advance offset but produce no subtitle."""
        config = _make_config(pre_silence=1.0, pad_seconds=1.5, crossfade=0.0, silence_duration=3.0)
        tts = _make_tts()
        entries = [PlaylistEntry(path=Path("slides.md"), module_type=ModuleType.MARP)]

        slides = [
            _make_slide(1, annotation=SlideAnnotation.SILENT, narration_raw=""),
            _make_slide(2, narration_raw="After silence."),
        ]

        build_dir = tmp_path / "cache"
        audio_dir = build_dir / "audio"
        audio_dir.mkdir(parents=True)
        fake_audio = audio_dir / "fake.wav"
        fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

        with (
            patch("slidesonnet.subtitles.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.subtitles.get_duration", return_value=2.0),
            patch("slidesonnet.subtitles._find_audio_path", return_value=fake_audio),
        ):
            mock_parser = MagicMock()
            mock_parser.parse.return_value = slides
            mock_gpe.return_value = (lambda: mock_parser, None)
            (tmp_path / "slides.md").touch()

            result = generate_subtitles(entries, config, tts, build_dir, tmp_path)

        assert len(result) == 1
        assert result[0].text == "After silence."
        # Silent slide duration = 3.0, no crossfade for first
        # Slide 2 offset = 3.0 - 0.0 = 3.0 (crossfade=0)
        # start = 3.0 + 1.0 = 4.0
        assert result[0].start == pytest.approx(4.0)

    def test_uses_narration_raw(self, tmp_path: Path) -> None:
        """Subtitles use narration_raw, not pronunciation-substituted text."""
        config = _make_config(crossfade=0.0)
        tts = _make_tts()
        entries = [PlaylistEntry(path=Path("slides.md"), module_type=ModuleType.MARP)]

        slide = _make_slide(1, narration_raw="Dijkstra invented this.")
        # Simulate pronunciation substitution
        slide.narration_processed = "DYKE-struh invented this."

        build_dir = tmp_path / "cache"
        audio_dir = build_dir / "audio"
        audio_dir.mkdir(parents=True)
        fake_audio = audio_dir / "fake.wav"
        fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

        with (
            patch("slidesonnet.subtitles.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.subtitles.get_duration", return_value=2.0),
            patch("slidesonnet.subtitles._find_audio_path", return_value=fake_audio),
        ):
            mock_parser = MagicMock()
            mock_parser.parse.return_value = [slide]
            mock_gpe.return_value = (lambda: mock_parser, None)
            (tmp_path / "slides.md").touch()

            result = generate_subtitles(entries, config, tts, build_dir, tmp_path)

        assert len(result) == 1
        assert result[0].text == "Dijkstra invented this."
        assert "DYKE-struh" not in result[0].text

    def test_skip_slides_no_offset(self, tmp_path: Path) -> None:
        """Skipped slides produce no subtitle and no offset."""
        config = _make_config(crossfade=0.0)
        tts = _make_tts()
        entries = [PlaylistEntry(path=Path("slides.md"), module_type=ModuleType.MARP)]

        slides = [
            _make_slide(1, annotation=SlideAnnotation.SKIP, narration_raw=""),
            _make_slide(2, narration_raw="First visible."),
        ]

        build_dir = tmp_path / "cache"
        audio_dir = build_dir / "audio"
        audio_dir.mkdir(parents=True)
        fake_audio = audio_dir / "fake.wav"
        fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

        with (
            patch("slidesonnet.subtitles.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.subtitles.get_duration", return_value=2.0),
            patch("slidesonnet.subtitles._find_audio_path", return_value=fake_audio),
        ):
            mock_parser = MagicMock()
            mock_parser.parse.return_value = slides
            mock_gpe.return_value = (lambda: mock_parser, None)
            (tmp_path / "slides.md").touch()

            result = generate_subtitles(entries, config, tts, build_dir, tmp_path)

        assert len(result) == 1
        assert result[0].text == "First visible."
        # Skip slide produces no offset, so start = 0 + pre_silence
        assert result[0].start == pytest.approx(1.0)
