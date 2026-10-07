"""Deck discovery and the token registry behind inter-deck navigation.

The editor addresses decks by an opaque token rather than by path: the page
route is ``/d/{token}`` and media is served from ``/ssmedia/{token}/…``. The
token is a hash of the *resolved* deck path, so it is stable across restarts
(bookmarks survive) while the registry gates which decks exist at all — the URL
bar can't coax the editor into opening an arbitrary PDF off disk.

Discovery walks *down* from a root directory (``--root``, the directory passed
to ``edit``, or the cwd) looking for a ``*.pdf`` with a sibling
``<stem>.narration``. No VCS assumption: a course tree needn't be a repo, and a
repo root is as often too wide (a monorepo) as too narrow. The walk is capped in
directories visited, so launching from ``$HOME`` reports a truncated scan instead
of hanging; folders deeper than ``max_depth`` are walked last, with whatever of
that budget is left, so it goes to the shallow folders decks live in first.
The library can then move to another folder mid-session (up to a course, or
into one week): see :meth:`DeckRegistry.move_to`.

Depth never cuts the scan short by itself. ``pool prune --root`` deletes the
clips no *found* deck says, so a deck the scan skipped would lose its audio; a
course's deep build output (a site's ``dist/``) must neither block a prune nor
hide a deck that really lives down there. Only the folder cap truncates, and the
result says where it stopped so a caller can refuse and explain.

Pure logic — no web framework imports, so it is testable without a server.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from slidesonnet.builds import deck_pdf, default_sidecar_path, working_pdf
from slidesonnet.cache import CACHE_DIRNAME

logger = logging.getLogger(__name__)

#: Directories never worth walking into. Dot-directories are pruned wholesale
#: (which covers ``.git``/``.venv``/``.slidesonnet``); these are the rest.
#: ``cache`` is the pre-1.0 per-deck cache folder: older checkouts still have
#: one beside each deck, full of per-slide PDFs that would list as phantom decks.
_PRUNED = frozenset({"node_modules", "__pycache__", "site-packages", "venv", "cache"})

_TOKEN_CHARS = 8


@dataclass(frozen=True)
class ScanLimits:
    """Bounds on a discovery walk, so a scan can never hang the editor."""

    #: Folders deeper than this below the root are walked after all shallower ones.
    max_depth: int = 6
    #: Folders visited before the walk stops (and the result is truncated).
    max_dirs: int = 5000


#: The limits a scan uses when none are given.
DEFAULT_LIMITS = ScanLimits()


def deck_token(pdf_path: Path) -> str:
    """A short, stable id for the deck at *pdf_path*.

    Derived from the resolved path, so two spellings of one deck agree and the
    token survives a restart (bookmarked deck URLs keep working).
    """
    resolved = str(Path(pdf_path).resolve())
    return hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:_TOKEN_CHARS]


def natural_key(text: str) -> tuple[object, ...]:
    """Sort key that orders embedded numbers numerically (``week9`` < ``week10``).

    A course list sorted lexically puts ``week10`` before ``week9``, which reads
    as a bug every single time.
    """
    parts = re.split(r"(\d+)", text)
    return tuple((1, int(p)) if p.isdigit() else (0, p.lower()) for p in parts)


@dataclass(frozen=True)
class DeckEntry:
    """One deck in the library: where it is, what to call it, how to address it."""

    pdf_path: Path
    sidecar_path: Path | None
    token: str
    #: Directory holding the deck, relative to the scan root ("" at the root).
    group: str
    #: The deck's file stem — what a human calls it.
    name: str

    @property
    def label(self) -> str:
        """``week02/llm_basics/llm_basics`` — the searchable, displayable path."""
        return f"{self.group}/{self.name}" if self.group else self.name

    @property
    def section(self) -> str:
        """Top-level folder under the root — the library's section heading.

        Decks usually sit one-per-folder (``week02/<deck>/<deck>.pdf``), so
        grouping by the full :attr:`group` would make every section a section of
        one; the first component (``week02``) is the grouping a human means.
        Empty for a deck sitting directly in the root.
        """
        return self.group.split("/", 1)[0] if self.group else ""

    @classmethod
    def build(cls, pdf_path: Path, *, root: Path, sidecar_path: Path | None = None) -> DeckEntry:
        """Describe the deck at *pdf_path*, named relative to *root*.

        *sidecar_path* overrides the default ``<stem>.narration``; pass ``None``
        to use the default when it exists (and to mark the deck un-narrated when
        it does not).
        """
        pdf = working_pdf(pdf_path.resolve())  # a deck opens on its plain build, if any
        sidecar = sidecar_path.resolve() if sidecar_path is not None else None
        if sidecar is None:
            default = default_sidecar_path(pdf)
            sidecar = default if default.is_file() else None
        try:
            group = pdf.parent.relative_to(Path(root).resolve()).as_posix()
        except ValueError:  # deck outside the root (an explicitly opened one)
            group = pdf.parent.name
        return cls(
            pdf_path=pdf,
            sidecar_path=sidecar,
            token=deck_token(pdf),
            group="" if group == "." else group,
            name=deck_pdf(pdf).stem,
        )


@dataclass
class ScanResult:
    """What a discovery walk found, and whether it saw everything."""

    decks: list[DeckEntry] = field(default_factory=list)
    #: PDFs with no sidecar — offered as "scaffold a narration here".
    unnarrated: list[DeckEntry] = field(default_factory=list)
    #: Folders the walk looked into.
    visited: int = 0
    #: The first folder the folder cap kept the walk from (None: it saw everything).
    stopped_at: Path | None = None
    #: How many known folders went unvisited when the cap hit (``stopped_at`` included).
    unvisited: int = 0

    @property
    def truncated(self) -> bool:
        """True when the folder cap stopped the walk early: the lists may be incomplete."""
        return self.stopped_at is not None


def _prunable(name: str) -> bool:
    return name.startswith(".") or name in _PRUNED or name == CACHE_DIRNAME


def discover_decks(root: Path, *, limits: ScanLimits | None = None) -> ScanResult:
    """Find decks under *root*, walking down within *limits*.

    A deck is a ``*.pdf`` with a sibling ``<stem>.narration`` (its plain build
    ``<stem>.plain.pdf``, when present, is the same deck); a PDF without one
    lands in :attr:`ScanResult.unnarrated`. Results are naturally sorted by
    label. Folders below ``limits.max_depth`` are walked after every shallower
    one; only ``limits.max_dirs`` truncates the walk (see the module docstring).
    Unreadable directories are skipped rather than raising — a library listing
    must never be the thing that fails.
    """
    limits = limits or DEFAULT_LIMITS
    root = Path(root).resolve()
    result = ScanResult()
    if not root.is_dir():
        return result

    shallow: list[tuple[Path, int]] = [(root, 0)]
    deep: list[Path] = []  # past max_depth: walked once the shallow folders are done
    seen: set[str] = set()
    while shallow or deep:
        directory, depth = shallow.pop() if shallow else (deep.pop(), limits.max_depth + 1)
        if result.visited >= limits.max_dirs:
            result.stopped_at = directory
            result.unvisited = 1 + len(shallow) + len(deep)
            break
        result.visited += 1
        try:
            children = sorted(directory.iterdir())
        except OSError as exc:  # unreadable dir: skip it, keep the scan alive
            logger.debug("skipping %s during deck scan: %s", directory, exc)
            continue
        for child in children:
            if child.is_dir():
                if _prunable(child.name):
                    continue
                if depth + 1 > limits.max_depth:
                    deep.append(child)
                else:
                    shallow.append((child, depth + 1))
            elif child.suffix.lower() == ".pdf":
                entry = DeckEntry.build(child, root=root)
                if entry.token in seen:
                    continue  # the deck's other build: listed once, by its working build
                seen.add(entry.token)
                target = result.decks if entry.sidecar_path else result.unnarrated
                target.append(entry)

    result.decks.sort(key=lambda e: natural_key(e.label))
    result.unnarrated.sort(key=lambda e: natural_key(e.label))
    return result


class DeckRegistry:
    """The decks this editor process will serve, addressed by token.

    Holds the scanned library plus any deck opened explicitly (which may live
    outside the root — ``edit ../other/deck.pdf`` must still work). Only decks
    in here resolve, so a token from the URL bar can't reach an arbitrary file.
    """

    def __init__(self, root: Path, *, limits: ScanLimits | None = None) -> None:
        self.root = Path(root).resolve()
        self.limits = limits or ScanLimits()
        self._scanned: ScanResult = ScanResult()
        #: Explicitly opened decks (and sidecar overrides), which survive rescans.
        self._pinned: dict[str, DeckEntry] = {}
        #: Decks listed under an earlier root: no longer listed, still openable.
        self._retired: dict[str, DeckEntry] = {}

    # ---- population ----------------------------------------------------
    def rescan(self) -> ScanResult:
        """Re-walk the root. Pinned decks are kept; everything else is replaced."""
        self._scanned = discover_decks(self.root, limits=self.limits)
        return self._scanned

    def move_to(self, root: Path) -> ScanResult:
        """Make *root* the library's folder and scan it.

        Decks found under the old root stay openable (a deck open in the editor
        keeps working, at the same token) but leave the listing. Pinned decks
        are renamed relative to the new root. Raises :class:`NotADirectoryError`
        (or :class:`FileNotFoundError`) when *root* isn't a folder.
        """
        try:
            root = Path(root).resolve()
        except (OSError, ValueError) as exc:  # a symlink loop, a NUL byte: no such folder
            raise FileNotFoundError(root) from exc
        if not root.exists():
            raise FileNotFoundError(root)
        if not root.is_dir():
            raise NotADirectoryError(root)
        self._retired.update({e.token: e for e in self._scanned.decks})
        self.root = root
        self._pinned = {
            token: DeckEntry.build(e.pdf_path, root=root, sidecar_path=e.sidecar_path)
            for token, e in self._pinned.items()
        }
        return self.rescan()

    def register(self, pdf_path: Path, *, sidecar_path: Path | None = None) -> DeckEntry:
        """Pin an explicitly opened deck (with an optional sidecar override)."""
        entry = DeckEntry.build(pdf_path, root=self.root, sidecar_path=sidecar_path)
        self._pinned[entry.token] = entry
        return entry

    # ---- lookup --------------------------------------------------------
    def entries(self) -> list[DeckEntry]:
        """Every narrated deck, library order — pinned decks merged in by token."""
        merged = {e.token: e for e in self._scanned.decks}
        merged.update(self._pinned)
        return sorted(merged.values(), key=lambda e: natural_key(e.label))

    def unnarrated(self) -> list[DeckEntry]:
        """PDFs found without a sidecar (never pinned — nothing to open yet)."""
        pinned = set(self._pinned)
        return [e for e in self._scanned.unnarrated if e.token not in pinned]

    def truncated(self) -> bool:
        """True when the last scan hit a cap and the library may be incomplete."""
        return self._scanned.truncated

    def resolve(self, token: str) -> DeckEntry | None:
        """The deck for *token*, or ``None`` when it isn't one of ours."""
        found = next((e for e in self.entries() if e.token == token), None)
        return found if found is not None else self._retired.get(token)

    def parents(self) -> list[str]:
        """Names of the folders above the root, outermost first.

        Starts at ``~`` when the root is inside the home folder (the folders
        above it are rarely where decks live), else at the filesystem's root.
        Item *i* is ``len(parents) - i`` folders up.
        """
        home = Path.home().resolve()
        names: list[str] = []
        for folder in self.root.parents:
            if folder == home:
                names.append("~")
                break
            names.append(folder.name or folder.anchor)
        return names[::-1]

    def grouped(self) -> list[tuple[str, list[DeckEntry]]]:
        """Decks bucketed by :attr:`DeckEntry.section`, in library order.

        Section order follows the decks themselves, so the natural sort carries
        through (``week9`` before ``week10``) without re-deriving it here.
        """
        sections: dict[str, list[DeckEntry]] = {}
        for entry in self.entries():
            sections.setdefault(entry.section, []).append(entry)
        return list(sections.items())

    def neighbour(self, token: str, delta: int) -> DeckEntry | None:
        """The deck *delta* steps from *token* in library order, wrapping around.

        Wrapping keeps a sequential audit pass from dead-ending at the last deck.
        Returns ``None`` only when *token* isn't registered.
        """
        entries = self.entries()
        index = next((i for i, e in enumerate(entries) if e.token == token), None)
        if index is None:
            return None
        return entries[(index + delta) % len(entries)]
