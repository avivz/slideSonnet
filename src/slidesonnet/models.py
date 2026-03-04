"""Core data models for slideSonnet."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal


API_BACKENDS: frozenset[str] = frozenset({"elevenlabs"})


class ModuleType(Enum):
    MARP = "marp"
    BEAMER = "beamer"
    VIDEO = "video"


EXTENSION_TO_TYPE: dict[str, ModuleType] = {
    ".md": ModuleType.MARP,
    ".tex": ModuleType.BEAMER,
    ".mp4": ModuleType.VIDEO,
    ".mkv": ModuleType.VIDEO,
    ".webm": ModuleType.VIDEO,
    ".mov": ModuleType.VIDEO,
}


class SlideAnnotation(Enum):
    SAY = "say"
    SILENT = "silent"
    SKIP = "skip"
    NONE = "none"  # unannotated — triggers warning


@dataclass
class SlideNarration:
    """Parsed data for a single slide."""

    index: int  # 1-based slide number within the module
    image_index: int = 0  # 1-based index into image manifest (0 = default to index)
    image_path: Path | None = None
    annotation: SlideAnnotation = SlideAnnotation.NONE
    narration_raw: str = ""
    narration_processed: str = ""
    narration_parts: list[str] = field(default_factory=list)
    narration_parts_processed: list[str] = field(default_factory=list)
    audio_path: Path | None = None
    segment_path: Path | None = None
    duration_seconds: float = 0.0
    voice: str | None = None  # named voice preset, None = default
    pace: str | None = None  # slow / normal / fast
    silence_override: float | None = None  # per-slide silence duration override (seconds)

    def __post_init__(self) -> None:
        if self.image_index == 0:
            self.image_index = self.index
        if self.silence_override is not None and self.silence_override < 0:
            raise ValueError(f"silence_override must be non-negative, got {self.silence_override}")

    @property
    def has_narration(self) -> bool:
        return self.annotation == SlideAnnotation.SAY and bool(self.narration_raw.strip())

    @property
    def is_skip(self) -> bool:
        return self.annotation == SlideAnnotation.SKIP


@dataclass
class PlaylistEntry:
    """One module in the playlist."""

    path: Path  # relative to playlist file
    module_type: ModuleType

    @classmethod
    def from_path(cls, path_str: str) -> PlaylistEntry:
        path = Path(path_str)
        if path.is_absolute():
            raise ValueError(f"Module path must be relative, got absolute: '{path_str}'")
        if ".." in path.parts:
            raise ValueError(f"Module path must not contain '..': '{path_str}'")
        suffix = path.suffix.lower()
        module_type = EXTENSION_TO_TYPE.get(suffix)
        if module_type is None:
            raise ValueError(f"Unknown file type for '{path_str}' (extension '{suffix}')")
        return cls(path=path, module_type=module_type)


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

    backend: Literal["piper", "elevenlabs"] = "piper"
    piper_model: str = "en_US-lessac-medium"
    elevenlabs_api_key_env: str = "ELEVENLABS_API_KEY"
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_stability: float = 0.5
    elevenlabs_similarity_boost: float = 0.75

    def __post_init__(self) -> None:
        if not (0.0 <= self.elevenlabs_stability <= 1.0):
            raise ValueError(
                f"elevenlabs_stability must be between 0 and 1, got {self.elevenlabs_stability}"
            )
        if not (0.0 <= self.elevenlabs_similarity_boost <= 1.0):
            raise ValueError(
                f"elevenlabs_similarity_boost must be between 0 and 1, got {self.elevenlabs_similarity_boost}"
            )


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
    pad_seconds: float = 1.5
    pre_silence: float = 1.0
    silence_duration: float = 3.0
    crossfade: float = 0.5

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
        if self.silence_duration < 0:
            raise ValueError(f"silence_duration must be non-negative, got {self.silence_duration}")
        if self.crossfade < 0:
            raise ValueError(f"crossfade must be non-negative, got {self.crossfade}")


@dataclass
class ProjectConfig:
    """Full project configuration parsed from playlist YAML."""

    title: str = ""
    tts: TTSConfig = field(default_factory=TTSConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    voices: dict[str, VoiceConfig] = field(default_factory=dict)
    pronunciation_files: dict[str, list[Path]] = field(default_factory=dict)
    pronunciation: dict[str, dict[str, str]] = field(default_factory=dict)  # merged from files

    def pronunciation_for(self, backend: str) -> dict[str, str]:
        """Merge shared + backend-specific pronunciation dicts.

        Backend-specific entries override shared entries for the same word.
        """
        merged = dict(self.pronunciation.get("shared", {}))
        merged.update(self.pronunciation.get(backend, {}))
        return merged
