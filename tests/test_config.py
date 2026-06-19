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
    assert cfg.logging.enabled is True
    assert cfg.logging.file is None


def test_logging_section_overrides(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text(
        """
[logging]
file = "logs/run.log"
level = "INFO"
max_bytes = 5000
backup_count = 1
""",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.logging.enabled is True
    # A relative path is resolved against the config dir, like other path settings.
    assert cfg.logging.file == str((tmp_path / "logs/run.log").resolve())
    assert cfg.logging.level == "INFO"
    assert cfg.logging.max_bytes == 5000
    assert cfg.logging.backup_count == 1


def test_logging_can_be_disabled(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text("[logging]\nfile = false\n", encoding="utf-8")
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.logging.enabled is False


def test_default_config_path(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pdf"
    assert default_config_path(deck) == tmp_path / "slidesonnet.toml"


def test_load_overrides(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text(
        """
[tts]
backend = "inworld"

[tts.kokoro]
voice = "bm_george"

[video]
resolution = "1280x720"
fps = 30

[voices.narrator]
kokoro = "am_adam"
inworld = "abc123"
""",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.tts.backend == "inworld"
    assert cfg.tts.kokoro_voice == "bm_george"
    assert cfg.video.resolution == "1280x720"
    assert cfg.video.fps == 30
    assert cfg.voices["narrator"].resolve("kokoro") == "am_adam"
    assert cfg.voices["narrator"].resolve("inworld") == "abc123"


def test_pronunciation_loaded_and_applied(tmp_path: Path) -> None:
    (tmp_path / "pron.md").write_text("**Euler**: OY-ler\n", encoding="utf-8")
    (tmp_path / "slidesonnet.toml").write_text('pronunciation = ["pron.md"]\n', encoding="utf-8")
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.apply_pronunciation("Euler summed") == "OY-ler summed"


def test_flat_voice_string(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text('[voices]\nalice = "af_bella"\n', encoding="utf-8")
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.voices["alice"].resolve("kokoro") == "af_bella"
    assert cfg.voices["alice"].resolve("inworld") == "af_bella"


def test_config_dataclass_defaults() -> None:
    assert Config().tts.backend == "kokoro"


def test_invalid_toml_raises_config_error(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text("tts = [broken\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid TOML"):
        load_config(tmp_path / "deck.pdf")


def test_inworld_settings_parsed(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text(
        """
[tts.inworld]
api_key_env = "MY_INWORLD_KEY"
voice = "Ashley"
model = "inworld-tts-1.5-mini"
speed = 1.2
""",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.tts.inworld_api_key_env == "MY_INWORLD_KEY"
    assert cfg.tts.inworld_voice == "Ashley"
    assert cfg.tts.inworld_model == "inworld-tts-1.5-mini"
    assert cfg.tts.inworld_speed == 1.2


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
