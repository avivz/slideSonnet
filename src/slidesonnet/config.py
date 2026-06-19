"""Optional project configuration for the narration editor.

Unlike the old playlist-driven pipeline, the editor needs no config to run —
sensible defaults (Kokoro, 1080p) apply out of the box. A ``slidesonnet.toml``
next to the deck can override the TTS backend, voices, video settings, and
pronunciation files.

Example ``slidesonnet.toml``::

    [tts]
    backend = "kokoro"

    [tts.kokoro]
    voice = "af_heart"

    [video]
    resolution = "1920x1080"
    fps = 24

    [voices.narrator]
    kokoro = "af_heart"
    inworld = "Ashley"

    [logging]
    file = ".slidesonnet/slidesonnet.log"  # or false to disable the run log
    level = "DEBUG"                          # file detail level; console obeys -v/-q
    max_bytes = 2_000_000                    # rotate past ~2 MB
    backup_count = 3                         # keep slidesonnet.log.1 .. .3

    pronunciation = ["pronunciation.md"]
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slidesonnet.exceptions import ConfigError
from slidesonnet.tts import BACKENDS
from slidesonnet.models import LoggingConfig, TTSConfig, VideoConfig, VoiceConfig
from slidesonnet.tts.pronunciation import apply_pronunciation, load_pronunciation_files

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "slidesonnet.toml"
_KNOWN_BACKENDS = frozenset(BACKENDS)


@dataclass
class Config:
    """Resolved editor configuration."""

    tts: TTSConfig = field(default_factory=TTSConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    voices: dict[str, VoiceConfig] = field(default_factory=dict)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    pronunciation_files: list[Path] = field(default_factory=list)
    pronunciation: dict[str, str] = field(default_factory=dict)

    def apply_pronunciation(self, text: str) -> str:
        """Apply the merged pronunciation dictionary to *text*."""
        return apply_pronunciation(text, self.pronunciation)


def default_config_path(deck_path: Path) -> Path:
    """Where the config for *deck_path* would live (its directory)."""
    return deck_path.resolve().parent / CONFIG_FILENAME


def load_config(deck_path: Path, *, config_path: Path | None = None) -> Config:
    """Load config for *deck_path*.

    Uses *config_path* if given, else ``slidesonnet.toml`` beside the deck if it
    exists, else all-defaults. Pronunciation files are loaded and merged.
    """
    path = config_path or default_config_path(deck_path)
    if not path.exists():
        return Config()

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {path}: {e}") from e

    cfg_dir = path.resolve().parent
    config = Config(
        tts=_parse_tts(raw.get("tts", {})),
        video=_parse_video(raw.get("video", {})),
        voices=_parse_voices(raw.get("voices", {})),
        logging=_parse_logging(raw.get("logging", {}), cfg_dir),
        pronunciation_files=[cfg_dir / p for p in raw.get("pronunciation", [])],
    )
    # The Qwen3 voice prompt is a file path; resolve it relative to the config
    # so a deck stays portable (paths in the toml are relative to the toml).
    if config.tts.qwen3_voice_prompt:
        config.tts.qwen3_voice_prompt = str((cfg_dir / config.tts.qwen3_voice_prompt).resolve())
    config.pronunciation = load_pronunciation_files(config.pronunciation_files)
    return config


def _parse_tts(raw: dict[str, Any]) -> TTSConfig:
    kokoro = raw.get("kokoro", {})
    qwen3 = raw.get("qwen3", {})
    inworld = raw.get("inworld", {})
    kwargs: dict[str, Any] = {}
    if "backend" in raw:
        kwargs["backend"] = raw["backend"]
    if "voice" in kokoro:
        kwargs["kokoro_voice"] = str(kokoro["voice"])
    if "speed" in kokoro:
        kwargs["kokoro_speed"] = float(kokoro["speed"])
    for key, target in (
        ("model", "qwen3_model"),
        ("device", "qwen3_device"),
        ("voice_prompt", "qwen3_voice_prompt"),
        ("language", "qwen3_language"),
    ):
        if key in qwen3:
            kwargs[target] = str(qwen3[key])
    for key, target, cast in (
        ("api_key_env", "inworld_api_key_env", str),
        ("voice", "inworld_voice", str),
        ("model", "inworld_model", str),
        ("speed", "inworld_speed", float),
    ):
        if key in inworld:
            kwargs[target] = cast(inworld[key])
    return TTSConfig(**kwargs)


def _parse_video(raw: dict[str, Any]) -> VideoConfig:
    kwargs: dict[str, Any] = {}
    for key, cast in (
        ("resolution", str),
        ("fps", int),
        ("crf", int),
        ("preset", str),
        ("pre_silence", float),
        ("tail_seconds", float),
    ):
        if key in raw:
            kwargs[key] = cast(raw[key])
    return VideoConfig(**kwargs)


def _parse_logging(raw: dict[str, Any], cfg_dir: Path) -> LoggingConfig:
    kwargs: dict[str, Any] = {}
    file = raw.get("file")
    if file is False:
        # `file = false` turns the log file off entirely.
        kwargs["enabled"] = False
    elif isinstance(file, str):
        # A relative path is relative to the config, so a deck stays portable.
        kwargs["file"] = str((cfg_dir / file).resolve())
    if "level" in raw:
        kwargs["level"] = str(raw["level"])
    if "max_bytes" in raw:
        kwargs["max_bytes"] = int(raw["max_bytes"])
    if "backup_count" in raw:
        kwargs["backup_count"] = int(raw["backup_count"])
    try:
        return LoggingConfig(**kwargs)
    except ValueError as e:
        raise ConfigError(f"slidesonnet.toml [logging]: {e}") from e


def _parse_voices(raw: dict[str, Any]) -> dict[str, VoiceConfig]:
    voices: dict[str, VoiceConfig] = {}
    for name, value in raw.items():
        if isinstance(value, str):
            voices[name] = VoiceConfig(
                name=name, backend_voices=dict.fromkeys(_KNOWN_BACKENDS, value)
            )
        elif isinstance(value, dict):
            mapping = {k: str(v) for k, v in value.items() if k in _KNOWN_BACKENDS}
            for stray in value.keys() - _KNOWN_BACKENDS:
                # TOML scopes everything after a [table] header to that table,
                # so a top-level key written below [voices.x] lands here
                logger.warning(
                    "slidesonnet.toml: ignoring unknown key '%s' in [voices.%s] — "
                    "if it's meant to be a top-level setting (e.g. 'pronunciation'), "
                    "move it above the table headers",
                    stray,
                    name,
                )
            voices[name] = VoiceConfig(name=name, backend_voices=mapping)
        else:
            raise ConfigError(
                f"voice '{name}' must be a string or table, got {type(value).__name__}"
            )
    return voices
