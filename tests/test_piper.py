"""Tests for Piper TTS backend."""

import subprocess
import wave
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
        assert cmd[0] == "piper"
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
    def test_no_speaker_flag_when_zero(
        self, mock_run: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        tts = PiperTTS(model="en_US-lessac-medium", speaker=0)
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
        with pytest.raises(SystemExit, match="1"):
            tts.synthesize("Hi", tmp_path / "out.wav")

    @patch(
        "slidesonnet.tts.piper.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "piper", stderr="error msg"),
    )
    def test_piper_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        tts = PiperTTS()
        with pytest.raises(SystemExit, match="1"):
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
    def test_missing_package_gives_helpful_error(
        self, mock_dir: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """If piper-tts package is missing, should exit with a helpful message."""
        from slidesonnet.tts.piper import _ensure_voice

        # Point _VOICES_DIR to tmp_path so the model file won't exist
        mock_dir.__truediv__ = lambda self, x: tmp_path / x
        mock_dir.mkdir = MagicMock()

        with patch.dict("sys.modules", {"piper": None, "piper.download_voices": None}):
            with pytest.raises(SystemExit, match="1"):
                _ensure_voice("en_US-lessac-medium")

        captured = capsys.readouterr()
        assert "piper-tts" in captured.err
        assert "auto-download" in captured.err


class TestName:
    def test_name(self) -> None:
        assert PiperTTS().name() == "piper"
