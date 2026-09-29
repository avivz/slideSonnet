"""Review operations: what ``slidesonnet review …`` and the editor call.

Everything that changes review state goes through here, as an append to the
deck's ``.review`` log (see :mod:`slidesonnet.review.log`) or — for Clear — a
compaction plus advancing the stored base (:mod:`slidesonnet.review.base`).
Deck sources (``.tex``, ``.narration``) are never touched.

Every write is one :func:`transaction`: the cross-process review lock is held
from reading the log, through deciding (ids, validity), to appending,
compacting or saving the base, so concurrent writers (the editor and an agent)
never share an id or drop each other's records.

Functions that capture the deck take an optional *sidecar_path* for a deck
opened with an explicit ``--narration`` file (default: ``<deck>.narration``).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

from slidesonnet.deck import dedupe_page_ids, load_deck
from slidesonnet.exceptions import ReviewError
from slidesonnet.pdf.reader import is_final_build, read_page_ids
from slidesonnet.review import base as base_mod
from slidesonnet.review.diff import SlideChange, diff_versions
from slidesonnet.review.log import (
    FORMAT_HEADER,
    Author,
    Conversation,
    Record,
    ReviewState,
    append_unlocked,
    locked,
    now,
    read_records,
    read_state,
    write_records_unlocked,
)
from slidesonnet.review.versions import DeckVersion, PageCapture, capture, combine

AUTHOR_EDIT_NOTE = "The author edited the narration of @{slide}."


def review_path(pdf_path: Path) -> Path:
    """``<deck>.review`` next to the PDF (like the ``.narration`` sidecar)."""
    return pdf_path.resolve().with_suffix(".review")


def _lock(pdf_path: Path) -> Path:
    return base_mod.base_dir(pdf_path) / "review.lock"


class Transaction:
    """The review state, read under the lock, and the writes that go with it."""

    def __init__(self, pdf_path: Path) -> None:
        self.pdf_path = pdf_path
        self.path = review_path(pdf_path)
        self.state = read_state(self.path)

    def append(self, *records: Record) -> None:
        append_unlocked(self.path, *records)

    def rewrite(self, records: list[Record]) -> None:
        """Compact the log to *records*, keeping the id high-water mark."""
        write_records_unlocked(self.path, records, last_id=self.state.max_id())

    def ensure_file(self) -> None:
        if not self.path.exists():
            self.path.write_text(FORMAT_HEADER + "\n", encoding="utf-8")


@contextlib.contextmanager
def transaction(pdf_path: Path) -> Iterator[Transaction]:
    """Hold the deck's review lock across load → decide → write.

    Only unlocked helpers may run inside: ``flock`` locks belong to an open
    file, so taking the lock again from inside would deadlock.
    """
    with locked(_lock(pdf_path)):
        yield Transaction(pdf_path)


def is_active(pdf_path: Path) -> bool:
    """Review is on once the deck has a base (the editor takes one when it first
    opens a deck) or a ``<deck>.review`` log (an older start, or the CLI)."""
    return review_path(pdf_path).exists() or base_mod.has_base(pdf_path)


def start(pdf_path: Path, *, sidecar_path: Path | None = None) -> DeckVersion:
    """Enter review mode: take the base from the deck as it is now and create
    ``<deck>.review``. Changes from here on are compared against this base."""
    with transaction(pdf_path) as txn:
        version = base_mod.snapshot(pdf_path, sidecar_path=sidecar_path)
        txn.ensure_file()
    return version


def mark_seen(pdf_path: Path, *, sidecar_path: Path | None = None) -> DeckVersion:
    """Everything as it is now becomes the base (the log is untouched)."""
    with transaction(pdf_path):
        return base_mod.snapshot(pdf_path, sidecar_path=sidecar_path)


def load(pdf_path: Path) -> ReviewState:
    return read_state(review_path(pdf_path))


# ---- status ----------------------------------------------------------------------


@dataclass
class ReviewStatus:
    """Where review stands: diffs against the base, conversations, unfiled changes."""

    state: ReviewState
    changes: list[SlideChange] = field(default_factory=list)
    unfiled: list[str] = field(default_factory=list)  # changed, in no conversation
    # declared in an open conversation but in neither the base nor the PDF yet
    # (a slide the agent is about to compile, or a typo): slide id -> conversations
    pending: dict[str, list[str]] = field(default_factory=dict)
    final_build: bool = False  # comparison paused: the PDF is a final build
    base: DeckVersion | None = None
    current: DeckVersion | None = None


def ensure_base(pdf_path: Path, *, sidecar_path: Path | None = None) -> DeckVersion | None:
    """The stored base, taking it now on first use (None on a final build)."""
    base = base_mod.load_base(pdf_path)
    if base is not None or is_final_build(pdf_path):
        return base
    with transaction(pdf_path):
        base = base_mod.load_base(pdf_path)  # another writer may have taken it meanwhile
        if base is None:
            base = base_mod.snapshot(pdf_path, sidecar_path=sidecar_path)
    return base


def _current(pdf_path: Path, pages: PageCapture | None, sidecar_path: Path | None) -> DeckVersion:
    if pages is None:
        return capture(
            pdf_path, sidecar_path=sidecar_path, reference=base_mod.reference_images(pdf_path)
        )
    return combine(pages, load_deck(pdf_path, sidecar_path=sidecar_path)[0].narration)


def status(
    pdf_path: Path, *, pages: PageCapture | None = None, sidecar_path: Path | None = None
) -> ReviewStatus:
    """Read current review state; *pages*, if supplied, must match the PDF on disk."""
    state = load(pdf_path)
    if is_final_build(pdf_path):
        return ReviewStatus(state=state, final_build=True, base=base_mod.load_base(pdf_path))
    base = ensure_base(pdf_path, sidecar_path=sidecar_path)
    assert base is not None  # a plain build always yields one
    current = _current(pdf_path, pages, sidecar_path)
    changes = diff_versions(base, current)
    filed = {sid for c in state.slide_conversations() for sid in c.slides}
    unfiled = [c.slide_id for c in changes if c.slide_id not in filed]
    pending: dict[str, list[str]] = {}
    for conv in state.slide_conversations():
        if conv.status != "open":
            continue
        for sid in conv.slides:
            if sid not in base.slides and sid not in current.slides:
                pending.setdefault(sid, []).append(conv.id)
    return ReviewStatus(
        state=state,
        changes=changes,
        unfiled=unfiled,
        pending=pending,
        base=base,
        current=current,
    )


def open_slide_conversations(pdf_path: Path) -> list[Conversation]:
    """Open conversations about slides (the deck conversation never counts)."""
    return [c for c in load(pdf_path).slide_conversations() if c.status == "open"]


# ---- conversation actions ----------------------------------------------------------


def _known_ids(pdf_path: Path) -> set[str]:
    ids: set[str] = set()
    base = base_mod.load_base(pdf_path)
    if base is not None:
        ids |= set(base.slides)
    ids |= {p for p in dedupe_page_ids(read_page_ids(pdf_path))[0] if p}
    return ids


def not_in_deck(pdf_path: Path, slide_ids: list[str]) -> list[str]:
    """The ids in *slide_ids* that are in neither the base nor the compiled PDF.

    Declaring them is allowed — the agent declares a new slide, then compiles —
    so callers only point them out; ``status`` keeps listing them as pending.
    """
    known = _known_ids(pdf_path)
    return [s.removeprefix("@") for s in slide_ids if s.removeprefix("@") not in known]


def _check_slides(slide_ids: list[str]) -> None:
    if any(not s.strip() for s in slide_ids):
        raise ReviewError("empty slide id")


def _conversation(state: ReviewState, conv_id: str) -> Conversation:
    conv = state.conversations.get(conv_id)
    if conv is None:
        raise ReviewError(f"no conversation '{conv_id}'")
    return conv


def comment(
    pdf_path: Path, slide_ids: list[str], text: str, *, author: Author = "author", title: str = ""
) -> str:
    """Open a new conversation about *slide_ids*; return its id."""
    slide_ids = [s.removeprefix("@") for s in slide_ids]
    if not slide_ids:
        raise ReviewError(
            "a conversation needs at least one slide — for the whole deck, "
            "write in the deck conversation instead"
        )
    _check_slides(slide_ids)
    ensure_base(pdf_path)
    with transaction(pdf_path) as txn:
        conv_id = txn.state.next_id()
        txn.append(
            Record("open", conv_id, now(), author, slides=tuple(slide_ids), text=text, title=title)
        )
    return conv_id


def reply(
    pdf_path: Path,
    conv_id: str,
    text: str,
    *,
    author: Author = "agent",
    add_slides: list[str] | None = None,
    title: str = "",
) -> None:
    """Add a message to a conversation, optionally widening its slide scope or renaming it."""
    added = [s.removeprefix("@") for s in add_slides or []]
    with transaction(pdf_path) as txn:
        conv = _conversation(txn.state, conv_id)
        if added and conv.is_deck:
            raise ReviewError(
                "the deck conversation has no slides — open a slide conversation "
                "for slide changes (`slidesonnet review comment`)"
            )
        if conv.status == "closed":
            raise ReviewError(f"conversation {conv_id} is closed — reopen it first")
        if added:
            _check_slides(added)
        txn.append(
            Record("message", conv_id, now(), author, slides=tuple(added), text=text, title=title)
        )


def retitle(pdf_path: Path, conv_id: str, title: str, *, author: Author = "author") -> None:
    """Name a conversation (open or accepted); the id stays its identifier."""
    title = " ".join(title.split())
    if not title:
        raise ReviewError("a title can't be empty")
    with transaction(pdf_path) as txn:
        _conversation(txn.state, conv_id)
        txn.append(Record("message", conv_id, now(), author, title=title))


def accept(pdf_path: Path, conv_id: str, *, author: Author = "author") -> None:
    with transaction(pdf_path) as txn:
        conv = _conversation(txn.state, conv_id)
        if conv.is_deck:
            raise ReviewError("the deck conversation never closes")
        if conv.status == "closed":
            raise ReviewError(f"conversation {conv_id} is already closed")
        txn.append(Record("accept", conv_id, now(), author))


def reopen(pdf_path: Path, conv_id: str, *, author: Author = "author") -> None:
    with transaction(pdf_path) as txn:
        conv = _conversation(txn.state, conv_id)
        if conv.status == "open":
            raise ReviewError(f"conversation {conv_id} is already open")
        txn.append(Record("reopen", conv_id, now(), author))


def send(pdf_path: Path, *, author: Author = "author") -> None:
    """Release anyone blocked in :func:`wait` (``review wait``)."""
    with transaction(pdf_path) as txn:
        txn.append(Record("send", None, now(), author))


# ---- automatic filing ------------------------------------------------------------


def open_unrequested(pdf_path: Path, slide_ids: list[str]) -> str:
    """Open a system conversation filing *slide_ids* as unrequested changes."""
    note = f"Changed at {now()[11:16]} without a conversation."
    with transaction(pdf_path) as txn:
        conv_id = txn.state.next_id()
        txn.append(
            Record(
                "open",
                conv_id,
                now(),
                "system",
                slides=tuple(slide_ids),
                origin="unrequested",
                text=note,
            )
        )
    return conv_id


def file_unrequested(pdf_path: Path, *, sidecar_path: Path | None = None) -> str | None:
    """File every changed slide that's in no conversation into a new one.

    Returns the new conversation id, or None when nothing was unfiled (or the
    PDF is a final build, where comparison pauses).
    """
    current = status(pdf_path, sidecar_path=sidecar_path)
    if not current.unfiled:
        return None
    return open_unrequested(pdf_path, current.unfiled)


def note_author_edit(pdf_path: Path, slide_id: str) -> None:
    """Record that the author edited *slide_id*'s narration in the editor.

    Each open conversation holding the slide gets a system note (so the agent
    sees the edit instead of overwriting it); without one, the slide joins the
    closed "Your edits" conversation — you don't approve your own changes.
    """
    with transaction(pdf_path) as txn:
        _note_author_edit(txn, slide_id)


def _note_author_edit(txn: Transaction, slide_id: str) -> None:
    state = txn.state
    note = AUTHOR_EDIT_NOTE.format(slide=slide_id)
    open_convs = [
        c for c in state.slide_conversations() if c.status == "open" and slide_id in c.slides
    ]
    if open_convs:
        notes = [
            Record("message", conv.id, now(), "system", text=note)
            for conv in open_convs
            # repeated saves of the same edit: one note is enough
            if not (conv.messages and conv.messages[-1].text == note)
        ]
        if notes:
            txn.append(*notes)
        return
    mine = next(
        (
            c
            for c in state.slide_conversations()
            if c.origin == "author-edits" and c.status == "closed"
        ),
        None,
    )
    if mine is not None:
        if slide_id not in mine.slides:
            txn.append(Record("message", mine.id, now(), "system", slides=(slide_id,)))
        return
    if any(slide_id in c.slides for c in state.slide_conversations()):
        return  # already filed in a closed conversation: its diff covers the edit
    conv_id = state.next_id()
    txn.append(
        Record(
            "open",
            conv_id,
            now(),
            "system",
            slides=(slide_id,),
            origin="author-edits",
            text="Your own edits.",
        ),
        Record("accept", conv_id, now(), "system"),
    )


# ---- clear -------------------------------------------------------------------------


@dataclass
class ClearResult:
    cleared: list[str] = field(default_factory=list)  # conversation ids removed
    advanced: list[str] = field(default_factory=list)  # slides whose base moved
    skipped: list[str] = field(default_factory=list)  # held back by an open conversation
    order_adopted: bool = False


def _pin_slides(rec: Record, state: ReviewState) -> Record:
    """Make a kept record carry its conversation's current slides (on ``open`` only).

    Slides can leave a conversation through another one's records (see
    ``log._claim``); once those are compacted away, the conversation must still
    replay to the same slides.
    """
    conv = state.conversations.get(rec.conv) if rec.conv else None
    if conv is None or conv.is_deck:
        return rec
    if rec.kind == "open":
        return replace(rec, slides=tuple(conv.slides))
    return replace(rec, slides=()) if rec.slides else rec


def clear(
    pdf_path: Path, *, pages: PageCapture | None = None, sidecar_path: Path | None = None
) -> ClearResult:
    """Drop closed conversations and advance the base for their slides.

    A slide that's also in an open conversation keeps its base (it advances
    when that one clears). The base adopts the current slide order unless an
    open conversation holds a moved slide.

    The editor may supply a fresh cached page capture. Narration and the log
    are always read from disk, including when that capture is reused. The deck
    is captured before taking the lock (the slow part); the log is read, the
    base advanced and the log compacted under it.
    """
    if is_final_build(pdf_path):
        raise ReviewError("the PDF is a final build — recompile it normally before clearing")
    ensure_base(pdf_path, sidecar_path=sidecar_path)
    current = _current(pdf_path, pages, sidecar_path)
    with transaction(pdf_path) as txn:
        return _clear(txn, current)


def _clear(txn: Transaction, current: DeckVersion) -> ClearResult:
    pdf_path, state = txn.pdf_path, txn.state
    closed = [c for c in state.slide_conversations() if c.status == "closed"]
    if not closed:
        return ClearResult()
    base = base_mod.load_base(pdf_path)
    assert base is not None  # ensured before the lock; nothing deletes it
    open_slides = {
        sid for c in state.slide_conversations() if c.status == "open" for sid in c.slides
    }
    closed_slides = [sid for c in closed for sid in c.slides]
    advance = sorted({s for s in closed_slides if s not in open_slides})
    skipped = sorted({s for s in closed_slides if s in open_slides})
    moved = {c.slide_id for c in diff_versions(base, current) if c.moved}
    adopt = not (moved & open_slides)
    base_mod.advance(pdf_path, set(advance), adopt_order=adopt, current=current)
    drop = {c.id for c in closed} | state.retired
    records = [
        _pin_slides(r, state)
        for r in read_records(txn.path)
        if r.conv is None or r.conv not in drop
    ]
    txn.rewrite(records)
    return ClearResult(
        cleared=[c.id for c in closed], advanced=advance, skipped=skipped, order_adopted=adopt
    )


# ---- wait --------------------------------------------------------------------------


@dataclass
class WaitResult:
    cursor: int  # pass back as ``since`` next time
    awaiting_agent: list[Conversation]


def wait(
    pdf_path: Path, *, since: int, timeout: float | None = None, poll: float = 1.0
) -> WaitResult | None:
    """Block until a ``send`` beyond *since*; None if *timeout* runs out first."""
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        state = load(pdf_path)
        if state.sends > since:
            awaiting = [
                c for c in state.conversations.values() if c.status == "open" and c.turn == "agent"
            ]
            return WaitResult(cursor=state.sends, awaiting_agent=awaiting)
        if deadline is not None and time.monotonic() >= deadline:
            return None
        time.sleep(poll)
