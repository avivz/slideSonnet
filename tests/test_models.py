"""Tests for __post_init__ validation in models.py dataclasses."""

import pytest

from slidesonnet.models import SlideNarration, TTSConfig, VideoConfig


@pytest.mark.parametrize(
    "field, value, match",
    [
        ("fps", 0, "fps must be positive"),
        ("fps", -1, "fps must be positive"),
        ("crf", -1, "crf must be non-negative"),
        ("pad_seconds", -0.5, "pad_seconds must be non-negative"),
        ("pre_silence", -0.1, "pre_silence must be non-negative"),
        ("silence_duration", -1.0, "silence_duration must be non-negative"),
        ("crossfade", -0.5, "crossfade must be non-negative"),
    ],
)
def test_video_config_negative_values(field: str, value: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        VideoConfig(**{field: value})


def test_video_config_zero_boundary_accepted() -> None:
    vc = VideoConfig(crf=0, pad_seconds=0, pre_silence=0, silence_duration=0, crossfade=0)
    assert vc.crf == 0
    assert vc.pad_seconds == 0


@pytest.mark.parametrize(
    "field, value",
    [
        ("elevenlabs_stability", -0.1),
        ("elevenlabs_stability", 1.1),
        ("elevenlabs_similarity_boost", -0.01),
        ("elevenlabs_similarity_boost", 1.5),
    ],
)
def test_tts_config_out_of_range(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        TTSConfig(**{field: value})


def test_tts_config_boundary_values() -> None:
    tc = TTSConfig(elevenlabs_stability=0.0, elevenlabs_similarity_boost=1.0)
    assert tc.elevenlabs_stability == 0.0
    assert tc.elevenlabs_similarity_boost == 1.0


def test_slide_narration_image_index_defaults_to_index() -> None:
    sn = SlideNarration(index=5)
    assert sn.image_index == 5


def test_slide_narration_image_index_explicit_kept() -> None:
    sn = SlideNarration(index=5, image_index=3)
    assert sn.image_index == 3


def test_slide_narration_silence_override_negative_raises() -> None:
    with pytest.raises(ValueError, match="silence_override must be non-negative"):
        SlideNarration(index=1, silence_override=-1.0)


def test_slide_narration_silence_override_zero_accepted() -> None:
    sn = SlideNarration(index=1, silence_override=0.0)
    assert sn.silence_override == 0.0
