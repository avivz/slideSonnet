"""Configuration data models shared across slideSonnet.

These are the *engine/output* configuration types reused by the TTS backends,
the video composer, and the editor. The narration data model (Segment /
PageNarration / Deck) lives in :mod:`slidesonnet.narration.model`.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

#: Progress callback for long-running pipeline stages: ``(phase, done, total, label)``.
#: *phase* names the stage (``"tts"``, ``"assemble"``, ``"video"``, ``"concat"``,
#: ``"mux"``); ``done``/``total`` count within that phase (seconds of output for
#: the final ffmpeg passes); *label* is what was just finished, e.g. a slide id,
#: or ``""``. :class:`slidesonnet.progress.RunProgress` turns these into one
#: overall percentage.
ProgressFn = Callable[[str, int, int, str], None]


# The typed source of backend names. mypy can't derive a Literal from the
# runtime registry (tts.BACKENDS); a test pins the two in sync.
Backend = Literal["kokoro", "qwen3", "inworld"]

#: Devices the local Qwen3 engine can load onto (base device; the engine appends
#: ``:0`` for the accelerators). Validated on TTSConfig.
_QWEN3_DEVICES = frozenset({"xpu", "cuda", "cpu"})


def _require_positive(name: str, value: float) -> None:
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a positive number, got {value}")


def _require_non_negative(name: str, value: float) -> None:
    if not (math.isfinite(value) and value >= 0):
        raise ValueError(f"{name} must be a non-negative number, got {value}")


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
    #: Whether the deck's slidesonnet.toml named the backend (else it's the default).
    backend_configured: bool = False
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
    inworld_model: str = "inworld-tts-2"  # default model; override per deck via [tts.inworld] model
    inworld_speed: float = 1.0  # base speaking_rate; per-utterance :pace multiplies this
    #: The deck's directory, whose ``.env`` supplies the API key (see :mod:`slidesonnet.env`).
    #: Not part of any cache key; None falls back to the cwd's ``.env``.
    env_dir: Path | None = None

    def __post_init__(self) -> None:
        _require_positive("kokoro_speed", self.kokoro_speed)
        _require_positive("inworld_speed", self.inworld_speed)
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


_RESOLUTION_RE = re.compile(r"^(?P<w>\d+)x(?P<h>\d+)$")
#: x264's CRF range (8-bit): 0 is lossless, 51 the worst quality.
_CRF_RANGE = range(52)

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
    #: Leave the render intermediates (decoded page audio, the assembled track,
    #: per-slide clips) in the cache after a successful export instead of
    #: deleting them. They only feed ffmpeg once and dwarf the audio they came
    #: from, so the default is to drop them; set for debugging a render.
    keep_scratch: bool = False

    def __post_init__(self) -> None:
        size = _RESOLUTION_RE.match(self.resolution)
        if not size:
            raise ValueError(
                f"Invalid resolution '{self.resolution}': expected 'WIDTHxHEIGHT' (e.g. '1920x1080')"
            )
        if any(int(n) <= 0 or int(n) % 2 for n in (size["w"], size["h"])):
            # yuv420p (the MP4 pixel format) halves the chroma planes
            raise ValueError(
                f"Invalid resolution '{self.resolution}': width and height must be positive "
                "and even (e.g. '1920x1080')"
            )
        if self.fps <= 0:
            raise ValueError(f"fps must be positive, got {self.fps}")
        if self.crf not in _CRF_RANGE:
            raise ValueError(f"crf must be between 0 and 51, got {self.crf}")
        if self.preset not in _VALID_PRESETS:
            raise ValueError(
                f"Invalid preset '{self.preset}': must be one of {sorted(_VALID_PRESETS)}"
            )
        _require_non_negative("pre_silence", self.pre_silence)
        _require_non_negative("tail_seconds", self.tail_seconds)
