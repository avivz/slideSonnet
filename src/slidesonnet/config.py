"""Configuration loading and validation from playlist YAML."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from slidesonnet.exceptions import ConfigError
from slidesonnet.models import ProjectConfig, TTSConfig, VideoConfig, VoiceConfig


def load_config(raw: dict[str, Any], playlist_dir: Path) -> ProjectConfig:
    """Build a validated ProjectConfig from a raw YAML dict.

    Args:
        raw: Parsed YAML config dict.
        playlist_dir: Directory containing the playlist file (for resolving paths).
    """
    raw_tts = raw.get("tts", {})
    tts = _parse_tts(raw_tts)
    video = _parse_video(raw.get("video", {}))
    voices = _parse_voices(raw.get("voices", {}))
    pronunciation_files = _parse_pronunciation_paths(raw.get("pronunciation", []), playlist_dir)

    # Inherit engine defaults from voices.default when not explicitly set in YAML
    if "default" in voices:
        default_voice = voices["default"]
        piper_explicitly_set = "model" in raw_tts.get("piper", {})
        if not piper_explicitly_set:
            resolved = default_voice.resolve("piper")
            if resolved:
                tts.piper_model = resolved
        el_explicitly_set = "voice_id" in raw_tts.get("elevenlabs", {})
        if not el_explicitly_set:
            resolved = default_voice.resolve("elevenlabs")
            if resolved:
                tts.elevenlabs_voice_id = resolved

    return ProjectConfig(
        title=raw.get("title", ""),
        output=raw.get("output", ""),
        tts=tts,
        video=video,
        voices=voices,
        pronunciation_files=pronunciation_files,
    )


def _pick(
    raw: dict[str, Any],
    source_key: str,
    kwargs: dict[str, Any],
    target_key: str,
    cast: Callable[[Any], Any] = lambda x: x,
) -> None:
    """If *source_key* is in *raw*, copy its casted value into *kwargs[target_key]*."""
    if source_key in raw:
        kwargs[target_key] = cast(raw[source_key])


def _parse_tts(raw: dict[str, Any]) -> TTSConfig:
    piper = raw.get("piper", {})
    el = raw.get("elevenlabs", {})

    kwargs: dict[str, Any] = {}
    _pick(raw, "backend", kwargs, "backend")
    _pick(piper, "model", kwargs, "piper_model")
    _pick(piper, "speed", kwargs, "piper_speed", float)
    _pick(el, "api_key_env", kwargs, "elevenlabs_api_key_env")
    _pick(el, "voice_id", kwargs, "elevenlabs_voice_id")
    _pick(el, "model_id", kwargs, "elevenlabs_model_id")
    _pick(el, "stability", kwargs, "elevenlabs_stability", float)
    _pick(el, "similarity_boost", kwargs, "elevenlabs_similarity_boost", float)
    _pick(el, "speed", kwargs, "elevenlabs_speed", float)
    return TTSConfig(**kwargs)


def _parse_video(raw: dict[str, Any]) -> VideoConfig:
    kwargs: dict[str, Any] = {}
    _pick(raw, "resolution", kwargs, "resolution")
    _pick(raw, "fps", kwargs, "fps", int)
    _pick(raw, "crf", kwargs, "crf", int)
    _pick(raw, "pad_seconds", kwargs, "pad_seconds", float)
    _pick(raw, "pre_silence", kwargs, "pre_silence", float)
    _pick(raw, "silence_duration", kwargs, "silence_duration", float)
    _pick(raw, "preset", kwargs, "preset", str)
    _pick(raw, "crossfade", kwargs, "crossfade", float)
    return VideoConfig(**kwargs)


_KNOWN_BACKENDS = {"piper", "elevenlabs"}


def _parse_voices(raw: dict[str, Any]) -> dict[str, VoiceConfig]:
    voices: dict[str, VoiceConfig] = {}
    for name, value in raw.items():
        if isinstance(value, str):
            # Flat string → use for all backends
            voices[name] = VoiceConfig(
                name=name,
                backend_voices={b: value for b in _KNOWN_BACKENDS},
            )
        elif isinstance(value, dict):
            if set(value.keys()) & _KNOWN_BACKENDS:
                # Per-backend mapping: {piper: ..., elevenlabs: ...}
                voices[name] = VoiceConfig(
                    name=name,
                    backend_voices={k: str(v) for k, v in value.items() if k in _KNOWN_BACKENDS},
                )
            else:
                # Legacy dict format: {backend_voice: ..., model: ...}
                backend_voice = str(value.get("backend_voice", value.get("model", "")))
                voices[name] = VoiceConfig(
                    name=name,
                    backend_voices={b: backend_voice for b in _KNOWN_BACKENDS},
                )
    return voices


_PRONUNCIATION_KEYS = {"shared"} | _KNOWN_BACKENDS


def _parse_pronunciation_paths(
    raw: list[Any] | dict[str, Any] | None, playlist_dir: Path
) -> dict[str, list[Path]]:
    if not raw:
        return {}
    if isinstance(raw, list):
        # Old flat format → treat as shared
        return {"shared": [playlist_dir / p for p in raw]}
    if isinstance(raw, dict):
        unknown = set(raw.keys()) - _PRONUNCIATION_KEYS
        if unknown:
            raise ConfigError(
                f"Unknown pronunciation keys: {sorted(unknown)}. "
                f"Allowed keys: {sorted(_PRONUNCIATION_KEYS)}"
            )
        result: dict[str, list[Path]] = {}
        for key, paths in raw.items():
            if not isinstance(paths, list):
                raise ConfigError(
                    f"pronunciation.{key} must be a list of paths, got {type(paths).__name__}"
                )
            result[key] = [playlist_dir / p for p in paths]
        return result
    raise ConfigError(f"pronunciation must be a list or dict, got {type(raw).__name__}")
