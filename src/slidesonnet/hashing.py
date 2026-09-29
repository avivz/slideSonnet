"""Audio file naming and hash computation for content-addressed caching.

The single source of truth for how TTS audio filenames are computed, shared
by synthesis (audio/synth.py) and selective cleanup (clean.py).

Filename format: {text_hash}.{backend}.{config_hash}.{ext}
  - text_hash:   sha256(text + voice)[:16]  — identifies the utterance content;
                 a ``.pt`` clone-prompt voice is keyed by its file *content*
  - backend:     "kokoro", "inworld", ...   — readable engine name
  - config_hash: sha256(cache_key)[:8]      — differentiates engine configs
  - ext:         backend-specific extension (.wav for kokoro/qwen3, .mp3 for inworld)
"""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

#: Cached-audio file extension per TTS backend. Owned here (not derived from the
#: ``slidesonnet.tts`` registry) so naming a cache file never imports the engine
#: package; ``BackendSpec.extension`` reads it back, and a test pins every
#: registered backend to an entry.
BACKEND_EXTENSIONS: dict[str, str] = {"kokoro": ".wav", "inworld": ".mp3", "qwen3": ".wav"}

_VALID_EXTENSIONS: frozenset[str] = frozenset(BACKEND_EXTENSIONS.values())


#: Suffix of a file-based voice (a Qwen3 voice-clone prompt): such a voice is a
#: path, and is keyed by the file's bytes rather than by where it happens to live.
FILE_VOICE_SUFFIX = ".pt"

# Content hashes memoized by (resolved path, mtime_ns, size): cache keys are
# computed for every utterance on every editor render, so a multi-MB prompt must
# not be re-read each time — yet an in-place edit changes mtime/size and re-hashes.
_CONTENT_HASHES: dict[tuple[str, int, int], str] = {}


def file_content_hash(path: Path) -> str | None:
    """Full sha256 hex of *path*'s bytes, or None if it is not a regular file."""
    try:
        st = path.stat()
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    memo = (str(path.resolve()), st.st_mtime_ns, st.st_size)
    digest = _CONTENT_HASHES.get(memo)
    if digest is None:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        _CONTENT_HASHES[memo] = digest
    return digest


def _voice_identity(voice: str) -> str:
    """What a voice contributes to the text hash.

    An opaque voice id is used verbatim. A file voice (a ``.pt`` clone prompt,
    held as an absolute path) is replaced by its content hash, so editing the
    file in place re-keys its clips while moving the deck, or opening it from
    another worktree, still hits the cache. A missing file keeps the path (the
    synthesis that would fill that slot fails loudly anyway).
    """
    if voice.endswith(FILE_VOICE_SUFFIX):
        digest = file_content_hash(Path(voice))
        if digest is not None:
            return f"pt-sha256:{digest[:16]}"
    return voice


def audio_extension(backend: str) -> str:
    """Return the file extension for a TTS backend (e.g. '.wav', '.mp3')."""
    return BACKEND_EXTENSIONS.get(backend, ".wav")


def text_hash(text: str, voice: str | None = None) -> str:
    """16-char hex hash identifying an utterance's content and voice.

    Includes voice so the same text with different voices
    produces different cache entries (a ``.pt`` file voice by its content).

    *text* is the exact text the engine is sent (``Config.speech_text``): an
    Inworld ``direct:`` note, when sent, is part of it, so the note is hashed
    exactly when it changes the audio. Anything else an engine starts honoring
    must reach the hash too (the text, or the engine's ``cache_key``) —
    otherwise every previously-cached clip is silently stale.
    """
    h = text
    if voice:
        h += f"\0voice={_voice_identity(voice)}"
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


def _alternate_extensions(suffix: str) -> list[str]:
    """Return the other backend extensions besides *suffix*."""
    return [ext for ext in BACKEND_EXTENSIONS.values() if ext != suffix]


def audio_cache_path_or_alt(path: Path) -> Path | None:
    """Return *path* or a same-stem alternate extension if either exists.

    Read-only. Returns the actual path on disk (not a synthesized one)
    so callers can probe its duration. Returns None if nothing is cached.
    """
    if path.exists() and path.stat().st_size > 0:
        return path
    for ext in _alternate_extensions(path.suffix):
        alt = path.with_suffix(ext)
        if alt.exists() and alt.stat().st_size > 0:
            return alt
    return None


def parse_audio_filename(filename: str) -> tuple[str, str, str] | None:
    """Parse a new-format audio filename into (text_hash, backend, config_hash).

    Returns None for old-format files (plain hash.wav), legacy pre-1.0 concat
    files (*_concat.wav), or any filename that doesn't match the 3-part format.
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
