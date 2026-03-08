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
    _find_audio_path,
    _format_srt_time,
    _split_at_midpoint,
    _split_long_sentence,
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

    def test_audio_not_found_skips_subtitle(self, tmp_path: Path) -> None:
        """When audio path is not found, subtitle is skipped with a warning."""
        config = _make_config(crossfade=0.0)
        tts = _make_tts()
        entries = [PlaylistEntry(path=Path("slides.md"), module_type=ModuleType.MARP)]

        slides = [_make_slide(1, narration_raw="Missing audio.")]

        build_dir = tmp_path / "cache"
        (build_dir / "audio").mkdir(parents=True)

        with (
            patch("slidesonnet.subtitles.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.subtitles._find_audio_path", return_value=None),
        ):
            mock_parser = MagicMock()
            mock_parser.parse.return_value = slides
            mock_gpe.return_value = (lambda: mock_parser, None)
            (tmp_path / "slides.md").touch()

            result = generate_subtitles(entries, config, tts, build_dir, tmp_path)

        assert len(result) == 0

    def test_audio_probe_failure_skips_subtitle(self, tmp_path: Path) -> None:
        """When audio duration probe fails, subtitle is skipped."""
        config = _make_config(crossfade=0.0)
        tts = _make_tts()
        entries = [PlaylistEntry(path=Path("slides.md"), module_type=ModuleType.MARP)]

        slides = [_make_slide(1, narration_raw="Probe fails.")]

        build_dir = tmp_path / "cache"
        audio_dir = build_dir / "audio"
        audio_dir.mkdir(parents=True)
        fake_audio = audio_dir / "fake.wav"
        fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

        with (
            patch("slidesonnet.subtitles.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.subtitles.get_duration", side_effect=RuntimeError("probe fail")),
            patch("slidesonnet.subtitles._find_audio_path", return_value=fake_audio),
        ):
            mock_parser = MagicMock()
            mock_parser.parse.return_value = slides
            mock_gpe.return_value = (lambda: mock_parser, None)
            (tmp_path / "slides.md").touch()

            result = generate_subtitles(entries, config, tts, build_dir, tmp_path)

        assert len(result) == 0

    def test_multi_chunk_subtitle_distribution(self, tmp_path: Path) -> None:
        """Long narration text is split into multiple subtitle entries with proportional timing."""
        config = _make_config(pre_silence=0.0, pad_seconds=0.0, crossfade=0.0)
        tts = _make_tts()
        entries = [PlaylistEntry(path=Path("slides.md"), module_type=ModuleType.MARP)]

        # Long text that will split into multiple chunks at max_chars=40
        long_text = "This is the first sentence. This is the second sentence with more words."
        slides = [_make_slide(1, narration_raw=long_text)]

        build_dir = tmp_path / "cache"
        audio_dir = build_dir / "audio"
        audio_dir.mkdir(parents=True)
        fake_audio = audio_dir / "fake.wav"
        fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

        with (
            patch("slidesonnet.subtitles.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.subtitles.get_duration", return_value=6.0),
            patch("slidesonnet.subtitles._find_audio_path", return_value=fake_audio),
        ):
            mock_parser = MagicMock()
            mock_parser.parse.return_value = slides
            mock_gpe.return_value = (lambda: mock_parser, None)
            (tmp_path / "slides.md").touch()

            result = generate_subtitles(entries, config, tts, build_dir, tmp_path, max_chars=40)

        # Should have multiple subtitle entries
        assert len(result) >= 2
        # All text should be present across chunks
        combined = " ".join(r.text for r in result)
        assert "first sentence" in combined
        assert "second sentence" in combined
        # Timing should be continuous
        for i in range(1, len(result)):
            assert result[i].start == pytest.approx(result[i - 1].end, abs=0.01)

    def test_video_passthrough(self, tmp_path: Path) -> None:
        """Video entry advances offset by video duration."""
        config = _make_config(crossfade=0.5)
        tts = _make_tts()
        entries = [
            PlaylistEntry(path=Path("intro.mp4"), module_type=ModuleType.VIDEO),
            PlaylistEntry(path=Path("slides.md"), module_type=ModuleType.MARP),
        ]

        slides = [_make_slide(1, narration_raw="After video.")]

        build_dir = tmp_path / "cache"
        audio_dir = build_dir / "audio"
        audio_dir.mkdir(parents=True)
        fake_audio = audio_dir / "fake.wav"
        fake_audio.write_bytes(b"RIFF" + b"\x00" * 100)

        (tmp_path / "intro.mp4").touch()
        (tmp_path / "slides.md").touch()

        with (
            patch("slidesonnet.subtitles.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.subtitles.get_duration") as mock_dur,
            patch("slidesonnet.subtitles._find_audio_path", return_value=fake_audio),
        ):
            # First call: video duration, second: slide audio duration
            mock_dur.side_effect = [10.0, 2.0]
            mock_parser = MagicMock()
            mock_parser.parse.return_value = slides
            mock_gpe.return_value = (lambda: mock_parser, None)

            result = generate_subtitles(entries, config, tts, build_dir, tmp_path)

        assert len(result) == 1
        # Video is 10s, then crossfade offset: 10 - 0.5 = 9.5
        # Slide start = 9.5 + pre_silence(1.0) = 10.5
        assert result[0].start == pytest.approx(10.5)

    def test_video_probe_failure(self, tmp_path: Path) -> None:
        """Video entry with probe failure is skipped."""
        config = _make_config(crossfade=0.0)
        tts = _make_tts()
        entries = [
            PlaylistEntry(path=Path("broken.mp4"), module_type=ModuleType.VIDEO),
        ]

        build_dir = tmp_path / "cache"
        (build_dir / "audio").mkdir(parents=True)
        (tmp_path / "broken.mp4").touch()

        with patch("slidesonnet.subtitles.get_duration", side_effect=RuntimeError("probe fail")):
            result = generate_subtitles(entries, config, tts, build_dir, tmp_path)

        assert len(result) == 0

    def test_silence_override_duration(self, tmp_path: Path) -> None:
        """Silent slide with silence_override uses that duration."""
        config = _make_config(crossfade=0.0, silence_duration=3.0)
        tts = _make_tts()
        entries = [PlaylistEntry(path=Path("slides.md"), module_type=ModuleType.MARP)]

        slides = [
            _make_slide(
                1, annotation=SlideAnnotation.SILENT, narration_raw="", silence_override=5.0
            ),
            _make_slide(2, narration_raw="After custom silence."),
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
        # Silent slide offset = 5.0 (override, not 3.0 from config)
        # Second slide start = 5.0 + 1.0 (pre_silence) = 6.0
        assert result[0].start == pytest.approx(6.0)


# ---- _split_long_sentence() tests ----


class TestSplitLongSentence:
    def test_short_returns_as_is(self) -> None:
        assert _split_long_sentence("Short.", 80) == ["Short."]

    def test_empty_returns_empty(self) -> None:
        assert _split_long_sentence("", 80) == []
        assert _split_long_sentence("   ", 80) == []

    def test_clause_split(self) -> None:
        text = "This is a long clause, and here is another clause, plus one more for good measure."
        result = _split_long_sentence(text, 40)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 40

    def test_clause_split_fallback_to_midpoint(self) -> None:
        """If clause split produces chunks > max_chars, falls back to word split."""
        text = "A" * 50 + ", " + "B" * 50  # Each clause > 40 chars
        result = _split_long_sentence(text, 40)
        assert len(result) >= 2

    def test_clause_grouping(self) -> None:
        """Multiple short clauses group into chunks <= max_chars."""
        text = "First, second, third, fourth, and fifth part of the long text here."
        result = _split_long_sentence(text, 40)
        assert len(result) >= 1
        for chunk in result:
            assert len(chunk) <= 40

    def test_no_clause_boundaries_uses_midpoint(self) -> None:
        """Single long sentence without commas/semicolons splits at word boundary."""
        text = "This very long sentence has no clause boundaries at all and needs word splitting"
        result = _split_long_sentence(text, 30)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 30


# ---- _split_at_midpoint() tests ----


class TestSplitAtMidpoint:
    def test_short_returns_as_is(self) -> None:
        assert _split_at_midpoint("Short text", 80) == ["Short text"]

    def test_splits_at_space(self) -> None:
        text = "Hello world this is a long text"
        result = _split_at_midpoint(text, 15)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 15

    def test_no_space_returns_as_is(self) -> None:
        """Text with no spaces can't be split further."""
        text = "A" * 50
        result = _split_at_midpoint(text, 30)
        # Should return as-is since there's no space to split on
        assert result == [text]


# ---- _find_audio_path() tests ----


class TestFindAudioPath:
    def test_direct_path_found(self, tmp_path: Path) -> None:
        slide = SlideNarration(
            index=1,
            annotation=SlideAnnotation.SAY,
            narration_raw="Hello.",
            narration_processed="Hello.",
            narration_parts=["Hello."],
            narration_parts_processed=["Hello."],
        )
        tts = _make_tts()

        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        # Create the expected file
        from slidesonnet.hashing import audio_path as _audio_path

        expected = _audio_path(audio_dir, "Hello.", tts.name(), tts.cache_key(), None)
        expected.write_bytes(b"\x00" * 50)

        result = _find_audio_path(audio_dir, slide, tts)
        assert result is not None
        assert result == expected

    def test_alternate_extension(self, tmp_path: Path) -> None:
        slide = SlideNarration(
            index=1,
            annotation=SlideAnnotation.SAY,
            narration_raw="Hello.",
            narration_processed="Hello.",
            narration_parts=["Hello."],
            narration_parts_processed=["Hello."],
        )
        tts = _make_tts()

        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        from slidesonnet.hashing import audio_path as _audio_path

        expected = _audio_path(audio_dir, "Hello.", tts.name(), tts.cache_key(), None)
        # Write alternate extension
        alt = expected.with_suffix(".mp3")
        alt.write_bytes(b"\x00" * 50)

        result = _find_audio_path(audio_dir, slide, tts)
        if expected.suffix != ".mp3":
            assert result is not None
            assert result == alt

    def test_not_found(self, tmp_path: Path) -> None:
        slide = SlideNarration(
            index=1,
            annotation=SlideAnnotation.SAY,
            narration_raw="Missing.",
            narration_processed="Missing.",
            narration_parts=["Missing."],
            narration_parts_processed=["Missing."],
        )
        tts = _make_tts()

        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        result = _find_audio_path(audio_dir, slide, tts)
        assert result is None

    def test_multi_part_concat_path(self, tmp_path: Path) -> None:
        """Multi-part slide looks for the concatenated audio file."""
        slide = SlideNarration(
            index=1,
            annotation=SlideAnnotation.SAY,
            narration_raw="Part one. Part two.",
            narration_processed="Part one. Part two.",
            narration_parts=["Part one.", "Part two."],
            narration_parts_processed=["Part one.", "Part two."],
        )
        tts = _make_tts()

        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        # Create the concatenated file
        from slidesonnet.hashing import audio_path as _audio_path
        from slidesonnet.hashing import concat_filename as _concat_filename

        part_paths = [
            _audio_path(audio_dir, "Part one.", tts.name(), tts.cache_key(), None),
            _audio_path(audio_dir, "Part two.", tts.name(), tts.cache_key(), None),
        ]
        concat_name = _concat_filename(part_paths)
        concat_path = audio_dir / concat_name
        concat_path.write_bytes(b"\x00" * 50)

        result = _find_audio_path(audio_dir, slide, tts)
        assert result is not None
        assert result == concat_path
