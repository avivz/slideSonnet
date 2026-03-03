"""Configuration loading and validation from playlist YAML."""

from __future__ import annotations

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
    tts = _parse_tts(raw.get("tts", {}))
    video = _parse_video(raw.get("video", {}))
    voices = _parse_voices(raw.get("voices", {}))
    pronunciation_files = _parse_pronunciation_paths(raw.get("pronunciation", []), playlist_dir)

    return ProjectConfig(
        title=raw.get("title", ""),
        tts=tts,
        video=video,
        voices=voices,
        pronunciation_files=pronunciation_files,
    )


def _parse_tts(raw: dict[str, Any]) -> TTSConfig:
    piper = raw.get("piper", {})
    el = raw.get("elevenlabs", {})

    kwargs: dict[str, Any] = {}
    if "backend" in raw:
        kwargs["backend"] = raw["backend"]
    if "model" in piper:
        kwargs["piper_model"] = piper["model"]
    if "api_key_env" in el:
        kwargs["elevenlabs_api_key_env"] = el["api_key_env"]
    if "voice_id" in el:
        kwargs["elevenlabs_voice_id"] = el["voice_id"]
    if "model_id" in el:
        kwargs["elevenlabs_model_id"] = el["model_id"]
    if "stability" in el:
        kwargs["elevenlabs_stability"] = float(el["stability"])
    if "similarity_boost" in el:
        kwargs["elevenlabs_similarity_boost"] = float(el["similarity_boost"])

    return TTSConfig(**kwargs)


def _parse_video(raw: dict[str, Any]) -> VideoConfig:
    kwargs: dict[str, Any] = {}
    if "resolution" in raw:
        kwargs["resolution"] = raw["resolution"]
    if "fps" in raw:
        kwargs["fps"] = int(raw["fps"])
    if "crf" in raw:
        kwargs["crf"] = int(raw["crf"])
    if "pad_seconds" in raw:
        kwargs["pad_seconds"] = float(raw["pad_seconds"])
    if "pre_silence" in raw:
        kwargs["pre_silence"] = float(raw["pre_silence"])
    if "silence_duration" in raw:
        kwargs["silence_duration"] = float(raw["silence_duration"])
    if "preset" in raw:
        kwargs["preset"] = str(raw["preset"])
    if "crossfade" in raw:
        kwargs["crossfade"] = float(raw["crossfade"])
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
