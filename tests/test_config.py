"""Tests for config validation."""

from pathlib import Path

import pytest

from slidesonnet.config import load_config
from slidesonnet.exceptions import ConfigError
from slidesonnet.models import VideoConfig, VoiceConfig, resolve_voice


def test_load_defaults():
    config = load_config({}, Path("."))
    assert config.title == ""
    assert config.output == ""
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

    assert len(config.pronunciation_files["shared"]) == 2
    assert config.pronunciation_files["shared"][0] == Path("/project/pron/cs.md")


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


def test_output_field_present():
    raw = {"output": "my-lecture.mp4"}
    config = load_config(raw, Path("."))
    assert config.output == "my-lecture.mp4"


def test_output_field_absent():
    config = load_config({}, Path("."))
    assert config.output == ""


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


# -- preset validation -------------------------------------------------------


def test_preset_default():
    vc = VideoConfig()
    assert vc.preset == "medium"


@pytest.mark.parametrize(
    "preset",
    [
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
        "placebo",
    ],
)
def test_preset_valid(preset: str) -> None:
    vc = VideoConfig(preset=preset)
    assert vc.preset == preset


@pytest.mark.parametrize("bad", ["invalid", "MEDIUM", "Ultra", "fastest", ""])
def test_preset_invalid(bad: str) -> None:
    with pytest.raises(ValueError, match="Invalid preset"):
        VideoConfig(preset=bad)


def test_preset_from_yaml():
    raw = {"video": {"preset": "fast"}}
    config = load_config(raw, Path("."))
    assert config.video.preset == "fast"


def test_preset_default_from_yaml():
    config = load_config({}, Path("."))
    assert config.video.preset == "medium"


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


# -- voices.default inheritance into TTS config ------------------------------


def test_voices_default_inherits_piper_model() -> None:
    """voices.default.piper should set tts.piper_model when not explicitly configured."""
    raw = {
        "voices": {
            "default": {"piper": "en_US-amy-medium", "elevenlabs": "voice123"},
        }
    }
    config = load_config(raw, Path("."))
    assert config.tts.piper_model == "en_US-amy-medium"
    assert config.tts.elevenlabs_voice_id == "voice123"


def test_voices_default_does_not_override_explicit_piper_model() -> None:
    """Explicit tts.piper.model takes precedence over voices.default.piper."""
    raw = {
        "tts": {"piper": {"model": "en_US-joe-medium"}},
        "voices": {
            "default": {"piper": "en_US-amy-medium"},
        },
    }
    config = load_config(raw, Path("."))
    assert config.tts.piper_model == "en_US-joe-medium"


def test_voices_default_does_not_override_explicit_elevenlabs_voice() -> None:
    """Explicit tts.elevenlabs.voice_id takes precedence over voices.default.elevenlabs."""
    raw = {
        "tts": {"elevenlabs": {"voice_id": "explicit123"}},
        "voices": {
            "default": {"elevenlabs": "default456"},
        },
    }
    config = load_config(raw, Path("."))
    assert config.tts.elevenlabs_voice_id == "explicit123"


def test_voices_default_string_format_inherits() -> None:
    """voices.default as a plain string should set both backend defaults."""
    raw = {"voices": {"default": "universal-voice"}}
    config = load_config(raw, Path("."))
    assert config.tts.piper_model == "universal-voice"
    assert config.tts.elevenlabs_voice_id == "universal-voice"


def test_voices_default_partial_mapping() -> None:
    """voices.default with only piper mapping should only affect piper."""
    raw = {
        "voices": {
            "default": {"piper": "en_US-amy-medium"},
        }
    }
    config = load_config(raw, Path("."))
    assert config.tts.piper_model == "en_US-amy-medium"
    assert config.tts.elevenlabs_voice_id == ""  # unchanged from default


def test_no_voices_default_keeps_hardcoded_defaults() -> None:
    """Without voices.default, TTS config keeps hardcoded defaults."""
    raw = {"voices": {"alice": {"piper": "en_US-amy-medium"}}}
    config = load_config(raw, Path("."))
    assert config.tts.piper_model == "en_US-lessac-medium"
    assert config.tts.elevenlabs_voice_id == ""


# -- TTS speed parsing ------------------------------------------------------


def test_speed_defaults():
    config = load_config({}, Path("."))
    assert config.tts.piper_speed == 1.0
    assert config.tts.elevenlabs_speed == 1.0


def test_speed_from_yaml():
    raw = {
        "tts": {
            "piper": {"speed": 1.5},
            "elevenlabs": {"speed": 1.1},
        }
    }
    config = load_config(raw, Path("."))
    assert config.tts.piper_speed == 1.5
    assert config.tts.elevenlabs_speed == 1.1


def test_speed_piper_only():
    raw = {"tts": {"piper": {"speed": 2.0}}}
    config = load_config(raw, Path("."))
    assert config.tts.piper_speed == 2.0
    assert config.tts.elevenlabs_speed == 1.0


def test_speed_elevenlabs_only():
    raw = {"tts": {"elevenlabs": {"speed": 0.8}}}
    config = load_config(raw, Path("."))
    assert config.tts.elevenlabs_speed == 0.8
    assert config.tts.piper_speed == 1.0


# -- Pronunciation per-backend format ----------------------------------------


def test_pronunciation_flat_list_backwards_compat() -> None:
    raw = {"pronunciation": ["pron/a.md", "pron/b.md"]}
    config = load_config(raw, Path("/proj"))
    assert config.pronunciation_files == {
        "shared": [Path("/proj/pron/a.md"), Path("/proj/pron/b.md")]
    }


def test_pronunciation_per_backend_format() -> None:
    raw = {
        "pronunciation": {
            "shared": ["pron/names.md"],
            "piper": ["pron/piper-hacks.md"],
            "elevenlabs": ["pron/el-hacks.md"],
        }
    }
    config = load_config(raw, Path("/proj"))
    assert config.pronunciation_files["shared"] == [Path("/proj/pron/names.md")]
    assert config.pronunciation_files["piper"] == [Path("/proj/pron/piper-hacks.md")]
    assert config.pronunciation_files["elevenlabs"] == [Path("/proj/pron/el-hacks.md")]


def test_pronunciation_unknown_key_raises() -> None:
    raw = {"pronunciation": {"shared": ["a.md"], "openai": ["b.md"]}}
    with pytest.raises(ConfigError, match="Unknown pronunciation keys"):
        load_config(raw, Path("."))


def test_pronunciation_empty() -> None:
    config = load_config({}, Path("."))
    assert config.pronunciation_files == {}


def test_pronunciation_for_merges_shared_and_backend() -> None:
    config = load_config({}, Path("."))
    config.pronunciation = {
        "shared": {"Euler": "OY-ler", "Knuth": "kuh-NOOTH"},
        "piper": {"Euler": "OY-lur", "Dijkstra": "DYKE-struh"},
    }
    pron = config.pronunciation_for("piper")
    assert pron["Euler"] == "OY-lur"  # backend overrides shared
    assert pron["Knuth"] == "kuh-NOOTH"  # shared preserved
    assert pron["Dijkstra"] == "DYKE-struh"  # backend-only entry


def test_pronunciation_for_unknown_backend_returns_shared() -> None:
    config = load_config({}, Path("."))
    config.pronunciation = {"shared": {"Euler": "OY-ler"}}
    pron = config.pronunciation_for("unknown_backend")
    assert pron == {"Euler": "OY-ler"}


def test_pronunciation_for_empty() -> None:
    config = load_config({}, Path("."))
    assert config.pronunciation_for("piper") == {}


def test_video_pre_silence() -> None:
    config = load_config({"video": {"pre_silence": 2.5}}, Path("."))
    assert config.video.pre_silence == 2.5


def test_pronunciation_value_not_list_raises() -> None:
    with pytest.raises(ConfigError, match="must be a list of paths"):
        load_config({"pronunciation": {"shared": "not-a-list.md"}}, Path("."))


def test_pronunciation_not_list_or_dict_raises() -> None:
    with pytest.raises(ConfigError, match="must be a list or dict"):
        load_config({"pronunciation": 42}, Path("."))
