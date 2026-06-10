"""Optional project configuration for the narration editor.

Unlike the old playlist-driven pipeline, the editor needs no config to run —
sensible defaults (Piper, 1080p) apply out of the box. A ``slidesonnet.toml``
next to the deck can override the TTS backend, voices, video settings, and
pronunciation files.

Example ``slidesonnet.toml``::

    [tts]
    backend = "piper"

    [tts.piper]
    model = "en_US-lessac-medium"

    [video]
    resolution = "1920x1080"
    fps = 24

    [voices.narrator]
    piper = "en_US-lessac-medium"
    elevenlabs = "EXAVITQu4vr4xnSDxMaL"

    pronunciation = ["pronunciation.md"]
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slidesonnet.exceptions import ConfigError
from slidesonnet.models import TTSConfig, VideoConfig, VoiceConfig
from slidesonnet.tts.pronunciation import apply_pronunciation, load_pronunciation_files

CONFIG_FILENAME = "slidesonnet.toml"
_KNOWN_BACKENDS = {"piper", "elevenlabs"}


@dataclass
class Config:
    """Resolved editor configuration."""

    tts: TTSConfig = field(default_factory=TTSConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    voices: dict[str, VoiceConfig] = field(default_factory=dict)
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
        pronunciation_files=[cfg_dir / p for p in raw.get("pronunciation", [])],
    )
    config.pronunciation = load_pronunciation_files(config.pronunciation_files)
    return config


def _parse_tts(raw: dict[str, Any]) -> TTSConfig:
    piper = raw.get("piper", {})
    el = raw.get("elevenlabs", {})
    kwargs: dict[str, Any] = {}
    if "backend" in raw:
        kwargs["backend"] = raw["backend"]
    if "model" in piper:
        kwargs["piper_model"] = str(piper["model"])
    if "speed" in piper:
        kwargs["piper_speed"] = float(piper["speed"])
    for key, target, cast in (
        ("api_key_env", "elevenlabs_api_key_env", str),
        ("voice_id", "elevenlabs_voice_id", str),
        ("model_id", "elevenlabs_model_id", str),
        ("stability", "elevenlabs_stability", float),
        ("similarity_boost", "elevenlabs_similarity_boost", float),
        ("speed", "elevenlabs_speed", float),
    ):
        if key in el:
            kwargs[target] = cast(el[key])
    return TTSConfig(**kwargs)


def _parse_video(raw: dict[str, Any]) -> VideoConfig:
    kwargs: dict[str, Any] = {}
    for key, cast in (
        ("resolution", str),
        ("fps", int),
        ("crf", int),
        ("preset", str),
        ("pad_seconds", float),
        ("pre_silence", float),
        ("tail_seconds", float),
    ):
        if key in raw:
            kwargs[key] = cast(raw[key])
    return VideoConfig(**kwargs)


def _parse_voices(raw: dict[str, Any]) -> dict[str, VoiceConfig]:
    voices: dict[str, VoiceConfig] = {}
    for name, value in raw.items():
        if isinstance(value, str):
            voices[name] = VoiceConfig(
                name=name, backend_voices=dict.fromkeys(_KNOWN_BACKENDS, value)
            )
        elif isinstance(value, dict):
            mapping = {k: str(v) for k, v in value.items() if k in _KNOWN_BACKENDS}
            voices[name] = VoiceConfig(name=name, backend_voices=mapping)
        else:
            raise ConfigError(
                f"voice '{name}' must be a string or table, got {type(value).__name__}"
            )
    return voices
