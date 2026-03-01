"""Audio file naming and hash computation for content-addressed caching.

Provides the single source of truth for how TTS audio filenames are computed,
used by both tasks.py (build) and clean.py (selective cleanup).

Filename format: {text_hash}.{backend}.{config_hash}.{ext}
  - text_hash:   sha256(text + voice)[:16]  — identifies the utterance content
  - backend:     "piper" or "elevenlabs"    — readable engine name
  - config_hash: sha256(cache_key)[:8]      — differentiates engine configs
  - ext:         backend-specific extension (.wav for piper, .mp3 for elevenlabs)

Concat files keep the format: {hash}_concat.wav
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_BACKEND_EXTENSIONS: dict[str, str] = {
    "piper": ".wav",
    "elevenlabs": ".mp3",
}

_VALID_EXTENSIONS: frozenset[str] = frozenset(_BACKEND_EXTENSIONS.values())


def audio_extension(backend: str) -> str:
    """Return the file extension for a TTS backend (e.g. '.wav', '.mp3')."""
    return _BACKEND_EXTENSIONS.get(backend, ".wav")


def text_hash(text: str, voice: str | None = None) -> str:
    """16-char hex hash identifying an utterance's content and voice.

    Includes voice so the same text with different voices
    produces different cache entries.
    """
    h = text
    if voice:
        h += f"\0voice={voice}"
    return hashlib.sha256(h.encode("utf-8")).hexdigest()[:16]


def config_hash(cache_key: str) -> str:
    """8-char hex hash differentiating TTS engine configurations."""
    return hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:8]


def audio_filename(text: str, backend: str, cache_key: str, voice: str | None = None) -> str:
    """Compute the content-addressed filename for a TTS audio file.

    Format: {text_hash}.{backend}.{config_hash}.{ext}
    """
    th = text_hash(text, voice)
    ch = config_hash(cache_key)
    ext = audio_extension(backend)
    return f"{th}.{backend}.{ch}{ext}"


def audio_path(
    audio_dir: Path,
    text: str,
    backend: str,
    cache_key: str,
    voice: str | None = None,
) -> Path:
    """Full cache path for a TTS audio file."""
    return audio_dir / audio_filename(text, backend, cache_key, voice)


def concat_filename(part_paths: list[Path]) -> str:
    """Content-addressed filename for concatenated audio."""
    concat_hash_input = "\0".join(str(p) for p in part_paths)
    h = hashlib.sha256(concat_hash_input.encode("utf-8")).hexdigest()[:16]
    return f"{h}_concat.wav"


def parse_audio_filename(filename: str) -> tuple[str, str, str] | None:
    """Parse a new-format audio filename into (text_hash, backend, config_hash).

    Returns None for old-format files (plain hash.wav), concat files (*_concat.wav),
    or any filename that doesn't match the expected 3-part format.
    """
    if filename.endswith("_concat.wav"):
        return None
    # Accept any valid extension (.wav, .mp3)
    ext: str | None = None
    for valid_ext in _VALID_EXTENSIONS:
        if filename.endswith(valid_ext):
            ext = valid_ext
            break
    if ext is None:
        return None
    stem = filename[: -len(ext)]
    parts = stem.split(".")
    if len(parts) != 3:
        return None
    return (parts[0], parts[1], parts[2])
