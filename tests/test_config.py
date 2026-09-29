"""Tests for the optional TOML editor config."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.config import Config, default_config_path, load_config
from slidesonnet.exceptions import ConfigError
from slidesonnet.models import TTSConfig


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
temperature = 0.7
delivery_mode = "Creative"
language = "en-US"
text_normalization = false
send_direction = true
""",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.tts.inworld_api_key_env == "MY_INWORLD_KEY"
    assert cfg.tts.inworld_voice == "Ashley"
    assert cfg.tts.inworld_model == "inworld-tts-1.5-mini"
    assert cfg.tts.inworld_speed == 1.2
    assert cfg.tts.inworld_temperature == 0.7
    assert cfg.tts.inworld_delivery_mode == "creative"
    assert cfg.tts.inworld_language == "en-US"
    assert cfg.tts.inworld_text_normalization is False
    assert cfg.tts.inworld_send_direction is True
    assert TTSConfig().inworld_send_direction is False  # opt-in: old decks sound the same


def test_blank_inworld_delivery_settings_mean_unset(tmp_path: Path) -> None:
    """An empty value is the same as leaving the key out (so no clip re-keys)."""
    (tmp_path / "slidesonnet.toml").write_text(
        '[tts.inworld]\ndelivery_mode = ""\nlanguage = " "\n', encoding="utf-8"
    )
    tts = load_config(tmp_path / "deck.pdf").tts
    assert (tts.inworld_delivery_mode, tts.inworld_language) == (None, None)


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


@pytest.mark.parametrize(
    ("toml", "match"),
    [
        ('[tts.qwen3]\ndevice = "tpu"\n', r"\[tts\].*qwen3_device must be one of"),
        ("[tts.kokoro]\nspeed = nan\n", r"\[tts\.kokoro\] speed"),
        ("[tts.inworld]\nspeed = inf\n", r"\[tts\.inworld\] speed"),
        ("[tts.inworld]\ntemperature = 2.5\n", r"\[tts\].*temperature"),
        ("[tts.inworld]\ntemperature = 0\n", r"\[tts\].*temperature"),
        ('[tts.inworld]\ndelivery_mode = "wild"\n', r"\[tts\].*delivery_mode"),
        ('[tts.inworld]\ntext_normalization = "on"\n', r"\[tts\.inworld\] text_normalization"),
        ("[video]\npre_silence = nan\n", r"\[video\] pre_silence"),
        ("[video]\ntail_seconds = inf\n", r"\[video\] tail_seconds"),
        ("[video]\ntail_seconds = -1.0\n", r"\[video\].*tail_seconds"),
        ("[video]\nfps = inf\n", r"\[video\] fps"),
        ("[video]\nfps = 29.97\n", r"\[video\] fps"),
        ("[video]\nfps = true\n", r"\[video\] fps"),
        ('[video]\nfps = "fast"\n', r"\[video\] fps"),
        ("[video]\ncrf = 52\n", r"\[video\].*crf"),
        ('[video]\nresolution = "0x1080"\n', r"\[video\].*resolution"),
        ('[video]\nresolution = "1921x1080"\n', r"\[video\].*resolution.*even"),
        ('[video]\nkeep_scratch = "false"\n', r"\[video\] keep_scratch"),
        ("[video]\nkeep_scratch = 1\n", r"\[video\] keep_scratch"),
        ("[logging]\nmax_bytes = 1.5\n", r"\[logging\] max_bytes"),
    ],
)
def test_bad_settings_are_a_config_error_naming_the_key(
    tmp_path: Path, toml: str, match: str
) -> None:
    (tmp_path / "slidesonnet.toml").write_text(toml, encoding="utf-8")
    with pytest.raises(ConfigError, match=match):
        load_config(tmp_path / "deck.pdf")


def test_video_settings_parse_strictly_typed(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text(
        "[video]\nfps = 30.0\ncrf = 0\npre_silence = 1\nkeep_scratch = true\n", encoding="utf-8"
    )
    video = load_config(tmp_path / "deck.pdf").video
    assert (video.fps, video.crf, video.pre_silence, video.keep_scratch) == (30, 0, 1.0, True)


def test_explicit_config_path_must_exist(tmp_path: Path) -> None:
    missing = tmp_path / "nope.toml"
    with pytest.raises(ConfigError, match="nope.toml"):
        load_config(tmp_path / "deck.pdf", config_path=missing)


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


def test_cache_audio_dir_is_relative_to_the_toml(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text(
        '[cache]\naudio_dir = "../shared-audio"\n', encoding="utf-8"
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.audio_dir == (tmp_path / ".." / "shared-audio").resolve()


def test_cache_audio_dir_expands_tilde(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "slidesonnet.toml").write_text(
        '[cache]\naudio_dir = "~/.cache/slidesonnet/aicode"\n', encoding="utf-8"
    )
    cfg = load_config(tmp_path / "deck.pdf")
    assert cfg.audio_dir == tmp_path / ".cache" / "slidesonnet" / "aicode"


def test_no_cache_table_means_no_pool(tmp_path: Path) -> None:
    (tmp_path / "slidesonnet.toml").write_text("[video]\nfps = 30\n", encoding="utf-8")
    assert load_config(tmp_path / "deck.pdf").audio_dir is None
