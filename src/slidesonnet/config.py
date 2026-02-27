"""Configuration loading and validation from playlist YAML front matter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slidesonnet.models import ProjectConfig, TTSConfig, VideoConfig, VoiceConfig


def load_config(raw: dict[str, Any], playlist_dir: Path) -> ProjectConfig:
    """Build a validated ProjectConfig from a raw YAML dict.

    Args:
        raw: Parsed YAML front matter dict.
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


def _parse_pronunciation_paths(raw: list[Any] | None, playlist_dir: Path) -> list[Path]:
    if not raw:
        return []
    return [playlist_dir / p for p in raw]
