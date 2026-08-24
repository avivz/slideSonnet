"""Tests for the Kokoro TTS backend (mocked — no torch/model download)."""

from __future__ import annotations

import warnings
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import TTSError
from slidesonnet.tts.kokoro import KokoroTTS, _quiet_torch_load_warnings


def test_quiet_torch_load_warnings_silences_the_two_known_warnings() -> None:
    """The LSTM-dropout UserWarning and weight_norm FutureWarning torch emits on
    model construction are swallowed (they're third-party noise, not ours)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with _quiet_torch_load_warnings():
            warnings.warn(
                "dropout option adds dropout after all but last recurrent layer, "
                "so non-zero dropout expects num_layers greater than 1",
                UserWarning,
            )
            warnings.warn(
                "`torch.nn.utils.weight_norm` is deprecated in favor of "
                "`torch.nn.utils.parametrizations.weight_norm`.",
                FutureWarning,
            )
    assert caught == []


def test_quiet_torch_load_warnings_leaves_unrelated_warnings() -> None:
    """Only the two known torch messages are filtered — anything else passes."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with _quiet_torch_load_warnings():
            warnings.warn("a genuinely different warning", UserWarning)
    assert len(caught) == 1


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
        assert key == "kokoro:am_echo"

    def test_with_speed(self) -> None:
        assert KokoroTTS(speed=1.5).cache_key() == "kokoro:am_echo:1.5"

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

    def test_pace_scales_kokoro_speed(self) -> None:
        from slidesonnet.audio.synth import engine_for_pace
        from slidesonnet.models import TTSConfig
        from slidesonnet.narration.format import pace_to_speed
        from slidesonnet.tts.base import TTSEngine

        cfg = TTSConfig(backend="kokoro", kokoro_speed=1.0)
        cache: dict[float, TTSEngine] = {}
        engine = engine_for_pace(cfg, "fast", cache)
        assert isinstance(engine, KokoroTTS)
        assert engine.speed == pytest.approx(pace_to_speed("fast"))


def test_kokoro_is_not_paid() -> None:
    assert KokoroTTS().paid is False


class TestWriteWav:
    def test_roundtrip_values_and_clipping(self, tmp_path: Path) -> None:
        import wave

        from slidesonnet.tts.kokoro import _SAMPLE_RATE, _write_wav

        out = tmp_path / "clip.wav"
        _write_wav(out, [0.0, 0.5, -0.5, 1.5, -1.5])  # last two must clip
        with wave.open(str(out), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == _SAMPLE_RATE
            raw = wf.readframes(wf.getnframes())
        values = [
            int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw), 2)
        ]
        assert values == [0, 16383, -16383, 32767, -32767]

    def test_large_buffer_is_fast_enough(self, tmp_path: Path) -> None:
        import time

        from slidesonnet.tts.kokoro import _SAMPLE_RATE, _write_wav

        samples = [0.25] * (_SAMPLE_RATE * 60)  # one minute of audio
        start = time.monotonic()
        _write_wav(tmp_path / "minute.wav", samples)
        assert time.monotonic() - start < 2.0  # byte-by-byte loop took far longer

    def test_write_is_atomic_on_failure(self, tmp_path: Path) -> None:
        """A write that fails at the final rename must not clobber an existing
        file or leave a partial one — two concurrent generators of the same clip
        would otherwise corrupt each other's output."""
        from slidesonnet.tts.kokoro import _write_wav

        out = tmp_path / "clip.wav"
        out.write_bytes(b"ORIGINAL-GOOD-AUDIO")

        with patch("os.replace", side_effect=OSError("boom")), pytest.raises(OSError):
            _write_wav(out, [0.5] * 1000)

        # The existing file survived untouched, and no temp file was left behind.
        assert out.read_bytes() == b"ORIGINAL-GOOD-AUDIO"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.wav"]

    def test_write_leaves_no_temp_files_on_success(self, tmp_path: Path) -> None:
        from slidesonnet.tts.kokoro import _write_wav

        _write_wav(tmp_path / "clip.wav", [0.5] * 1000)

        assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.wav"]


class TestCacheFirstDownloads:
    """Kokoro resolves model/voice files from the local HF cache before it will
    talk to huggingface.co — so a flaky or absent network can't stall startup."""

    @staticmethod
    def _orig(recorder: list[dict[str, object]], *, missing: bool = False) -> object:
        # Raise the module's own cache-miss type rather than importing
        # huggingface_hub: it ships with the kokoro extra, which CI doesn't install.
        from slidesonnet.tts.kokoro import _CacheMiss

        def fake(repo_id: str, filename: str, **kwargs: object) -> str:
            recorder.append({"filename": filename, **kwargs})
            if missing and kwargs.get("local_files_only"):
                raise _CacheMiss("not cached")
            return f"/cache/{filename}"

        return fake

    def test_cached_file_never_touches_the_network(self) -> None:
        from slidesonnet.tts.kokoro import _cache_first

        calls: list[dict[str, object]] = []
        wrapped = _cache_first(self._orig(calls))  # type: ignore[arg-type]

        assert wrapped(repo_id="r", filename="config.json") == "/cache/config.json"
        assert calls == [{"filename": "config.json", "local_files_only": True}]

    def test_uncached_file_falls_back_to_downloading(self) -> None:
        from slidesonnet.tts.kokoro import _cache_first

        calls: list[dict[str, object]] = []
        wrapped = _cache_first(self._orig(calls, missing=True))  # type: ignore[arg-type]

        assert wrapped(repo_id="r", filename="voices/af_sky.pt") == "/cache/voices/af_sky.pt"
        assert len(calls) == 2
        assert calls[0]["local_files_only"] is True
        assert "local_files_only" not in calls[1]  # second try may hit the hub

    def test_explicit_caller_options_pass_through_untouched(self) -> None:
        """A caller that already asked for a refresh (or for strict offline) owns
        the decision — we don't second-guess it with a cache-first probe."""
        from slidesonnet.tts.kokoro import _cache_first

        calls: list[dict[str, object]] = []
        wrapped = _cache_first(self._orig(calls))  # type: ignore[arg-type]

        wrapped(repo_id="r", filename="a", force_download=True)
        wrapped(repo_id="r", filename="b", local_files_only=True)

        assert calls == [
            {"filename": "a", "force_download": True},
            {"filename": "b", "local_files_only": True},
        ]

    def test_install_patches_kokoro_download_sites_once(self) -> None:
        pytest.importorskip("kokoro")
        import kokoro.model
        import kokoro.pipeline

        from slidesonnet.tts.kokoro import _install_cache_first_downloads

        originals = (kokoro.model.hf_hub_download, kokoro.pipeline.hf_hub_download)
        try:
            _install_cache_first_downloads()
            patched = (kokoro.model.hf_hub_download, kokoro.pipeline.hf_hub_download)
            assert all(getattr(fn, "_slidesonnet_cache_first", False) for fn in patched)

            _install_cache_first_downloads()  # idempotent — no double wrapping
            assert (kokoro.model.hf_hub_download, kokoro.pipeline.hf_hub_download) == patched
        finally:
            kokoro.model.hf_hub_download, kokoro.pipeline.hf_hub_download = originals

    def test_refresh_env_var_restores_stock_behaviour(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("kokoro")
        import kokoro.model

        from slidesonnet.tts.kokoro import _ENV_REFRESH, _install_cache_first_downloads

        monkeypatch.setenv(_ENV_REFRESH, "1")
        original = kokoro.model.hf_hub_download
        try:
            _install_cache_first_downloads()
            assert kokoro.model.hf_hub_download is original
        finally:
            kokoro.model.hf_hub_download = original

    @patch("slidesonnet.tts.kokoro._install_cache_first_downloads")
    @patch("slidesonnet.tts.kokoro.KPipeline")
    def test_building_a_pipeline_installs_the_wrapper(
        self, mock_kp: MagicMock, mock_install: MagicMock, tmp_path: Path
    ) -> None:
        mock_kp.return_value = _fake_pipeline([100])

        KokoroTTS().synthesize("Hi", tmp_path / "out.wav")

        mock_install.assert_called_once()
