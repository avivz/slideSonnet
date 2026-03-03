"""Tests for parsers/expansion.py — parse_say_params, parse_silence_duration, expand_sub_slides."""

from pathlib import Path

import pytest

from slidesonnet.exceptions import ParserError
from slidesonnet.models import SlideAnnotation
from slidesonnet.parsers.expansion import (
    SayCommand,
    expand_sub_slides,
    parse_say_params,
    parse_silence_duration,
)

SOURCE = Path("test.md")


class TestParseSayParams:
    def test_empty_string(self) -> None:
        assert parse_say_params("") == (0, None, None)

    def test_bare_number(self) -> None:
        assert parse_say_params("2") == (2, None, None)

    def test_slide_key_value(self) -> None:
        assert parse_say_params("slide=3") == (3, None, None)

    def test_voice_key_value(self) -> None:
        assert parse_say_params("voice=alice") == (0, "alice", None)

    def test_pace_key_value(self) -> None:
        assert parse_say_params("pace=slow") == (0, None, "slow")

    def test_mixed_bare_number_and_voice(self) -> None:
        assert parse_say_params("2, voice=alice") == (2, "alice", None)

    def test_slide_key_overrides_bare_number(self) -> None:
        assert parse_say_params("2, slide=5") == (5, None, None)

    def test_default_sub_slide(self) -> None:
        assert parse_say_params("voice=alice", default_sub_slide=1) == (1, "alice", None)


class TestParseSilenceDuration:
    def test_none_returns_none(self) -> None:
        assert parse_silence_duration(None, SOURCE, 1) is None

    def test_empty_returns_none(self) -> None:
        assert parse_silence_duration("", SOURCE, 1) is None

    def test_whitespace_returns_none(self) -> None:
        assert parse_silence_duration("   ", SOURCE, 1) is None

    def test_valid_float(self) -> None:
        assert parse_silence_duration("3.5", SOURCE, 1) == 3.5

    def test_zero(self) -> None:
        assert parse_silence_duration("0", SOURCE, 1) == 0.0

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(ParserError, match="invalid nonarration duration"):
            parse_silence_duration("abc", SOURCE, 1)

    def test_negative_raises(self) -> None:
        with pytest.raises(ParserError, match="must be non-negative"):
            parse_silence_duration("-1", SOURCE, 1)


class TestExpandSubSlides:
    _COMMON = dict(source=SOURCE, label="slide", say_syntax="say:", nonarration_syntax="silent:")

    def test_single_command(self) -> None:
        cmds = [SayCommand(sub_slide=1, text="Hello", voice=None, pace=None)]
        results = expand_sub_slides(
            cmds, n_visual_states=1, start_index=1, start_image_index=1, **self._COMMON
        )
        assert len(results) == 1
        assert results[0].annotation == SlideAnnotation.SAY
        assert results[0].narration_raw == "Hello"

    def test_multiple_commands_joined(self) -> None:
        cmds = [
            SayCommand(sub_slide=1, text="A", voice=None, pace=None),
            SayCommand(sub_slide=1, text="B", voice=None, pace=None),
        ]
        results = expand_sub_slides(
            cmds, n_visual_states=1, start_index=1, start_image_index=1, **self._COMMON
        )
        assert len(results) == 1
        assert results[0].narration_raw == "A B"
        assert results[0].narration_parts == ["A", "B"]

    def test_voice_pace_last_wins(self) -> None:
        cmds = [
            SayCommand(sub_slide=1, text="A", voice="alice", pace="slow"),
            SayCommand(sub_slide=1, text="B", voice="bob", pace="fast"),
        ]
        results = expand_sub_slides(
            cmds, n_visual_states=1, start_index=1, start_image_index=1, **self._COMMON
        )
        assert results[0].voice == "bob"
        assert results[0].pace == "fast"

    def test_missing_sub_slide_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        cmds = [SayCommand(sub_slide=2, text="Hello", voice=None, pace=None)]
        results = expand_sub_slides(
            cmds, n_visual_states=2, start_index=1, start_image_index=1, **self._COMMON
        )
        assert len(results) == 2
        assert results[0].annotation == SlideAnnotation.SILENT
        assert results[1].annotation == SlideAnnotation.SAY
        assert "no narration" in caplog.text

    def test_empty_text_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        cmds = [SayCommand(sub_slide=1, text="", voice=None, pace=None)]
        results = expand_sub_slides(
            cmds, n_visual_states=1, start_index=1, start_image_index=1, **self._COMMON
        )
        assert results[0].annotation == SlideAnnotation.SILENT
        assert "empty" in caplog.text

    def test_max_target_extends(self) -> None:
        cmds = [SayCommand(sub_slide=3, text="Hello", voice=None, pace=None)]
        results = expand_sub_slides(
            cmds, n_visual_states=2, start_index=1, start_image_index=1, **self._COMMON
        )
        assert len(results) == 3

    def test_image_index_capped(self) -> None:
        cmds = [SayCommand(sub_slide=3, text="Hello", voice=None, pace=None)]
        results = expand_sub_slides(
            cmds, n_visual_states=2, start_index=1, start_image_index=1, **self._COMMON
        )
        # sub_slide=3, n_visual=2 → image_index capped at last visual
        assert results[2].image_index == 2  # start_image_index + min(2, 1) = 1 + 1 = 2

    def test_start_index_offset(self) -> None:
        cmds = [SayCommand(sub_slide=1, text="Hello", voice=None, pace=None)]
        results = expand_sub_slides(
            cmds, n_visual_states=1, start_index=5, start_image_index=10, **self._COMMON
        )
        assert results[0].index == 5
        assert results[0].image_index == 10
