"""Selective cache cleanup with graduated preservation levels.

nothing — remove the entire .slidesonnet cache
api     — keep cloud (paid, e.g. Inworld) audio, drop local Kokoro audio + renders
current — keep audio for the current sidecar text (any engine), drop orphans + renders
exact   — keep only audio matching the current text + active TTS config
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from slidesonnet.audio.synth import engine_for_pace
from slidesonnet.cache import audio_dir, cache_root, render_dir
from slidesonnet.config import load_config
from slidesonnet.deck import load_deck
from slidesonnet.hashing import audio_filename, parse_audio_filename, text_hash
from slidesonnet.models import resolve_voice
from slidesonnet.tts import API_BACKENDS, AUTO_PRUNE_BACKENDS
from slidesonnet.narration.model import Pace
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

KeepLevel = Literal["nothing", "api", "current", "exact"]


@dataclass
class CleanResult:
    removed_files: int = 0
    removed_bytes: int = 0
    kept_files: int = 0

    @property
    def removed_mb(self) -> float:
        return self.removed_bytes / (1024 * 1024)


def _count_dir(path: Path) -> tuple[int, int]:
    count = 0
    total = 0
    if not path.exists():
        return 0, 0
    for f in path.rglob("*"):
        if f.is_file():
            count += 1
            total += f.stat().st_size
    return count, total


def clean(pdf_path: Path, keep: KeepLevel = "api") -> CleanResult:
    """Clean the deck's cache with the given preservation level."""
    root = cache_root(pdf_path)
    if not root.exists():
        return CleanResult()

    files_before, bytes_before = _count_dir(root)

    if keep == "nothing":
        shutil.rmtree(root)
    else:
        _remove_logs(pdf_path)
        _remove_renders(pdf_path)
        if keep == "api":
            _keep_api(pdf_path)
        elif keep == "current":
            _keep_hashes(pdf_path, _current_text_hashes(pdf_path))
        elif keep == "exact":
            _keep_filenames(pdf_path, _current_filenames(pdf_path))

    files_after, bytes_after = _count_dir(root)
    return CleanResult(
        removed_files=files_before - files_after,
        removed_bytes=bytes_before - bytes_after,
        kept_files=files_after,
    )


def prune_local_orphans(pdf_path: Path) -> CleanResult:
    """Drop cheap-to-regenerate audio whose utterance is no longer in the sidecar.

    Called automatically after a sidecar edit: when text or a pinned voice
    changes, its old clip's ``text_hash`` falls out of the current set and the
    file becomes dead weight. Only backends flagged ``auto_prune_orphans`` (real-
    time local audio like Kokoro — cheap to regenerate) are reclaimed eagerly.
    Paid audio (Inworld — would re-bill) **and** expensive free-but-slow local
    audio (Qwen3 — seconds per clip) are kept, so an unrelated edit never silently
    discards minutes of own-voice generation. Renders are left alone, and
    unrecognized filenames are kept — an automatic, silent sweep should only
    delete clips it is certain it produced and that are trivial to remake.
    """
    ad = audio_dir(pdf_path)
    if not ad.exists():
        return CleanResult()

    current = _current_text_hashes(pdf_path)
    result = CleanResult()
    for f in ad.iterdir():
        if not f.is_file():
            continue
        parsed = parse_audio_filename(f.name)
        if parsed is None or parsed[1] not in AUTO_PRUNE_BACKENDS or parsed[0] in current:
            result.kept_files += 1
            continue
        result.removed_bytes += f.stat().st_size
        f.unlink()
        result.removed_files += 1
    return result


def _remove_logs(pdf_path: Path) -> None:
    """Drop the run log and its rotated backups — a disposable diagnostic artifact."""
    from slidesonnet.logging_setup import LOG_FILENAME

    root = cache_root(pdf_path)
    for log in root.glob(f"{LOG_FILENAME}*"):
        if log.is_file():
            log.unlink()


def _remove_renders(pdf_path: Path) -> None:
    rd = render_dir(pdf_path)
    if rd.exists():
        shutil.rmtree(rd)
    parent = rd.parent  # the shared render/ root; drop it once no deck uses it
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()


def _keep_api(pdf_path: Path) -> None:
    ad = audio_dir(pdf_path)
    if not ad.exists():
        return
    for f in ad.iterdir():
        if not f.is_file():
            continue
        parsed = parse_audio_filename(f.name)
        if parsed and parsed[1] in API_BACKENDS:
            continue
        f.unlink()


def _keep_hashes(pdf_path: Path, hashes: set[str]) -> None:
    ad = audio_dir(pdf_path)
    if not ad.exists():
        return
    for f in ad.iterdir():
        if not f.is_file():
            continue
        parsed = parse_audio_filename(f.name)
        if parsed and parsed[0] in hashes:
            continue
        f.unlink()


def _keep_filenames(pdf_path: Path, filenames: set[str]) -> None:
    ad = audio_dir(pdf_path)
    if not ad.exists():
        return
    for f in ad.iterdir():
        if f.is_file() and f.name not in filenames:
            f.unlink()


def _iter_speech(pdf_path: Path) -> list[tuple[str, str | None, Pace | None]]:
    """Return (text, voice_preset, pace) for every speech segment in the sidecar."""
    config = load_config(pdf_path)
    deck, _ = load_deck(pdf_path)
    out: list[tuple[str, str | None, Pace | None]] = []
    for block in deck.narration.values():
        for seg in block.speech_segments:
            out.append((config.apply_pronunciation(seg.text), seg.voice, seg.pace))
    return out


def _current_text_hashes(pdf_path: Path) -> set[str]:
    """text_hashes for current utterances across all backends (engine-agnostic)."""
    config = load_config(pdf_path)
    hashes: set[str] = set()
    for text, voice_preset, _pace in _iter_speech(pdf_path):
        voices: set[str | None] = {None}
        if voice_preset and voice_preset in config.voices:
            voices |= config.voices[voice_preset].all_voice_ids()
        for voice in voices:
            hashes.add(text_hash(text, voice))
    return hashes


def _current_filenames(pdf_path: Path) -> set[str]:
    """Expected audio filenames for the current text + active engine config.

    Mirrors the synthesis path: a paced utterance embeds its multiplied speed
    in the engine cache key, so its expected name comes from the pace-adjusted
    engine, not the base one.
    """
    config = load_config(pdf_path)
    engines: dict[float, TTSEngine] = {}
    names: set[str] = set()
    for text, voice_preset, pace in _iter_speech(pdf_path):
        tts = engine_for_pace(config.tts, pace, engines)
        voice = resolve_voice(voice_preset, config.voices, config.tts.backend)
        names.add(audio_filename(text, tts.name(), tts.cache_key(), voice))
    return names
