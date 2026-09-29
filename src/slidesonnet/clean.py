"""Selective cache cleanup with graduated preservation levels.

Render scratch and logs always go. ``--keep`` decides which speech clips of
*this deck* survive:

nothing — none
api     — paid (API-backend, e.g. Inworld) clips only
current — clips for text the deck still says, on any engine
exact   — only clips the deck would use under its current engine config

**One clip GC.** The default ``<folder>/.slidesonnet/audio/`` is shared by every
deck in the folder, so it is treated as an implicit pool whose members are the
sibling ``*.pdf`` files that have a ``<stem>.narration``. Whatever the level, a
clip a sibling still says is kept, and the decision is made by
:func:`slidesonnet.pool.plan_prune` — the same mark-and-sweep ``pool prune``
uses. If a sibling can't be read, nothing is planned (fail conservatively).
Paid and slow-to-make clips are never deleted outright: they are moved to
``audio/trash/``, exactly like a pool prune.

When the deck's clips live in a **shared pool** (``[cache] audio_dir`` or
``SLIDESONNET_AUDIO_DIR``, see :mod:`slidesonnet.cache`), the audio levels above
are meaningless for one deck: a clip this deck no longer says may be exactly the
one another deck still needs. A per-deck clean then touches only the deck's own
scratch (renders, logs, and any legacy local clips after copying them into the
pool) and reports the pool it left alone. Pruning the pool itself is
:mod:`slidesonnet.pool`'s job, which considers every deck at once.
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from slidesonnet.audio.synth import engine_for_pace
from slidesonnet.cache import (
    adopt_legacy_audio,
    cache_root,
    default_audio_dir,
    paths_overlap,
    render_dir,
    resolve_audio_dir,
)
from slidesonnet.config import Config, load_config
from slidesonnet.deck import default_sidecar_path, load_deck
from slidesonnet.hashing import audio_filename, parse_audio_filename, text_hash
from slidesonnet.models import VoiceConfig, resolve_voice
from slidesonnet.narration.format import parse_sidecar
from slidesonnet.narration.model import PageNarration, Segment
from slidesonnet.pool import (
    TRASH_DIRNAME,
    DeckRoot,
    PoolError,
    PrunePlan,
    apply_prune,
    is_paid,
    plan_prune,
)
from slidesonnet.tts import BACKENDS
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

KeepLevel = Literal["nothing", "api", "current", "exact"]

#: How long the automatic sweep leaves a cheap clip alone after it became an
#: orphan — long enough to try a voice or a wording and change your mind.
SWEEP_GRACE_S = 600.0


@dataclass
class CleanResult:
    removed_files: int = 0
    removed_bytes: int = 0
    #: Speech clips left in place.
    kept_files: int = 0
    #: The shared pool this clean deliberately did not touch (None = no pool).
    pool: Path | None = None
    #: Paid / slow clips moved to the trash instead of being deleted.
    trashed_files: int = 0
    trash_dir: Path | None = None
    kept_paid: int = 0
    #: Sweep only: orphans left alone because they are still in their grace period.
    deferred_files: int = 0

    @property
    def removed_mb(self) -> float:
        return self.removed_bytes / (1024 * 1024)


@dataclass
class CleanPlan:
    """What a clean would do; nothing has been touched yet."""

    pdf: Path
    keep: KeepLevel
    #: Removed whole: the deck's render dir and the run logs.
    scratch: list[Path] = field(default_factory=list)
    #: The audio GC over the folder's shared clip dir (None in pool mode).
    prune: PrunePlan | None = None
    #: Pool mode: the shared pool, left alone.
    pool: Path | None = None
    #: Pool mode: the legacy local clip dir, copied into the pool then dropped.
    legacy: Path | None = None

    @property
    def remove(self) -> list[Path]:
        """Every file that would be deleted (legacy local clips: after being
        copied into the pool)."""
        files = [f for p in self.scratch for f in _files(p)]
        if self.legacy is not None:
            files += _files(self.legacy)
        if self.prune is not None:
            files += self.prune.delete
        return files

    @property
    def to_trash(self) -> list[Path]:
        return list(self.prune.quarantine) if self.prune is not None else []

    @property
    def paid_to_trash(self) -> list[Path]:
        return [f for f in self.to_trash if _paid_clip(f)]

    @property
    def kept_paid(self) -> list[Path]:
        return [f for f in self.prune.kept if _paid_clip(f)] if self.prune is not None else []

    @property
    def trash_dir(self) -> Path | None:
        return self.prune.pool / TRASH_DIRNAME if self.prune is not None else None


def _paid_clip(f: Path) -> bool:
    parsed = parse_audio_filename(f.name)
    return parsed is not None and is_paid(parsed[1])


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return [f for f in path.rglob("*") if f.is_file()] if path.is_dir() else []


def _size(files: list[Path]) -> int:
    return sum(f.stat().st_size for f in files)


def sibling_decks(pdf_path: Path) -> list[DeckRoot]:
    """The other decks sharing *pdf_path*'s folder (and so its default clip dir):
    every ``*.pdf`` beside it with a ``<stem>.narration``."""
    pdf = pdf_path.resolve()
    return [
        DeckRoot(p)
        for p in sorted(pdf.parent.iterdir())
        if p.suffix.lower() == ".pdf" and p != pdf and default_sidecar_path(p).is_file()
    ]


def _own_roots(pdf_path: Path, sidecar_path: Path | None) -> list[DeckRoot]:
    """The deck itself as a GC root — under the sidecar actually being edited and,
    when that is an override, also its default sidecar (someone may still use it)."""
    pdf = pdf_path.resolve()
    if sidecar_path is None or sidecar_path.resolve() == default_sidecar_path(pdf):
        return [DeckRoot(pdf)]
    return [DeckRoot(pdf, sidecar_path.resolve()), DeckRoot(pdf)]


def plan_clean(
    pdf_path: Path, keep: KeepLevel = "api", *, sidecar_path: Path | None = None
) -> CleanPlan:
    """Decide what ``clean`` would remove. Raises :class:`PoolError` when a deck in
    the folder can't be read (nothing is planned without knowing what it uses)."""
    from slidesonnet.logging_setup import LOG_FILENAME

    root = cache_root(pdf_path)
    logs = sorted(p for p in root.glob(f"{LOG_FILENAME}*") if p.is_file())
    plan = CleanPlan(pdf=pdf_path, keep=keep, scratch=[render_dir(pdf_path), *logs])
    res = resolve_audio_dir(pdf_path, load_config(pdf_path))
    if res.shared:
        plan.pool = res.path
        legacy = default_audio_dir(pdf_path)
        if legacy.is_dir() and not paths_overlap(legacy, res.path):
            plan.legacy = legacy
        return plan
    own = _own_roots(pdf_path, sidecar_path) if keep in ("current", "exact") else []
    plan.prune = plan_prune(res.path, own, keep, protect=sibling_decks(pdf_path))
    return plan


def apply_clean(plan: CleanPlan) -> CleanResult:
    """Carry out *plan*: delete scratch and cheap clips, park paid / slow ones in trash."""
    result = CleanResult(pool=plan.pool)
    for path in plan.scratch:
        files = _files(path)
        result.removed_files += len(files)
        result.removed_bytes += _size(files)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    _rmdir_if_empty(render_dir(plan.pdf).parent)  # the shared render/ root
    if plan.legacy is not None and plan.pool is not None:
        files = _files(plan.legacy)
        result.removed_bytes += _size(files)
        result.removed_files += len(files)
        retire_legacy_audio(plan.pdf, plan.pool)
    if plan.prune is not None:
        pruned = apply_prune(plan.prune)
        result.removed_files += pruned.deleted_files
        result.removed_bytes += pruned.deleted_bytes
        result.trashed_files = pruned.quarantined_files
        result.trash_dir = pruned.trash_dir
        result.kept_files = len(plan.prune.kept)
        result.kept_paid = len(plan.kept_paid)
        if plan.keep == "nothing":
            _rmdir_if_empty(plan.prune.pool)
    _rmdir_if_empty(cache_root(plan.pdf))
    return result


def clean(
    pdf_path: Path, keep: KeepLevel = "api", *, sidecar_path: Path | None = None
) -> CleanResult:
    """Plan and apply a clean of the deck's cache at the given preservation level.

    With a shared pool configured, only the deck's own scratch is touched (see
    the module docstring) and the result names the pool.
    """
    if not cache_root(pdf_path).exists():
        return CleanResult()
    return apply_clean(plan_clean(pdf_path, keep, sidecar_path=sidecar_path))


def _rmdir_if_empty(path: Path) -> None:
    if path.is_dir() and not any(path.iterdir()):
        path.rmdir()


def retire_legacy_audio(pdf_path: Path, pool: Path) -> int:
    """Move the deck-local clips into the pool: copy, then drop the local dir.

    Adoption copies every recognizable clip that the pool lacks (and the local
    trash into the pool's), so removing the local dir afterwards loses nothing
    recognizable; unrecognized files (never clips) go with it, as they would
    under any clean. Returns how many clips the pool gained. Used by per-deck
    ``clean`` in pool mode and by ``pool migrate`` for a whole course.

    Refuses (returns 0, deletes nothing) when the pool and the local dir are
    the same directory or one contains the other: the rmtree would take the
    pool with it.
    """
    legacy = default_audio_dir(pdf_path)
    if not legacy.is_dir():
        return 0
    if paths_overlap(legacy, pool):
        logger.warning("not retiring %s: it overlaps the pool %s", legacy, pool)
        return 0
    adopted = adopt_legacy_audio(pdf_path, pool)
    trash = legacy / TRASH_DIRNAME
    if trash.is_dir():  # parked paid clips from an earlier clean: keep them parked
        (pool / TRASH_DIRNAME).mkdir(parents=True, exist_ok=True)
        for f in trash.iterdir():
            dst = pool / TRASH_DIRNAME / f.name
            if f.is_file() and not dst.exists():
                shutil.move(str(f), str(dst))
    shutil.rmtree(legacy)
    return adopted


def prune_local_orphans(
    pdf_path: Path,
    sidecar_path: Path | None = None,
    *,
    orphaned_since: dict[str, float] | None = None,
    grace_s: float = 0.0,
    now: float | None = None,
) -> CleanResult:
    """Drop cheap-to-regenerate clips that no deck in the folder says any more.

    Called automatically after a sidecar edit or a generated clip. Only
    backends flagged ``auto_prune_orphans`` (real-time local audio like Kokoro)
    are reclaimed; paid (Inworld) and slow (Qwen3) clips, renders and
    unrecognized names are never touched. The live set covers every narrated
    deck in the folder plus *sidecar_path* (the ``--narration`` override the
    editor is working on), so a sibling deck's clips and a clip just generated
    for the override both survive. A deck that can't be read makes the sweep
    do nothing.

    *orphaned_since* (clip name → when it was first seen orphaned, on the
    *now* clock) carries state between sweeps: an orphan is deleted only after
    it stayed orphaned for *grace_s*, and a clip that becomes live again
    forgets its clock — so trying a voice and reverting costs nothing.
    """
    res = resolve_audio_dir(pdf_path, load_config(pdf_path))
    if res.shared:
        # Another deck on the pool may still say what this one just edited away.
        return CleanResult(pool=res.path)
    try:
        own = _own_roots(pdf_path, sidecar_path)
        plan = plan_prune(res.path, own, "current", protect=sibling_decks(pdf_path))
    except PoolError as e:
        logger.warning("Not sweeping orphaned clips: %s", e)
        return CleanResult()
    since = orphaned_since if orphaned_since is not None else {}
    at = time.monotonic() if now is None else now
    orphans = {f.name: f for f in plan.delete}
    for name in [n for n in since if n not in orphans]:
        del since[name]  # live again (or gone): its grace clock starts over next time
    result = CleanResult(kept_files=len(plan.kept))
    for name, f in orphans.items():
        if at - since.setdefault(name, at) < grace_s:
            result.deferred_files += 1
            continue
        del since[name]
        if f.is_file():
            result.removed_bytes += f.stat().st_size
            f.unlink()
            result.removed_files += 1
    return result


def _review_base_blocks(pdf_path: Path) -> list[PageNarration]:
    """Narration held by the review base — still compared (and played) against
    the current text, so its clips count as in use until the base moves on."""
    from slidesonnet.review.base import load_base

    base = load_base(pdf_path)
    if base is None:
        return []
    return [
        block
        for slide in base.slides.values()
        if slide.narration
        for block in parse_sidecar(slide.narration)
    ]


def _speech_plan(
    pdf_path: Path, sidecar_path: Path | None = None
) -> tuple[Config, list[tuple[Segment, str | None]], dict[str, VoiceConfig]]:
    """Config, speech rows, and the voice map synthesis sees — so clean predicts
    the exact cache keys synthesis writes.

    Each row is ``(speech segment, effective voice preset)`` where the preset is
    ``seg.voice or deck.default_voice`` — the same fallback ``audio/synth``
    applies; the text an engine is sent comes from ``config.speech_text``, as in
    synth. ``voices`` merges the deck preamble's portable voice layer over config
    presets (deck wins), mirroring synth. Without both, a default- or
    preamble-voiced clip resolves to the wrong (or ``None``) voice and a current
    clip — notably paid Inworld audio whose name carries a concrete voice id — is
    mistaken for an orphan and deleted.
    """
    config = load_config(pdf_path)
    deck, _ = load_deck(pdf_path, sidecar_path=sidecar_path)
    voices = {**config.voices, **deck.voices}
    rows: list[tuple[Segment, str | None]] = []
    for block in [*deck.narration.values(), *_review_base_blocks(pdf_path)]:
        for seg in block.speech_segments:
            rows.append((seg, seg.voice or deck.default_voice))
    return config, rows, voices


def current_text_hashes(pdf_path: Path, sidecar_path: Path | None = None) -> set[str]:
    """text_hashes for current utterances across all backends (engine-agnostic).

    A named preset contributes every per-backend voice id it maps to (plus the
    bare default-voice variant), so a clip on any engine — including paid Inworld,
    whose name resolves to a concrete voice id — is recognized as current. Each
    engine's form of the line counts (an inline pronunciation fix reads
    differently to Inworld than to Kokoro).
    """
    config, rows, voices = _speech_plan(pdf_path, sidecar_path)
    hashes: set[str] = set()
    for seg, preset in rows:
        voice_ids: set[str | None] = {None}
        cfg = voices.get(preset) if preset else None
        if cfg is not None:
            voice_ids |= cfg.all_voice_ids()  # every backend's voice id for this preset
        elif preset:
            voice_ids.add(preset)  # a raw backend voice id, passed through unchanged
        for text in {config.speech_text(seg, backend) for backend in BACKENDS}:
            for voice in voice_ids:
                hashes.add(text_hash(text, voice))
    return hashes


def current_filenames(pdf_path: Path, sidecar_path: Path | None = None) -> set[str]:
    """Expected audio filenames for the current text + active engine config.

    Mirrors the synthesis path: a paced utterance embeds its multiplied speed
    in the engine cache key, so its expected name comes from the pace-adjusted
    engine, not the base one; and the voice is resolved against the deck preamble
    + config presets for the active backend (default voice included).
    """
    config, rows, voices = _speech_plan(pdf_path, sidecar_path)
    engines: dict[float, TTSEngine] = {}
    names: set[str] = set()
    for seg, preset in rows:
        tts = engine_for_pace(config.tts, seg.pace, engines)
        voice = resolve_voice(preset, voices, config.tts.backend)
        names.add(audio_filename(config.speech_text(seg), tts.name(), tts.cache_key(), voice))
    return names
