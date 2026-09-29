"""Tests for the configuration data models (VoiceConfig, TTSConfig, VideoConfig)."""

from __future__ import annotations

import pytest

from slidesonnet.models import (
    TTSConfig,
    VideoConfig,
    VoiceConfig,
    resolve_voice,
)

_VOICES = {
    "narrator": VoiceConfig(
        name="narrator", backend_voices={"kokoro": "af_bella", "qwen3": "Vivian"}
    )
}


@pytest.mark.parametrize(
    ("preset", "backend", "expected"),
    [
        (None, "kokoro", None),  # default voice
        ("", "kokoro", None),
        ("af_heart", "kokoro", "af_heart"),  # not a preset: a raw backend voice id
        ("narrator", "kokoro", "af_bella"),
        ("narrator", "inworld", None),  # the preset has no mapping for this backend
    ],
)
def test_resolve_voice(preset: str | None, backend: str, expected: str | None) -> None:
    assert resolve_voice(preset, _VOICES, backend) == expected


def test_all_voice_ids() -> None:
    assert _VOICES["narrator"].all_voice_ids() == {"af_bella", "Vivian"}
    assert VoiceConfig(name="empty").all_voice_ids() == set()


@pytest.mark.parametrize(
    ("config", "field", "expected"),
    [
        (TTSConfig(), "backend", "kokoro"),
        (TTSConfig(), "kokoro_voice", "am_echo"),
        (VideoConfig(), "resolution", "1920x1080"),
        (VideoConfig(), "preset", "medium"),
        (VideoConfig(resolution="640x360"), "resolution", "640x360"),
        (VideoConfig(crf=0), "crf", 0),
        (VideoConfig(crf=51), "crf", 51),
        (VideoConfig(pre_silence=0.0), "pre_silence", 0.0),
        (VideoConfig(tail_seconds=0.0), "tail_seconds", 0.0),
    ],
)
def test_defaults_and_boundary_values_accepted(
    config: object, field: str, expected: object
) -> None:
    assert getattr(config, field) == expected


@pytest.mark.parametrize("field", ["kokoro_speed", "inworld_speed"])
@pytest.mark.parametrize("speed", [0.0, -0.5, float("nan"), float("inf")])
def test_tts_speeds_must_be_positive_and_finite(field: str, speed: float) -> None:
    with pytest.raises(ValueError, match=field):
        TTSConfig(**{field: speed})  # type: ignore[arg-type]


class TestVideoConfigValidation:
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


class TestBackendRegistry:
    """The runtime registry and the static Literal must stay in sync."""

    def test_registry_matches_backend_literal(self) -> None:
        from typing import get_args

        from slidesonnet.models import Backend
        from slidesonnet.tts import BACKENDS

        assert set(BACKENDS) == set(get_args(Backend))

    def test_registry_specs(self) -> None:
        from slidesonnet.tts import API_BACKENDS, BACKENDS

        assert API_BACKENDS == {"inworld"}
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
