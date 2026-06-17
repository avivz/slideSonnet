"""Tests for the configuration data models (VoiceConfig, TTSConfig, VideoConfig)."""

from __future__ import annotations

import pytest

from slidesonnet.models import (
    TTSConfig,
    VideoConfig,
    VoiceConfig,
    resolve_voice,
)


class TestVoiceConfig:
    def test_resolve_mapped_backend(self) -> None:
        vc = VoiceConfig(name="narrator", backend_voices={"kokoro": "af_heart"})
        assert vc.resolve("kokoro") == "af_heart"

    def test_resolve_unmapped_backend_returns_none(self) -> None:
        vc = VoiceConfig(name="narrator", backend_voices={"kokoro": "af_heart"})
        assert vc.resolve("elevenlabs") is None

    def test_all_voice_ids(self) -> None:
        vc = VoiceConfig(
            name="narrator",
            backend_voices={"kokoro": "af_heart", "elevenlabs": "EXAVITQu4vr4xnSDxMaL"},
        )
        assert vc.all_voice_ids() == {"af_heart", "EXAVITQu4vr4xnSDxMaL"}

    def test_all_voice_ids_empty(self) -> None:
        assert VoiceConfig(name="narrator").all_voice_ids() == set()


class TestResolveVoice:
    VOICES: dict[str, VoiceConfig] = {
        "narrator": VoiceConfig(name="narrator", backend_voices={"kokoro": "af_bella"})
    }

    def test_none_preset(self) -> None:
        assert resolve_voice(None, self.VOICES, "kokoro") is None

    def test_empty_preset(self) -> None:
        assert resolve_voice("", self.VOICES, "kokoro") is None

    def test_raw_voice_id_passes_through(self) -> None:
        # not a named preset -> treated as a raw backend voice id
        assert resolve_voice("af_heart", self.VOICES, "kokoro") == "af_heart"

    def test_known_preset_mapped_backend(self) -> None:
        assert resolve_voice("narrator", self.VOICES, "kokoro") == "af_bella"

    def test_known_preset_unmapped_backend(self) -> None:
        assert resolve_voice("narrator", self.VOICES, "elevenlabs") is None


class TestAPIBackends:
    def test_elevenlabs_is_api_kokoro_is_not(self) -> None:
        from slidesonnet.tts import API_BACKENDS

        assert "elevenlabs" in API_BACKENDS
        assert "kokoro" not in API_BACKENDS


class TestTTSConfigValidation:
    def test_defaults_are_valid(self) -> None:
        cfg = TTSConfig()
        assert cfg.backend == "kokoro"
        assert cfg.kokoro_voice == "af_heart"

    @pytest.mark.parametrize("stability", [-0.1, 1.1])
    def test_stability_out_of_range(self, stability: float) -> None:
        with pytest.raises(ValueError, match="elevenlabs_stability"):
            TTSConfig(elevenlabs_stability=stability)

    @pytest.mark.parametrize("boost", [-0.1, 1.5])
    def test_similarity_boost_out_of_range(self, boost: float) -> None:
        with pytest.raises(ValueError, match="elevenlabs_similarity_boost"):
            TTSConfig(elevenlabs_similarity_boost=boost)

    @pytest.mark.parametrize("value", [0.0, 1.0])
    def test_stability_boundaries_accepted(self, value: float) -> None:
        cfg = TTSConfig(elevenlabs_stability=value, elevenlabs_similarity_boost=value)
        assert cfg.elevenlabs_stability == value

    @pytest.mark.parametrize("speed", [0.0, -1.0])
    def test_kokoro_speed_must_be_positive(self, speed: float) -> None:
        with pytest.raises(ValueError, match="kokoro_speed"):
            TTSConfig(kokoro_speed=speed)

    @pytest.mark.parametrize("speed", [0.0, -0.5])
    def test_elevenlabs_speed_must_be_positive(self, speed: float) -> None:
        with pytest.raises(ValueError, match="elevenlabs_speed"):
            TTSConfig(elevenlabs_speed=speed)


class TestVideoConfigValidation:
    def test_defaults_are_valid(self) -> None:
        cfg = VideoConfig()
        assert cfg.resolution == "1920x1080"
        assert cfg.preset == "medium"

    @pytest.mark.parametrize("resolution", ["1920", "1920x", "x1080", "fullhd", "1920X1080"])
    def test_invalid_resolution(self, resolution: str) -> None:
        with pytest.raises(ValueError, match="resolution"):
            VideoConfig(resolution=resolution)

    def test_custom_resolution_accepted(self) -> None:
        assert VideoConfig(resolution="640x360").resolution == "640x360"

    @pytest.mark.parametrize("fps", [0, -24])
    def test_fps_must_be_positive(self, fps: int) -> None:
        with pytest.raises(ValueError, match="fps"):
            VideoConfig(fps=fps)

    def test_crf_must_be_non_negative(self) -> None:
        with pytest.raises(ValueError, match="crf"):
            VideoConfig(crf=-1)

    def test_crf_zero_accepted(self) -> None:
        assert VideoConfig(crf=0).crf == 0

    def test_invalid_preset(self) -> None:
        with pytest.raises(ValueError, match="preset"):
            VideoConfig(preset="warp9")

    def test_pre_silence_must_be_non_negative(self) -> None:
        with pytest.raises(ValueError, match="pre_silence"):
            VideoConfig(pre_silence=-0.1)

    def test_tail_seconds_must_be_non_negative(self) -> None:
        with pytest.raises(ValueError, match="tail_seconds"):
            VideoConfig(tail_seconds=-0.1)

    def test_zero_paddings_accepted(self) -> None:
        cfg = VideoConfig(pre_silence=0.0, tail_seconds=0.0)
        assert cfg.pre_silence == 0.0


class TestBackendRegistry:
    """The runtime registry and the static Literal must stay in sync."""

    def test_registry_matches_backend_literal(self) -> None:
        from typing import get_args

        from slidesonnet.models import Backend
        from slidesonnet.tts import BACKENDS

        assert set(BACKENDS) == set(get_args(Backend))

    def test_registry_specs(self) -> None:
        from slidesonnet.tts import BACKENDS

        kokoro = BACKENDS["kokoro"]
        eleven = BACKENDS["elevenlabs"]
        qwen3 = BACKENDS["qwen3"]
        assert (kokoro.extension, kokoro.paid, kokoro.realtime) == (".wav", False, True)
        assert (eleven.extension, eleven.paid, eleven.realtime) == (".mp3", True, True)
        # Qwen3 is free local audio (.wav, not paid) but too slow to auto-generate.
        assert (qwen3.extension, qwen3.paid, qwen3.realtime) == (".wav", False, False)

    def test_engine_voice_introspection(self) -> None:
        from slidesonnet.models import TTSConfig
        from slidesonnet.tts import create_tts
        from slidesonnet.tts.kokoro import KOKORO_VOICES

        kokoro = create_tts(TTSConfig(backend="kokoro", kokoro_voice="af_nova"))
        assert kokoro.list_voices() == KOKORO_VOICES
        assert kokoro.default_voice() == "af_nova"

        eleven = create_tts(TTSConfig(backend="elevenlabs", elevenlabs_voice_id="v9"))
        assert eleven.list_voices() == ()
        assert eleven.default_voice() == "v9"
