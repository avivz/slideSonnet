"""Configuration data models shared across slideSonnet.

These are the *engine/output* configuration types reused by the TTS backends,
the video composer, and the editor. The narration data model (Segment /
PageNarration / Deck) lives in :mod:`slidesonnet.narration.model`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

#: Progress callback for long-running pipeline stages: (slide_id, done, total).
ProgressFn = Callable[[str, int, int], None]


# The typed source of backend names. mypy can't derive a Literal from the
# runtime registry (tts.BACKENDS); a test pins the two in sync.
Backend = Literal["kokoro", "qwen3", "inworld"]

#: Devices the local Qwen3 engine can load onto (base device; the engine appends
#: ``:0`` for the accelerators). Validated on TTSConfig.
_QWEN3_DEVICES = frozenset({"xpu", "cuda", "cpu"})


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
    """Resolve a per-utterance voice to a backend-specific voice ID.

    A named *preset* (a key in *voices*) maps to its backend voice ID (or None
    if it has no mapping for *backend*). Anything else is treated as a raw
    backend voice ID and passed through unchanged — so an utterance can name an
    engine voice directly (e.g. Kokoro ``af_heart``). None/empty means default.
    """
    if not voice_preset:
        return None
    voice_cfg = voices.get(voice_preset)
    if voice_cfg is None:
        return voice_preset  # a raw backend voice id (not a named preset)
    return voice_cfg.resolve(backend)


@dataclass
class TTSConfig:
    """TTS backend configuration."""

    backend: Backend = "kokoro"
    kokoro_voice: str = "am_echo"
    kokoro_speed: float = 1.0
    # CustomVoice ships ready-to-use named speakers (works out of the box); a
    # ``...-Base`` repo instead clones an own voice from ``qwen3_voice_prompt``.
    qwen3_model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    qwen3_device: str = "xpu"
    qwen3_voice_prompt: str = ""  # path to a .pt voice-clone prompt (Base own-voice only)
    qwen3_language: str = "English"
    inworld_api_key_env: str = "INWORLD_API_KEY"
    inworld_voice: str = "Simon"  # built-in default voice; any Inworld voice name (see library)
    inworld_model: str = "inworld-tts-1.5-max"  # quality-optimized; -mini trades for latency
    inworld_speed: float = 1.0  # base speaking_rate; per-utterance :pace multiplies this

    def __post_init__(self) -> None:
        if self.kokoro_speed <= 0:
            raise ValueError(f"kokoro_speed must be positive, got {self.kokoro_speed}")
        if self.inworld_speed <= 0:
            raise ValueError(f"inworld_speed must be positive, got {self.inworld_speed}")
        if self.qwen3_device not in _QWEN3_DEVICES:
            raise ValueError(
                f"qwen3_device must be one of {sorted(_QWEN3_DEVICES)}, got {self.qwen3_device!r}"
            )


@dataclass
class LoggingConfig:
    """Log-file configuration (the console level comes from the CLI, not here).

    *file* is an explicit path, or ``None`` to use the default under the deck's
    ``.slidesonnet/`` cache. *enabled* is ``False`` when the user wrote
    ``file = false`` in the TOML to turn the log file off entirely. The file
    captures down to *level* (DEBUG by default) and rotates by size, capping disk
    at roughly ``max_bytes * (backup_count + 1)``.
    """

    enabled: bool = True
    file: str | None = None
    level: str = "DEBUG"
    max_bytes: int = 2_000_000
    backup_count: int = 3

    def __post_init__(self) -> None:
        if logging.getLevelName(self.level.upper()) == f"Level {self.level.upper()}":
            raise ValueError(
                f"Invalid log level '{self.level}': expected one of "
                "DEBUG, INFO, WARNING, ERROR, CRITICAL"
            )
        self.level = self.level.upper()
        if self.max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {self.max_bytes}")
        if self.backup_count < 0:
            raise ValueError(f"backup_count must be non-negative, got {self.backup_count}")


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
        if self.pre_silence < 0:
            raise ValueError(f"pre_silence must be non-negative, got {self.pre_silence}")
        if self.tail_seconds < 0:
            raise ValueError(f"tail_seconds must be non-negative, got {self.tail_seconds}")
