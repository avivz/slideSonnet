"""Tests for Piper TTS backend."""

import subprocess
import wave
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import TTSError
from slidesonnet.tts.piper import PiperTTS, _wav_duration


class TestPiperSynthesize:
    """Tests for PiperTTS.synthesize()."""

    @pytest.fixture(autouse=True)
    def _mock_ensure_voice(self) -> Iterator[None]:
        """Prevent _ensure_voice from hitting real filesystem or network."""
        with patch("slidesonnet.tts.piper._ensure_voice"):
            yield

    @patch("slidesonnet.tts.piper._wav_duration", return_value=2.5)
    @patch("slidesonnet.tts.piper.subprocess.run")
    def test_basic_synthesis(
        self, mock_run: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        tts = PiperTTS(model="en_US-lessac-medium")
        out = tmp_path / "out.wav"

        duration = tts.synthesize("Hello world", out)

        assert duration == 2.5
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert Path(cmd[0]).name == "piper"
        assert "--model" in cmd
        assert "en_US-lessac-medium" in cmd
        assert "--output_file" in cmd
        assert str(out) in cmd
        assert mock_run.call_args[1]["input"] == "Hello world"
        assert mock_run.call_args[1]["check"] is True

    @patch("slidesonnet.tts.piper._wav_duration", return_value=1.0)
    @patch("slidesonnet.tts.piper.subprocess.run")
    def test_voice_override(self, mock_run: MagicMock, mock_dur: MagicMock, tmp_path: Path) -> None:
        tts = PiperTTS(model="en_US-lessac-medium")
        out = tmp_path / "out.wav"

        tts.synthesize("Hi", out, voice="en_US-amy-medium")

        cmd = mock_run.call_args[0][0]
        assert "en_US-amy-medium" in cmd
        assert "en_US-lessac-medium" not in cmd

    @patch("slidesonnet.tts.piper._wav_duration", return_value=1.0)
    @patch("slidesonnet.tts.piper.subprocess.run")
    def test_speaker_flag(self, mock_run: MagicMock, mock_dur: MagicMock, tmp_path: Path) -> None:
        tts = PiperTTS(model="en_US-lessac-medium", speaker=3)
        out = tmp_path / "out.wav"

        tts.synthesize("Hi", out)

        cmd = mock_run.call_args[0][0]
        assert "--speaker" in cmd
        idx = cmd.index("--speaker")
        assert cmd[idx + 1] == "3"

    @patch("slidesonnet.tts.piper._wav_duration", return_value=1.0)
    @patch("slidesonnet.tts.piper.subprocess.run")
    def test_speaker_zero_passes_flag(
        self, mock_run: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        tts = PiperTTS(model="en_US-lessac-medium", speaker=0)
        out = tmp_path / "out.wav"

        tts.synthesize("Hi", out)

        cmd = mock_run.call_args[0][0]
        assert "--speaker" in cmd
        idx = cmd.index("--speaker")
        assert cmd[idx + 1] == "0"

    @patch("slidesonnet.tts.piper._wav_duration", return_value=1.0)
    @patch("slidesonnet.tts.piper.subprocess.run")
    def test_no_speaker_flag_when_none(
        self, mock_run: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        tts = PiperTTS(model="en_US-lessac-medium", speaker=None)
        out = tmp_path / "out.wav"

        tts.synthesize("Hi", out)

        cmd = mock_run.call_args[0][0]
        assert "--speaker" not in cmd

    @patch("slidesonnet.tts.piper._wav_duration", return_value=1.0)
    @patch("slidesonnet.tts.piper.subprocess.run")
    def test_creates_output_dir(
        self, mock_run: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        tts = PiperTTS()
        out = tmp_path / "subdir" / "deep" / "out.wav"

        tts.synthesize("Hi", out)

        assert out.parent.exists()

    @patch("slidesonnet.tts.piper.subprocess.run", side_effect=FileNotFoundError)
    def test_piper_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        tts = PiperTTS()
        with pytest.raises(TTSError):
            tts.synthesize("Hi", tmp_path / "out.wav")

    @patch(
        "slidesonnet.tts.piper.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "piper", stderr="error msg"),
    )
    def test_piper_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        tts = PiperTTS()
        with pytest.raises(TTSError):
            tts.synthesize("Hi", tmp_path / "out.wav")


class TestWavDuration:
    """Tests for _wav_duration()."""

    def test_correct_duration(self, tmp_path: Path) -> None:
        path = tmp_path / "test.wav"
        sample_rate = 44100
        num_frames = 44100 * 2  # 2 seconds
        with wave.open(str(path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * num_frames)

        assert _wav_duration(path) == pytest.approx(2.0)

    def test_short_file(self, tmp_path: Path) -> None:
        path = tmp_path / "short.wav"
        sample_rate = 22050
        num_frames = 22050  # 1 second at 22050 Hz
        with wave.open(str(path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * num_frames)

        assert _wav_duration(path) == pytest.approx(1.0)


class TestEnsureVoice:
    """Tests for _ensure_voice()."""

    @patch("slidesonnet.tts.piper._VOICES_DIR")
    def test_missing_package_gives_helpful_error(self, mock_dir: MagicMock, tmp_path: Path) -> None:
        """If piper-tts package is missing, should exit with a helpful message."""
        from slidesonnet.tts.piper import _ensure_voice

        # Point _VOICES_DIR to tmp_path so the model file won't exist
        mock_dir.__truediv__ = lambda self, x: tmp_path / x
        mock_dir.mkdir = MagicMock()

        with patch.dict("sys.modules", {"piper": None, "piper.download_voices": None}):
            with pytest.raises(TTSError) as exc_info:
                _ensure_voice("en_US-lessac-medium")

        assert "piper-tts" in str(exc_info.value)
        assert "auto-download" in str(exc_info.value)


class TestSpeed:
    """Tests for speed / --length_scale support."""

    @pytest.fixture(autouse=True)
    def _mock_ensure_voice(self) -> Iterator[None]:
        with patch("slidesonnet.tts.piper._ensure_voice"):
            yield

    @patch("slidesonnet.tts.piper._wav_duration", return_value=1.0)
    @patch("slidesonnet.tts.piper.subprocess.run")
    def test_length_scale_when_speed_set(
        self, mock_run: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        tts = PiperTTS(speed=1.5)
        out = tmp_path / "out.wav"
        tts.synthesize("Hi", out)

        cmd = mock_run.call_args[0][0]
        assert "--length_scale" in cmd
        idx = cmd.index("--length_scale")
        assert float(cmd[idx + 1]) == pytest.approx(1.0 / 1.5)

    @patch("slidesonnet.tts.piper._wav_duration", return_value=1.0)
    @patch("slidesonnet.tts.piper.subprocess.run")
    def test_no_length_scale_at_default_speed(
        self, mock_run: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        tts = PiperTTS(speed=1.0)
        out = tmp_path / "out.wav"
        tts.synthesize("Hi", out)

        cmd = mock_run.call_args[0][0]
        assert "--length_scale" not in cmd

    def test_cache_key_with_speed(self) -> None:
        tts = PiperTTS(speed=1.5)
        assert ":1.5" in tts.cache_key()

    def test_cache_key_default_speed(self) -> None:
        tts = PiperTTS(speed=1.0)
        # Default speed → key should be "piper:model:speaker" with no trailing speed
        parts = tts.cache_key().split(":")
        assert len(parts) == 3  # piper:model:speaker


class TestName:
    def test_name(self) -> None:
        assert PiperTTS().name() == "piper"
