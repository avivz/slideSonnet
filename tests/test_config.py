"""Tests for the optional TOML editor config."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.config import Config, default_config_path, load_config
from slidesonnet.exceptions import ConfigError


def test_missing_config_is_all_defaults(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pdf"
    cfg = load_config(deck)
    assert cfg.tts.backend == "kokoro"
    assert cfg.video.resolution == "1920x1080"
    assert cfg.voices == {}


def test_default_config_path(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pdf"
    assert default_config_path(deck) == tmp_path / "slidesonnet.toml"


def test_load_overrides(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text(
        """
[tts]
backend = "elevenlabs"

[tts.kokoro]
voice = "bm_george"

[video]
resolution = "1280x720"
fps = 30

[voices.narrator]
kokoro = "am_adam"
elevenlabs = "abc123"
""",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.tts.backend == "elevenlabs"
    assert cfg.tts.kokoro_voice == "bm_george"
    assert cfg.video.resolution == "1280x720"
    assert cfg.video.fps == 30
    assert cfg.voices["narrator"].resolve("kokoro") == "am_adam"
    assert cfg.voices["narrator"].resolve("elevenlabs") == "abc123"


def test_pronunciation_loaded_and_applied(tmp_path: Path) -> None:
    (tmp_path / "pron.md").write_text("**Euler**: OY-ler\n", encoding="utf-8")
    (tmp_path / "slidesonnet.toml").write_text('pronunciation = ["pron.md"]\n', encoding="utf-8")
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.apply_pronunciation("Euler summed") == "OY-ler summed"


def test_flat_voice_string(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text('[voices]\nalice = "af_bella"\n', encoding="utf-8")
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.voices["alice"].resolve("kokoro") == "af_bella"
    assert cfg.voices["alice"].resolve("elevenlabs") == "af_bella"


def test_config_dataclass_defaults() -> None:
    assert Config().tts.backend == "kokoro"


def test_invalid_toml_raises_config_error(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text("tts = [broken\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid TOML"):
        load_config(tmp_path / "deck.pdf")


def test_elevenlabs_settings_parsed(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text(
        """
[tts.elevenlabs]
api_key_env = "MY_KEY"
voice_id = "v123"
model_id = "eleven_turbo_v2"
stability = 0.3
similarity_boost = 0.9
speed = 1.1
""",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.tts.elevenlabs_api_key_env == "MY_KEY"
    assert cfg.tts.elevenlabs_voice_id == "v123"
    assert cfg.tts.elevenlabs_model_id == "eleven_turbo_v2"
    assert cfg.tts.elevenlabs_stability == 0.3
    assert cfg.tts.elevenlabs_similarity_boost == 0.9
    assert cfg.tts.elevenlabs_speed == 1.1


def test_qwen3_settings_parsed_and_prompt_resolved(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text(
        """
[tts]
backend = "qwen3"

[tts.qwen3]
model = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
device = "cuda"
language = "English"
voice_prompt = "voices/me.pt"
""",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.tts.backend == "qwen3"
    assert cfg.tts.qwen3_model == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert cfg.tts.qwen3_device == "cuda"
    # The voice-prompt path is resolved relative to the config dir (portable deck).
    assert cfg.tts.qwen3_voice_prompt == str((tmp_path / "voices" / "me.pt").resolve())


def test_qwen3_invalid_device_raises(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text('[tts.qwen3]\ndevice = "tpu"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="qwen3_device must be one of"):
        load_config(tmp_path / "deck.pdf")


def test_invalid_voice_value_raises(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text("[voices]\nalice = 3\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a string or table"):
        load_config(tmp_path / "deck.pdf")


def test_unknown_voice_table_key_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A key misplaced under [voices.x] (e.g. top-level `pronunciation` written
    after a table header) must not vanish silently."""
    (tmp_path / "slidesonnet.toml").write_text(
        '[voices.alex]\nkokoro = "am_michael"\npronunciation = ["pron.md"]\n',
        encoding="utf-8",
    )
    with caplog.at_level("WARNING"):
        load_config(tmp_path / "deck.pdf")
    assert any("pronunciation" in r.message and "alex" in r.message for r in caplog.records)


EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.mark.parametrize("deck", ["showcase/showcase.pdf", "basel-problem/basel-problem.pdf"])
def test_example_deck_pronunciation_is_wired(deck: str) -> None:
    """Guard the bundled demos: their pronunciation dictionaries must load.

    (Both once had `pronunciation = [...]` after a [voices.x] table header,
    which TOML scopes to that table — the dictionaries silently never loaded.)
    """
    cfg = load_config(EXAMPLES / deck)
    assert cfg.pronunciation, f"{deck}: no pronunciation entries loaded"
