"""Core data models for slideSonnet."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


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
    image_path: Path | None = None
    annotation: SlideAnnotation = SlideAnnotation.NONE
    narration_raw: str = ""
    narration_processed: str = ""
    audio_path: Path | None = None
    segment_path: Path | None = None
    duration_seconds: float = 0.0
    voice: str | None = None  # named voice preset, None = default
    pace: str | None = None  # slow / normal / fast

    @property
    def has_narration(self) -> bool:
        return self.annotation == SlideAnnotation.SAY and bool(self.narration_raw.strip())

    @property
    def is_silent(self) -> bool:
        return self.annotation in (SlideAnnotation.SILENT, SlideAnnotation.NONE)

    @property
    def is_skip(self) -> bool:
        return self.annotation == SlideAnnotation.SKIP


@dataclass
class PlaylistEntry:
    """One module in the playlist."""

    label: str
    path: Path  # relative to playlist file
    module_type: ModuleType

    @classmethod
    def from_link(cls, label: str, path_str: str) -> PlaylistEntry:
        path = Path(path_str)
        suffix = path.suffix.lower()
        module_type = EXTENSION_TO_TYPE.get(suffix)
        if module_type is None:
            raise ValueError(f"Unknown file type for '{path_str}' (extension '{suffix}')")
        return cls(label=label, path=path, module_type=module_type)


@dataclass
class VoiceConfig:
    """A named voice preset."""

    name: str
    backend_voice: str  # piper model name or elevenlabs voice_id


@dataclass
class TTSConfig:
    """TTS backend configuration."""

    backend: str = "piper"  # "piper" | "elevenlabs"
    piper_model: str = "en_US-lessac-medium"
    elevenlabs_api_key_env: str = "ELEVENLABS_API_KEY"
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_stability: float = 0.5
    elevenlabs_similarity_boost: float = 0.75


@dataclass
class VideoConfig:
    """Video output configuration."""

    resolution: str = "1920x1080"
    fps: int = 24
    crf: int = 23
    pad_seconds: float = 0.5
    silence_duration: float = 3.0


@dataclass
class ProjectConfig:
    """Full project configuration parsed from playlist YAML front matter."""

    title: str = ""
    tts: TTSConfig = field(default_factory=TTSConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    voices: dict[str, VoiceConfig] = field(default_factory=dict)
    pronunciation_files: list[Path] = field(default_factory=list)
    pronunciation: dict[str, str] = field(default_factory=dict)  # merged from files
