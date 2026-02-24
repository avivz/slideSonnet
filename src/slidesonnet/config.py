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
    cfg = TTSConfig()
    cfg.backend = raw.get("backend", cfg.backend)

    piper = raw.get("piper", {})
    cfg.piper_model = piper.get("model", cfg.piper_model)

    el = raw.get("elevenlabs", {})
    cfg.elevenlabs_api_key_env = el.get("api_key_env", cfg.elevenlabs_api_key_env)
    cfg.elevenlabs_voice_id = el.get("voice_id", cfg.elevenlabs_voice_id)
    cfg.elevenlabs_model_id = el.get("model_id", cfg.elevenlabs_model_id)
    cfg.elevenlabs_stability = float(el.get("stability", cfg.elevenlabs_stability))
    cfg.elevenlabs_similarity_boost = float(
        el.get("similarity_boost", cfg.elevenlabs_similarity_boost)
    )

    return cfg


def _parse_video(raw: dict[str, Any]) -> VideoConfig:
    cfg = VideoConfig()
    cfg.resolution = raw.get("resolution", cfg.resolution)
    cfg.fps = int(raw.get("fps", cfg.fps))
    cfg.crf = int(raw.get("crf", cfg.crf))
    cfg.pad_seconds = float(raw.get("pad_seconds", cfg.pad_seconds))
    cfg.pre_silence = float(raw.get("pre_silence", cfg.pre_silence))
    cfg.silence_duration = float(raw.get("silence_duration", cfg.silence_duration))
    return cfg


def _parse_voices(raw: dict[str, Any]) -> dict[str, VoiceConfig]:
    voices = {}
    for name, value in raw.items():
        if isinstance(value, str):
            voices[name] = VoiceConfig(name=name, backend_voice=value)
        elif isinstance(value, dict):
            backend_voice = str(value.get("backend_voice", value.get("model", "")))
            voices[name] = VoiceConfig(
                name=name,
                backend_voice=backend_voice,
            )
    return voices


def _parse_pronunciation_paths(raw: list[Any] | None, playlist_dir: Path) -> list[Path]:
    if not raw:
        return []
    return [playlist_dir / p for p in raw]
