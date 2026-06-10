"""Tests for the optional TOML editor config."""

from __future__ import annotations

from pathlib import Path

from slidesonnet.config import Config, default_config_path, load_config


def test_missing_config_is_all_defaults(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pdf"
    cfg = load_config(deck)
    assert cfg.tts.backend == "piper"
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

[tts.piper]
model = "en_GB-alan-medium"

[video]
resolution = "1280x720"
fps = 30

[voices.narrator]
piper = "en_US-lessac-high"
elevenlabs = "abc123"
""",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.tts.backend == "elevenlabs"
    assert cfg.tts.piper_model == "en_GB-alan-medium"
    assert cfg.video.resolution == "1280x720"
    assert cfg.video.fps == 30
    assert cfg.voices["narrator"].resolve("piper") == "en_US-lessac-high"
    assert cfg.voices["narrator"].resolve("elevenlabs") == "abc123"


def test_pronunciation_loaded_and_applied(tmp_path: Path) -> None:
    (tmp_path / "pron.md").write_text("**Euler**: OY-ler\n", encoding="utf-8")
    (tmp_path / "slidesonnet.toml").write_text('pronunciation = ["pron.md"]\n', encoding="utf-8")
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.apply_pronunciation("Euler summed") == "OY-ler summed"


def test_flat_voice_string(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text(
        '[voices]\nalice = "en_US-amy-medium"\n', encoding="utf-8"
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.voices["alice"].resolve("piper") == "en_US-amy-medium"
    assert cfg.voices["alice"].resolve("elevenlabs") == "en_US-amy-medium"


def test_config_dataclass_defaults() -> None:
    assert Config().tts.backend == "piper"
