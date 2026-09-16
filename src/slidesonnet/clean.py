"""Selective cache cleanup with graduated preservation levels.

nothing — remove the entire .slidesonnet cache
api     — keep cloud (paid, e.g. Inworld) audio, drop local Kokoro audio + renders
current — keep audio for the current sidecar text (any engine), drop orphans + renders
exact   — keep only audio matching the current text + active TTS config

When the deck's clips live in a **shared pool** (``[cache] audio_dir`` or
``SLIDESONNET_AUDIO_DIR``, see :mod:`slidesonnet.cache`), the audio levels above
are meaningless for one deck: a clip this deck no longer says may be exactly the
one another deck still needs. A per-deck clean then touches only the deck's own
``.slidesonnet/`` (renders, logs, and any legacy local clips after copying them
into the pool) and reports the pool it left alone. Pruning the pool itself is
:mod:`slidesonnet.pool`'s job, which considers every deck at once.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from slidesonnet.audio.synth import engine_for_pace
from slidesonnet.cache import (
    adopt_legacy_audio,
    cache_root,
    default_audio_dir,
    render_dir,
    resolve_audio_dir,
)
from slidesonnet.config import Config, load_config
from slidesonnet.deck import load_deck
from slidesonnet.hashing import audio_filename, parse_audio_filename, text_hash
from slidesonnet.models import VoiceConfig, resolve_voice
from slidesonnet.narration.model import Pace
from slidesonnet.tts import API_BACKENDS, AUTO_PRUNE_BACKENDS
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

KeepLevel = Literal["nothing", "api", "current", "exact"]


@dataclass
class CleanResult:
    removed_files: int = 0
    removed_bytes: int = 0
    kept_files: int = 0
    #: The shared pool this clean deliberately did not touch (None = no pool).
    pool: Path | None = None

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
    """Clean the deck's cache with the given preservation level.

    With a shared pool configured, only the deck's own ``.slidesonnet/`` is
    touched (see the module docstring) and the result names the pool.
    """
    root = cache_root(pdf_path)
    if not root.exists():
        return CleanResult()

    files_before, bytes_before = _count_dir(root)
    res = resolve_audio_dir(pdf_path, load_config(pdf_path))

    if keep == "nothing":
        if res.shared:
            adopt_legacy_audio(pdf_path, res.path)  # never lose a clip the pool lacks
        shutil.rmtree(root)
    elif res.shared:
        _remove_logs(pdf_path)
        _remove_renders(pdf_path)
        retire_legacy_audio(pdf_path, res.path)
    else:
        _remove_logs(pdf_path)
        _remove_renders(pdf_path)
        if keep == "api":
            _keep_api(pdf_path)
        elif keep == "current":
            _keep_hashes(pdf_path, current_text_hashes(pdf_path))
        elif keep == "exact":
            _keep_filenames(pdf_path, current_filenames(pdf_path))

    files_after, bytes_after = _count_dir(root)
    return CleanResult(
        removed_files=files_before - files_after,
        removed_bytes=bytes_before - bytes_after,
        kept_files=files_after,
        pool=res.path if res.shared else None,
    )


def retire_legacy_audio(pdf_path: Path, pool: Path) -> int:
    """Move the deck-local clips into the pool: copy, then drop the local dir.

    Adoption copies every recognizable clip that the pool lacks, so removing
    the local dir afterwards loses nothing recognizable; unrecognized files
    (never clips) go with it, as they would under any clean. Returns how many
    clips the pool gained. Used by per-deck ``clean`` in pool mode and by
    ``pool migrate`` for a whole course.
    """
    legacy = default_audio_dir(pdf_path)
    if not legacy.is_dir():
        return 0
    adopted = adopt_legacy_audio(pdf_path, pool)
    shutil.rmtree(legacy)
    return adopted


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
    res = resolve_audio_dir(pdf_path, load_config(pdf_path))
    if res.shared:
        # Another deck on the pool may still say what this one just edited away.
        return CleanResult(pool=res.path)
    ad = res.path
    if not ad.exists():
        return CleanResult()

    current = current_text_hashes(pdf_path)
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
    ad = default_audio_dir(pdf_path)
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
    ad = default_audio_dir(pdf_path)
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
    ad = default_audio_dir(pdf_path)
    if not ad.exists():
        return
    for f in ad.iterdir():
        if f.is_file() and f.name not in filenames:
            f.unlink()


def _speech_plan(
    pdf_path: Path,
) -> tuple[Config, list[tuple[str, str | None, Pace | None]], dict[str, VoiceConfig]]:
    """Config, speech rows, and the voice map synthesis sees — so clean predicts
    the exact cache keys synthesis writes.

    Each row is ``(pronunciation-applied text, effective voice preset, pace)``
    where the preset is ``seg.voice or deck.default_voice`` — the same fallback
    ``audio/synth`` applies. ``voices`` merges the deck preamble's portable voice
    layer over config presets (deck wins), mirroring synth. Without both, a
    default- or preamble-voiced clip resolves to the wrong (or ``None``) voice and
    a current clip — notably paid Inworld audio whose name carries a concrete
    voice id — is mistaken for an orphan and deleted.
    """
    config = load_config(pdf_path)
    deck, _ = load_deck(pdf_path)
    voices = {**config.voices, **deck.voices}
    rows: list[tuple[str, str | None, Pace | None]] = []
    for block in deck.narration.values():
        for seg in block.speech_segments:
            rows.append(
                (config.apply_pronunciation(seg.text), seg.voice or deck.default_voice, seg.pace)
            )
    return config, rows, voices


def current_text_hashes(pdf_path: Path) -> set[str]:
    """text_hashes for current utterances across all backends (engine-agnostic).

    A named preset contributes every per-backend voice id it maps to (plus the
    bare default-voice variant), so a clip on any engine — including paid Inworld,
    whose name resolves to a concrete voice id — is recognized as current.
    """
    _config, rows, voices = _speech_plan(pdf_path)
    hashes: set[str] = set()
    for text, preset, _pace in rows:
        voice_ids: set[str | None] = {None}
        cfg = voices.get(preset) if preset else None
        if cfg is not None:
            voice_ids |= cfg.all_voice_ids()  # every backend's voice id for this preset
        elif preset:
            voice_ids.add(preset)  # a raw backend voice id, passed through unchanged
        for voice in voice_ids:
            hashes.add(text_hash(text, voice))
    return hashes


def current_filenames(pdf_path: Path) -> set[str]:
    """Expected audio filenames for the current text + active engine config.

    Mirrors the synthesis path: a paced utterance embeds its multiplied speed
    in the engine cache key, so its expected name comes from the pace-adjusted
    engine, not the base one; and the voice is resolved against the deck preamble
    + config presets for the active backend (default voice included).
    """
    config, rows, voices = _speech_plan(pdf_path)
    engines: dict[float, TTSEngine] = {}
    names: set[str] = set()
    for text, preset, pace in rows:
        tts = engine_for_pace(config.tts, pace, engines)
        voice = resolve_voice(preset, voices, config.tts.backend)
        names.add(audio_filename(text, tts.name(), tts.cache_key(), voice))
    return names
