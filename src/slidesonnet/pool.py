"""The shared speech-clip pool: what's in it, what still uses it, what can go.

A pool is just an audio directory (see :mod:`slidesonnet.cache`) that more than
one deck — or more than one checkout of the same deck — writes into. Clips are
content-addressed, so nothing here needs to know which deck *produced* a clip;
the only question that matters is whether *any* deck still *uses* it. Pruning
is therefore mark-and-sweep: every deck's sidecar names the clips it expects,
the union of those is the live set, and the rest are orphans.

Two safety layers sit on top of that:

* **Quarantine.** An orphan from a backend whose audio is expensive (paid
  Inworld, slow own-voice Qwen3) is moved into ``<pool>/trash/`` rather than
  unlinked, so a wrong sweep is a ``mv`` back instead of a re-bill. Cheap local
  clips are deleted outright. ``empty_trash`` is the deliberate second step.
* **An advisory index** (``<pool>/index.jsonl``): one line per clip per deck
  that used it, with a text snippet. It is *never* consulted to decide what to
  delete — that's what the sidecars are for — it exists so a dry run can say
  "this clip said *Welcome back* and was last used by 04-50" instead of listing
  bare hashes. Lines are appended (atomic for their size), so several sessions
  can write at once and the worst case is a missing snippet.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.hashing import parse_audio_filename
from slidesonnet.tts import AUTO_PRUNE_BACKENDS

logger = logging.getLogger(__name__)

INDEX_FILENAME = "index.jsonl"
TRASH_DIRNAME = "trash"
_SNIPPET_CHARS = 80

PoolKeep = Literal["api", "current", "exact"]


class PoolError(SlideSonnetError):
    """A pool operation could not be planned safely."""


# ---- advisory index ------------------------------------------------------------


@dataclass(frozen=True)
class IndexRecord:
    """One appended line: *deck* used *file* (which says *text*) on *at*."""

    file: str
    text: str
    voice: str | None
    backend: str
    deck: str
    at: str


@dataclass
class IndexEntry:
    """What the index knows about one clip, merged over its records."""

    file: str
    text: str
    voice: str | None
    backend: str
    decks: list[str] = field(default_factory=list)
    last_used: str = ""


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def snippet(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _SNIPPET_CHARS else text[: _SNIPPET_CHARS - 1] + "…"


def append_index(pool: Path, records: Iterable[IndexRecord]) -> None:
    lines = [json.dumps(r.__dict__, ensure_ascii=False) + "\n" for r in records]
    if not lines:
        return
    pool.mkdir(parents=True, exist_ok=True)
    with (pool / INDEX_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write("".join(lines))


def load_index(pool: Path) -> dict[str, IndexEntry]:
    path = pool / INDEX_FILENAME
    entries: dict[str, IndexEntry] = {}
    if not path.is_file():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            raw = json.loads(line)
            rec = IndexRecord(**raw)
        except (ValueError, TypeError):
            continue  # a torn or foreign line: advisory data, never worth failing over
        entry = entries.get(rec.file)
        if entry is None:
            entry = IndexEntry(rec.file, rec.text, rec.voice, rec.backend)
            entries[rec.file] = entry
        if rec.deck not in entry.decks:
            entry.decks.append(rec.deck)
        entry.last_used = max(rec.at, entry.last_used)
    return entries


def _rewrite_index(pool: Path, entries: dict[str, IndexEntry]) -> None:
    """Compact the index to one line per (clip, deck), atomically."""
    path = pool / INDEX_FILENAME
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for e in entries.values():
            for deck in e.decks:
                fh.write(
                    json.dumps(
                        IndexRecord(e.file, e.text, e.voice, e.backend, deck, e.last_used).__dict__,
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    os.replace(tmp, path)


# ---- prune ---------------------------------------------------------------------


@dataclass
class PrunePlan:
    """What a prune would do; nothing has been touched yet."""

    pool: Path
    keep: PoolKeep
    decks: list[Path]
    kept: list[Path] = field(default_factory=list)
    delete: list[Path] = field(default_factory=list)  # cheap local clips
    quarantine: list[Path] = field(default_factory=list)  # paid / expensive clips → trash/
    unknown: list[Path] = field(default_factory=list)  # unrecognized names, always left alone

    @property
    def empty(self) -> bool:
        return not self.delete and not self.quarantine


@dataclass
class PruneResult:
    deleted_files: int = 0
    deleted_bytes: int = 0
    quarantined_files: int = 0
    quarantined_bytes: int = 0
    trash_dir: Path | None = None


def _live_names(pool: Path, decks: Sequence[Path], keep: PoolKeep) -> tuple[set[str], set[str]]:
    """(text hashes, exact filenames) every deck still expects — the GC roots."""
    from slidesonnet.clean import current_filenames, current_text_hashes

    hashes: set[str] = set()
    names: set[str] = set()
    for deck in decks:
        try:
            if keep == "current":
                hashes |= current_text_hashes(deck)
            elif keep == "exact":
                names |= current_filenames(deck)
        except Exception as e:  # any load failure: the deck can't vouch for its clips
            raise PoolError(
                f"can't read {deck} ({e}); refusing to prune {pool} without knowing "
                "which clips it still needs"
            ) from e
    return hashes, names


def plan_prune(pool: Path, decks: Sequence[Path], keep: PoolKeep = "current") -> PrunePlan:
    """Decide each clip's fate under *keep*, given every deck that uses *pool*.

    ``api``: keep only paid-backend clips (no decks needed). ``current``: keep a
    clip whose utterance text (+ voice) some deck still says, on any engine.
    ``exact``: keep only clips some deck would synthesize under its *current*
    engine config. A deck that fails to load aborts the plan (:class:`PoolError`)
    rather than silently counting as "uses nothing".
    """
    plan = PrunePlan(pool=pool, keep=keep, decks=list(decks))
    if not pool.is_dir():
        return plan
    hashes, names = _live_names(pool, decks, keep)
    for f in sorted(pool.iterdir()):
        if not f.is_file():
            continue
        parsed = parse_audio_filename(f.name)
        if parsed is None:
            plan.unknown.append(f)
            continue
        th, backend, _ = parsed
        if keep == "api":
            live = _is_paid(backend)
        elif keep == "current":
            live = th in hashes
        else:
            live = f.name in names
        if live:
            plan.kept.append(f)
        elif backend in AUTO_PRUNE_BACKENDS:
            plan.delete.append(f)
        else:
            plan.quarantine.append(f)
    return plan


def _is_paid(backend: str) -> bool:
    from slidesonnet.tts import API_BACKENDS

    return backend in API_BACKENDS


def apply_prune(plan: PrunePlan) -> PruneResult:
    """Carry out *plan*: delete cheap orphans, park expensive ones in ``trash/``."""
    result = PruneResult()
    for f in plan.delete:
        result.deleted_bytes += f.stat().st_size
        f.unlink()
        result.deleted_files += 1
    if plan.quarantine:
        trash = plan.pool / TRASH_DIRNAME
        trash.mkdir(parents=True, exist_ok=True)
        result.trash_dir = trash
        for f in plan.quarantine:
            result.quarantined_bytes += f.stat().st_size
            shutil.move(str(f), str(trash / f.name))
            result.quarantined_files += 1
    # Compact the index: forget deleted clips, keep quarantined ones so the
    # trash can still be described.
    entries = load_index(plan.pool)
    if entries:
        gone = {f.name for f in plan.delete}
        _rewrite_index(plan.pool, {k: v for k, v in entries.items() if k not in gone})
    logger.info(
        "pruned pool %s: deleted %d, quarantined %d, kept %d",
        plan.pool,
        result.deleted_files,
        result.quarantined_files,
        len(plan.kept),
    )
    return result


def empty_trash(pool: Path) -> tuple[int, int]:
    """Delete quarantined clips for good. Returns ``(files, bytes)``."""
    trash = pool / TRASH_DIRNAME
    if not trash.is_dir():
        return 0, 0
    files = [f for f in trash.iterdir() if f.is_file()]
    size = sum(f.stat().st_size for f in files)
    shutil.rmtree(trash)
    entries = load_index(pool)
    names = {f.name for f in files}
    if entries and names & set(entries):
        _rewrite_index(pool, {k: v for k, v in entries.items() if k not in names})
    return len(files), size


# ---- status ------------------------------------------------------------------


@dataclass
class PoolStatus:
    pool: Path
    exists: bool
    by_backend: dict[str, tuple[int, int]] = field(default_factory=dict)  # name → (files, bytes)
    unknown: tuple[int, int] = (0, 0)
    trash: tuple[int, int] = (0, 0)
    indexed: int = 0

    @property
    def total_files(self) -> int:
        return sum(n for n, _ in self.by_backend.values()) + self.unknown[0]

    @property
    def total_bytes(self) -> int:
        return sum(b for _, b in self.by_backend.values()) + self.unknown[1]


def pool_status(pool: Path) -> PoolStatus:
    st = PoolStatus(pool=pool, exists=pool.is_dir())
    if not st.exists:
        return st
    unknown_n = unknown_b = 0
    for f in pool.iterdir():
        if not f.is_file():
            continue
        parsed = parse_audio_filename(f.name)
        if parsed is None:
            if f.name != INDEX_FILENAME:
                unknown_n += 1
                unknown_b += f.stat().st_size
            continue
        n, b = st.by_backend.get(parsed[1], (0, 0))
        st.by_backend[parsed[1]] = (n + 1, b + f.stat().st_size)
    st.unknown = (unknown_n, unknown_b)
    trash = pool / TRASH_DIRNAME
    if trash.is_dir():
        files = [f for f in trash.iterdir() if f.is_file()]
        st.trash = (len(files), sum(f.stat().st_size for f in files))
    st.indexed = len(load_index(pool))
    return st
