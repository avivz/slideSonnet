"""Configuration data models shared across slideSonnet.

These are the *engine/output* configuration types reused by the TTS backends,
the video composer, and the editor. The narration data model (Segment /
PageNarration / Deck) lives in :mod:`slidesonnet.narration.model`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


API_BACKENDS: frozenset[str] = frozenset({"elevenlabs"})


@dataclass
class VoiceConfig:
    """A named voice preset with per-backend voice mappings."""

    name: str
    backend_voices: dict[str, str] = field(default_factory=dict)

    def resolve(self, backend: str) -> str | None:
        """Return the voice ID for the given backend, or None if unmapped."""
        return self.backend_voices.get(backend)

    def all_voice_ids(self) -> set[str]:
        """Return all backend voice IDs for this preset."""
        return set(self.backend_voices.values())


def resolve_voice(
    voice_preset: str | None,
    voices: dict[str, VoiceConfig],
    backend: str,
) -> str | None:
    """Resolve a named voice preset to a backend-specific voice ID.

    Returns None if *voice_preset* is None, unknown, or has no mapping
    for *backend*.
    """
    if not voice_preset:
        return None
    voice_cfg = voices.get(voice_preset)
    if voice_cfg is None:
        return None
    return voice_cfg.resolve(backend)


@dataclass
class TTSConfig:
    """TTS backend configuration."""

    backend: Literal["kokoro", "elevenlabs"] = "kokoro"
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0
    elevenlabs_api_key_env: str = "ELEVENLABS_API_KEY"
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_stability: float = 0.5
    elevenlabs_similarity_boost: float = 0.75
    elevenlabs_speed: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.elevenlabs_stability <= 1.0):
            raise ValueError(
                f"elevenlabs_stability must be between 0 and 1, got {self.elevenlabs_stability}"
            )
        if not (0.0 <= self.elevenlabs_similarity_boost <= 1.0):
            raise ValueError(
                "elevenlabs_similarity_boost must be between 0 and 1, "
                f"got {self.elevenlabs_similarity_boost}"
            )
        if self.kokoro_speed <= 0:
            raise ValueError(f"kokoro_speed must be positive, got {self.kokoro_speed}")
        if self.elevenlabs_speed <= 0:
            raise ValueError(f"elevenlabs_speed must be positive, got {self.elevenlabs_speed}")


_RESOLUTION_RE = re.compile(r"^\d+x\d+$")

_VALID_PRESETS = frozenset(
    {
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
        "placebo",
    }
)


@dataclass
class VideoConfig:
    """Video output configuration."""

    resolution: str = "1920x1080"
    fps: int = 24
    crf: int = 23
    preset: str = "medium"
    pad_seconds: float = 1.0
    pre_silence: float = 0.3
    tail_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not _RESOLUTION_RE.match(self.resolution):
            raise ValueError(
                f"Invalid resolution '{self.resolution}': expected 'WIDTHxHEIGHT' (e.g. '1920x1080')"
            )
        if self.fps <= 0:
            raise ValueError(f"fps must be positive, got {self.fps}")
        if self.crf < 0:
            raise ValueError(f"crf must be non-negative, got {self.crf}")
        if self.preset not in _VALID_PRESETS:
            raise ValueError(
                f"Invalid preset '{self.preset}': must be one of {sorted(_VALID_PRESETS)}"
            )
        if self.pad_seconds < 0:
            raise ValueError(f"pad_seconds must be non-negative, got {self.pad_seconds}")
        if self.pre_silence < 0:
            raise ValueError(f"pre_silence must be non-negative, got {self.pre_silence}")
        if self.tail_seconds < 0:
            raise ValueError(f"tail_seconds must be non-negative, got {self.tail_seconds}")
