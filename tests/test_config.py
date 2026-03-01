"""Tests for config validation."""

from pathlib import Path

import pytest

from slidesonnet.config import load_config
from slidesonnet.models import VideoConfig, VoiceConfig, resolve_voice


def test_load_defaults():
    config = load_config({}, Path("."))
    assert config.title == ""
    assert config.tts.backend == "piper"
    assert config.tts.piper_model == "en_US-lessac-medium"
    assert config.video.resolution == "1920x1080"
    assert config.video.fps == 24
    assert config.video.silence_duration == 3.0


def test_load_full_config():
    raw = {
        "title": "Test Lecture",
        "tts": {
            "backend": "elevenlabs",
            "piper": {"model": "en_US-amy-medium"},
            "elevenlabs": {
                "api_key_env": "MY_KEY",
                "voice_id": "abc123",
                "model_id": "eleven_v2",
                "stability": 0.7,
                "similarity_boost": 0.9,
            },
        },
        "video": {
            "resolution": "1280x720",
            "fps": 30,
            "crf": 18,
            "pad_seconds": 1.0,
            "silence_duration": 5.0,
        },
        "voices": {
            "default": "en_US-lessac-medium",
            "alice": "en_US-amy-medium",
        },
        "pronunciation": ["pron/cs.md", "pron/math.md"],
    }
    config = load_config(raw, Path("/project"))

    assert config.title == "Test Lecture"
    assert config.tts.backend == "elevenlabs"
    assert config.tts.piper_model == "en_US-amy-medium"
    assert config.tts.elevenlabs_voice_id == "abc123"
    assert config.tts.elevenlabs_stability == 0.7
    assert config.video.resolution == "1280x720"
    assert config.video.fps == 30
    assert config.video.silence_duration == 5.0

    assert "default" in config.voices
    assert config.voices["alice"].resolve("piper") == "en_US-amy-medium"
    assert config.voices["alice"].resolve("elevenlabs") == "en_US-amy-medium"

    assert len(config.pronunciation_files) == 2
    assert config.pronunciation_files[0] == Path("/project/pron/cs.md")


def test_voices_string_format():
    raw = {"voices": {"default": "model-a", "bob": "model-b"}}
    config = load_config(raw, Path("."))
    assert config.voices["default"].resolve("piper") == "model-a"
    assert config.voices["default"].resolve("elevenlabs") == "model-a"
    assert config.voices["bob"].resolve("piper") == "model-b"


def test_voices_dict_format():
    raw = {"voices": {"default": {"backend_voice": "model-a"}}}
    config = load_config(raw, Path("."))
    assert config.voices["default"].resolve("piper") == "model-a"
    assert config.voices["default"].resolve("elevenlabs") == "model-a"


def test_voices_per_backend_format():
    raw = {
        "voices": {
            "narrator": {
                "piper": "en_US-amy-medium",
                "elevenlabs": "21m00Tcm4TlvDq8ikWAM",
            }
        }
    }
    config = load_config(raw, Path("."))
    assert config.voices["narrator"].resolve("piper") == "en_US-amy-medium"
    assert config.voices["narrator"].resolve("elevenlabs") == "21m00Tcm4TlvDq8ikWAM"
    assert config.voices["narrator"].resolve("unknown") is None


def test_crossfade_default():
    config = load_config({}, Path("."))
    assert config.video.crossfade == 0.5


def test_crossfade_custom():
    raw = {"video": {"crossfade": 0.8}}
    config = load_config(raw, Path("."))
    assert config.video.crossfade == 0.8


def test_crossfade_zero():
    raw = {"video": {"crossfade": 0}}
    config = load_config(raw, Path("."))
    assert config.video.crossfade == 0.0


def test_resolution_valid():
    vc = VideoConfig(resolution="1280x720")
    assert vc.resolution == "1280x720"


@pytest.mark.parametrize("bad", ["1920", "abc", "1920X1080", "x1080", "1920x", ""])
def test_resolution_invalid(bad: str) -> None:
    with pytest.raises(ValueError, match="Invalid resolution"):
        VideoConfig(resolution=bad)


# -- resolve_voice ----------------------------------------------------------


def _make_voices() -> dict[str, VoiceConfig]:
    return {
        "narrator": VoiceConfig(
            name="narrator",
            backend_voices={"piper": "en_US-amy-medium", "elevenlabs": "abc123"},
        ),
        "robot": VoiceConfig(
            name="robot",
            backend_voices={"piper": "en_US-lessac-medium"},
        ),
    }


def test_resolve_voice_known_preset() -> None:
    voices = _make_voices()
    assert resolve_voice("narrator", voices, "piper") == "en_US-amy-medium"
    assert resolve_voice("narrator", voices, "elevenlabs") == "abc123"


def test_resolve_voice_unknown_preset() -> None:
    voices = _make_voices()
    assert resolve_voice("nonexistent", voices, "piper") is None


def test_resolve_voice_unmapped_backend() -> None:
    voices = _make_voices()
    assert resolve_voice("robot", voices, "elevenlabs") is None


def test_resolve_voice_none_preset() -> None:
    voices = _make_voices()
    assert resolve_voice(None, voices, "piper") is None


# -- VoiceConfig.all_voice_ids ----------------------------------------------


def test_all_voice_ids() -> None:
    vc = VoiceConfig(
        name="narrator",
        backend_voices={"piper": "en_US-amy-medium", "elevenlabs": "abc123"},
    )
    assert vc.all_voice_ids() == {"en_US-amy-medium", "abc123"}
