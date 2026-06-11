"""Tests for the Kokoro TTS backend (mocked — no torch/model download)."""

from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import TTSError
from slidesonnet.tts.kokoro import KokoroTTS


def _fake_audio(samples: int) -> MagicMock:
    """A stand-in for a torch float tensor: tolist() yields floats in [-1, 1]."""
    audio = MagicMock()
    audio.tolist.return_value = [0.5] * samples
    return audio


def _fake_pipeline(samples_per_chunk: list[int]) -> MagicMock:
    """A KPipeline whose call yields one result per entry, with that many samples."""
    pipeline = MagicMock()
    pipeline.side_effect = lambda *a, **kw: iter(
        [SimpleNamespace(audio=_fake_audio(n)) for n in samples_per_chunk]
    )
    return pipeline


class TestKokoroSynthesize:
    @patch("slidesonnet.tts.kokoro.KPipeline")
    def test_basic_synthesis(self, mock_kp: MagicMock, tmp_path: Path) -> None:
        pipeline = _fake_pipeline([24_000, 12_000])  # 1.5 s at 24 kHz
        mock_kp.return_value = pipeline
        tts = KokoroTTS(voice="af_heart")
        out = tmp_path / "out.wav"

        duration = tts.synthesize("Hello world", out)

        assert duration == pytest.approx(1.5)
        assert out.exists()
        with wave.open(str(out), "rb") as wf:
            assert wf.getframerate() == 24_000
            assert wf.getnchannels() == 1
            assert wf.getnframes() == 36_000
        # Pipeline created with the voice's language code ('a' for af_*).
        assert mock_kp.call_args[1]["lang_code"] == "a"
        # Called with the configured voice and speed.
        assert pipeline.call_args[1]["voice"] == "af_heart"
        assert pipeline.call_args[1]["speed"] == 1.0

    @patch("slidesonnet.tts.kokoro.KPipeline")
    def test_voice_override(self, mock_kp: MagicMock, tmp_path: Path) -> None:
        pipeline = _fake_pipeline([1000])
        mock_kp.return_value = pipeline
        tts = KokoroTTS(voice="af_heart")

        tts.synthesize("Hi", tmp_path / "out.wav", voice="bm_george")

        assert mock_kp.call_args[1]["lang_code"] == "b"
        assert pipeline.call_args[1]["voice"] == "bm_george"

    @patch("slidesonnet.tts.kokoro.KPipeline")
    def test_speed_passed_through(self, mock_kp: MagicMock, tmp_path: Path) -> None:
        pipeline = _fake_pipeline([1000])
        mock_kp.return_value = pipeline
        tts = KokoroTTS(speed=1.25)

        tts.synthesize("Hi", tmp_path / "out.wav")

        assert pipeline.call_args[1]["speed"] == 1.25

    @patch("slidesonnet.tts.kokoro.KPipeline")
    def test_pipeline_reused_per_lang(self, mock_kp: MagicMock, tmp_path: Path) -> None:
        mock_kp.side_effect = lambda **kw: _fake_pipeline([100])
        tts = KokoroTTS(voice="af_heart")

        tts.synthesize("One", tmp_path / "a.wav")
        tts.synthesize("Two", tmp_path / "b.wav")

        assert mock_kp.call_count == 1  # same lang code → one pipeline

    @patch("slidesonnet.tts.kokoro.KPipeline")
    def test_creates_output_dir(self, mock_kp: MagicMock, tmp_path: Path) -> None:
        mock_kp.return_value = _fake_pipeline([100])
        out = tmp_path / "sub" / "deep" / "out.wav"

        KokoroTTS().synthesize("Hi", out)

        assert out.exists()

    @patch("slidesonnet.tts.kokoro.KPipeline")
    def test_no_audio_raises(self, mock_kp: MagicMock, tmp_path: Path) -> None:
        mock_kp.return_value = _fake_pipeline([])
        with pytest.raises(TTSError):
            KokoroTTS().synthesize("Hi", tmp_path / "out.wav")

    @patch("slidesonnet.tts.kokoro.KPipeline", None)
    def test_missing_package_gives_helpful_error(self, tmp_path: Path) -> None:
        with pytest.raises(TTSError) as exc_info:
            KokoroTTS().synthesize("Hi", tmp_path / "out.wav")
        assert "kokoro" in str(exc_info.value)
        assert "slidesonnet[kokoro]" in str(exc_info.value)


class TestCacheKey:
    def test_default(self) -> None:
        key = KokoroTTS().cache_key()
        assert key == "kokoro:af_heart"

    def test_with_speed(self) -> None:
        assert KokoroTTS(speed=1.5).cache_key() == "kokoro:af_heart:1.5"

    def test_name(self) -> None:
        assert KokoroTTS().name() == "kokoro"


class TestFactoryAndConfig:
    def test_create_tts_kokoro(self) -> None:
        from slidesonnet.models import TTSConfig
        from slidesonnet.tts import create_tts

        engine = create_tts(TTSConfig(backend="kokoro", kokoro_voice="am_adam", kokoro_speed=1.2))
        assert isinstance(engine, KokoroTTS)
        assert engine.voice == "am_adam"
        assert engine.speed == 1.2

    def test_config_parses_kokoro_table(self, tmp_path: Path) -> None:
        from slidesonnet.config import load_config

        (tmp_path / "slidesonnet.toml").write_text(
            '[tts]\nbackend = "kokoro"\n\n[tts.kokoro]\nvoice = "am_adam"\nspeed = 1.1\n'
        )
        config = load_config(tmp_path / "deck.pdf")
        assert config.tts.backend == "kokoro"
        assert config.tts.kokoro_voice == "am_adam"
        assert config.tts.kokoro_speed == 1.1

    def test_invalid_speed_rejected(self) -> None:
        from slidesonnet.models import TTSConfig

        with pytest.raises(ValueError):
            TTSConfig(kokoro_speed=0.0)

    def test_create_tts_unknown_backend_rejected(self) -> None:
        from slidesonnet.models import TTSConfig
        from slidesonnet.tts import create_tts

        cfg = TTSConfig()
        cfg.backend = "espeak"  # type: ignore[assignment]
        with pytest.raises(ValueError, match="Unknown TTS backend"):
            create_tts(cfg)

    def test_create_tts_from_config(self) -> None:
        from slidesonnet.config import Config
        from slidesonnet.tts import create_tts_from_config

        engine = create_tts_from_config(Config())
        assert isinstance(engine, KokoroTTS)  # default backend is kokoro

    def test_pace_scales_kokoro_speed(self) -> None:
        from slidesonnet.audio.synth import _engine_for_pace
        from slidesonnet.models import TTSConfig
        from slidesonnet.narration.format import pace_to_speed
        from slidesonnet.tts.base import TTSEngine

        cfg = TTSConfig(backend="kokoro", kokoro_speed=1.0)
        cache: dict[float, TTSEngine] = {}
        engine = _engine_for_pace(cfg, "fast", cache)
        assert isinstance(engine, KokoroTTS)
        assert engine.speed == pytest.approx(pace_to_speed("fast"))


def test_kokoro_is_not_paid() -> None:
    assert KokoroTTS().paid is False
