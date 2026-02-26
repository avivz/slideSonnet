"""Tests for single-slide preview."""

import logging
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.preview import _play_audio, preview_single_slide


class TestPreviewSingleSlide:
    """Tests for preview_single_slide()."""

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "slides.pptx"
        bad_file.write_text("dummy")
        with pytest.raises(SlideSonnetError):
            preview_single_slide(bad_file, 1)

    def test_slide_number_too_high(self, tmp_path: Path) -> None:
        md = tmp_path / "slides.md"
        md.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Only Slide

            <!-- say: Hello. -->
        """)
        )
        with pytest.raises(SlideSonnetError):
            preview_single_slide(md, 5)

    def test_slide_number_zero(self, tmp_path: Path) -> None:
        md = tmp_path / "slides.md"
        md.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Only Slide

            <!-- say: Hello. -->
        """)
        )
        with pytest.raises(SlideSonnetError):
            preview_single_slide(md, 0)

    def test_silent_slide_no_tts(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        md = tmp_path / "slides.md"
        md.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Silent Slide

            <!-- silent -->
        """)
        )
        with caplog.at_level(logging.INFO):
            preview_single_slide(md, 1)
        assert "no narration to preview" in caplog.text

    @patch("slidesonnet.preview._play_audio")
    @patch("slidesonnet.preview.PiperTTS")
    def test_narrated_slide_calls_tts(
        self, mock_tts_cls: MagicMock, mock_play: MagicMock, tmp_path: Path
    ) -> None:
        md = tmp_path / "slides.md"
        md.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Slide One

            <!-- say: Hello world. -->
        """)
        )
        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = 1.5
        mock_tts_cls.return_value = mock_tts

        preview_single_slide(md, 1)

        mock_tts.synthesize.assert_called_once()
        text_arg = mock_tts.synthesize.call_args[0][0]
        assert "Hello world" in text_arg
        mock_play.assert_called_once()

    @patch("slidesonnet.preview._play_audio")
    @patch("slidesonnet.preview.PiperTTS")
    def test_with_playlist_loads_pronunciation(
        self, mock_tts_cls: MagicMock, mock_play: MagicMock, tmp_path: Path
    ) -> None:
        # Create pronunciation file
        pron_file = tmp_path / "pronunciation.md"
        pron_file.write_text("**API**: A P I\n")

        # Create playlist referencing pronunciation
        playlist = tmp_path / "lecture.md"
        playlist.write_text(
            textwrap.dedent("""\
            ---
            title: Test
            pronunciation:
              - pronunciation.md
            ---

            1. [Intro](slides.md)
        """)
        )

        md = tmp_path / "slides.md"
        md.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Slide One

            <!-- say: The API is great. -->
        """)
        )
        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = 1.0
        mock_tts_cls.return_value = mock_tts

        preview_single_slide(md, 1, playlist_path=playlist)

        # Pronunciation should have been applied: API → A P I
        text_arg = mock_tts.synthesize.call_args[0][0]
        assert "A P I" in text_arg

    @patch("slidesonnet.preview._play_audio")
    @patch("slidesonnet.preview.PiperTTS")
    def test_tex_file_uses_beamer_parser(
        self, mock_tts_cls: MagicMock, mock_play: MagicMock, tmp_path: Path
    ) -> None:
        tex = tmp_path / "slides.tex"
        tex.write_text(
            textwrap.dedent(r"""
            \begin{frame}
            \say{Hello from Beamer.}
            \end{frame}
        """)
        )
        mock_tts = MagicMock()
        mock_tts.synthesize.return_value = 1.0
        mock_tts_cls.return_value = mock_tts

        preview_single_slide(tex, 1)

        text_arg = mock_tts.synthesize.call_args[0][0]
        assert "Hello from Beamer" in text_arg


class TestPlayAudio:
    """Tests for _play_audio()."""

    @patch("slidesonnet.preview.subprocess.run")
    def test_first_player_works(self, mock_run: MagicMock, tmp_path: Path) -> None:
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"fake")

        _play_audio(audio)

        # Should try first player (aplay) and succeed
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "aplay"

    @patch("slidesonnet.preview.subprocess.run")
    def test_falls_through_on_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"fake")

        # First 3 players not found, 4th works
        mock_run.side_effect = [
            FileNotFoundError,
            FileNotFoundError,
            FileNotFoundError,
            MagicMock(),  # afplay succeeds
        ]

        _play_audio(audio)
        assert mock_run.call_count == 4

    @patch("slidesonnet.preview.subprocess.run")
    def test_falls_through_on_called_process_error(
        self, mock_run: MagicMock, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"fake")

        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "aplay", stderr="device busy"),
            MagicMock(),  # paplay succeeds
        ]

        _play_audio(audio)
        assert mock_run.call_count == 2
        assert "aplay failed" in caplog.text
        assert "device busy" in caplog.text

    @patch("slidesonnet.preview.subprocess.run", side_effect=FileNotFoundError)
    def test_all_players_not_found(
        self, mock_run: MagicMock, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"fake")

        _play_audio(audio)

        assert "no audio player found" in caplog.text

    @patch("slidesonnet.preview.subprocess.run")
    def test_all_players_error(
        self, mock_run: MagicMock, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        audio = tmp_path / "test.wav"
        audio.write_bytes(b"fake")

        mock_run.side_effect = subprocess.CalledProcessError(1, "player", stderr="bad audio")

        _play_audio(audio)

        assert "All audio players failed" in caplog.text
