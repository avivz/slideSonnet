"""Tests for the configuration data models (VoiceConfig, TTSConfig, VideoConfig)."""

from __future__ import annotations

from typing import ClassVar

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
        assert vc.resolve("inworld") is None

    def test_all_voice_ids(self) -> None:
        vc = VoiceConfig(
            name="narrator",
            backend_voices={"kokoro": "af_heart", "inworld": "Ashley"},
        )
        assert vc.all_voice_ids() == {"af_heart", "Ashley"}

    def test_all_voice_ids_empty(self) -> None:
        assert VoiceConfig(name="narrator").all_voice_ids() == set()


class TestResolveVoice:
    VOICES: ClassVar[dict[str, VoiceConfig]] = {
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
        assert resolve_voice("narrator", self.VOICES, "inworld") is None


class TestAPIBackends:
    def test_inworld_is_api_kokoro_is_not(self) -> None:
        from slidesonnet.tts import API_BACKENDS

        assert "inworld" in API_BACKENDS
        assert "kokoro" not in API_BACKENDS


class TestTTSConfigValidation:
    def test_defaults_are_valid(self) -> None:
        cfg = TTSConfig()
        assert cfg.backend == "kokoro"
        assert cfg.kokoro_voice == "am_echo"

    @pytest.mark.parametrize("field", ["kokoro_speed", "inworld_speed"])
    @pytest.mark.parametrize("speed", [0.0, -0.5, float("nan"), float("inf")])
    def test_speeds_must_be_positive_and_finite(self, field: str, speed: float) -> None:
        with pytest.raises(ValueError, match=field):
            TTSConfig(**{field: speed})  # type: ignore[arg-type]


class TestVideoConfigValidation:
    def test_defaults_are_valid(self) -> None:
        cfg = VideoConfig()
        assert cfg.resolution == "1920x1080"
        assert cfg.preset == "medium"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            *[("resolution", r) for r in ["1920", "1920x", "x1080", "fullhd", "1920X1080"]],
            *[("resolution", r) for r in ["0x1080", "1920x0", "1921x1080", "1920x1081"]],
            ("fps", 0),
            ("fps", -24),
            ("crf", -1),
            ("crf", 52),
            ("preset", "warp9"),
            *[("pre_silence", v) for v in [-0.1, float("nan"), float("inf")]],
            *[("tail_seconds", v) for v in [-0.1, float("nan"), float("inf")]],
        ],
    )
    def test_invalid_values_name_the_field(self, field: str, value: object) -> None:
        with pytest.raises(ValueError, match=field):
            VideoConfig(**{field: value})  # type: ignore[arg-type]

    def test_boundary_values_accepted(self) -> None:
        cfg = VideoConfig(resolution="640x360", crf=0)
        assert (cfg.resolution, cfg.crf, VideoConfig(crf=51).crf) == ("640x360", 0, 51)

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
        inworld = BACKENDS["inworld"]
        qwen3 = BACKENDS["qwen3"]
        assert (kokoro.extension, kokoro.paid, kokoro.realtime) == (".wav", False, True)
        assert (inworld.extension, inworld.paid, inworld.realtime) == (".mp3", True, True)
        # Qwen3 is free local audio (.wav, not paid) but too slow to auto-generate.
        assert (qwen3.extension, qwen3.paid, qwen3.realtime) == (".wav", False, False)

    def test_available_backends_filters_to_installed(self) -> None:
        import importlib.util

        from slidesonnet.tts import BACKENDS, available_backends

        # Every spec names the import that gates its availability.
        assert all(spec.import_name for spec in BACKENDS.values())
        avail = available_backends()
        assert set(avail) <= set(BACKENDS)
        # A backend is offered iff its import is present — env-independent (CI
        # installs neither the kokoro nor the qwen3 extra; local dev has kokoro).
        for name, spec in BACKENDS.items():
            present = importlib.util.find_spec(spec.import_name) is not None
            assert (name in avail) == present

    def test_engine_voice_introspection(self) -> None:
        from slidesonnet.models import TTSConfig
        from slidesonnet.tts import create_tts
        from slidesonnet.tts.kokoro import KOKORO_VOICES

        kokoro = create_tts(TTSConfig(backend="kokoro", kokoro_voice="af_nova"))
        assert kokoro.list_voices() == KOKORO_VOICES
        assert kokoro.default_voice() == "af_nova"

        inworld = create_tts(TTSConfig(backend="inworld", inworld_voice="Ashley"))
        assert inworld.list_voices() == ()
        assert inworld.default_voice() == "Ashley"
