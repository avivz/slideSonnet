"""Review operations: what ``slidesonnet review …`` and the editor call.

Everything that changes review state goes through here, as an append to the
deck's ``.review`` log (see :mod:`slidesonnet.review.log`) or — for Clear — a
compaction plus advancing the stored base (:mod:`slidesonnet.review.base`).
Deck sources (``.tex``, ``.narration``) are never touched.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from slidesonnet.deck import dedupe_page_ids
from slidesonnet.exceptions import ReviewError
from slidesonnet.pdf.reader import is_final_build, read_page_ids
from slidesonnet.review import base as base_mod
from slidesonnet.review.diff import SlideChange, diff_versions
from slidesonnet.review.log import (
    Author,
    Conversation,
    Record,
    ReviewState,
    append,
    ensure_file,
    now,
    read_records,
    replay,
    write_records,
)
from slidesonnet.review.versions import DeckVersion, capture

AUTHOR_EDIT_NOTE = "The author edited the narration of @{slide}."


def review_path(pdf_path: Path) -> Path:
    """``<deck>.review`` next to the PDF (like the ``.narration`` sidecar)."""
    return pdf_path.resolve().with_suffix(".review")


def _lock(pdf_path: Path) -> Path:
    return base_mod.base_dir(pdf_path) / "review.lock"


def _append(pdf_path: Path, *records: Record) -> None:
    append(review_path(pdf_path), *records, lock_path=_lock(pdf_path))


def is_active(pdf_path: Path) -> bool:
    """Review is on once the deck has a base (the editor takes one when it first
    opens a deck) or a ``<deck>.review`` log (an older start, or the CLI)."""
    return review_path(pdf_path).exists() or base_mod.has_base(pdf_path)


def start(pdf_path: Path) -> DeckVersion:
    """Enter review mode: take the base from the deck as it is now and create
    ``<deck>.review``. Changes from here on are compared against this base."""
    version = base_mod.snapshot(pdf_path)
    ensure_file(review_path(pdf_path), lock_path=_lock(pdf_path))
    return version


def load(pdf_path: Path) -> ReviewState:
    return replay(read_records(review_path(pdf_path)))


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


def ensure_base(pdf_path: Path) -> DeckVersion | None:
    """The stored base, taking it now on first use (None on a final build)."""
    base = base_mod.load_base(pdf_path)
    if base is None and not is_final_build(pdf_path):
        base = base_mod.snapshot(pdf_path)
    return base


def status(pdf_path: Path) -> ReviewStatus:
    state = load(pdf_path)
    if is_final_build(pdf_path):
        return ReviewStatus(state=state, final_build=True, base=base_mod.load_base(pdf_path))
    base = ensure_base(pdf_path)
    assert base is not None  # a plain build always yields one
    current = capture(pdf_path, reference=base_mod.reference_images(pdf_path))
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


def comment(pdf_path: Path, slide_ids: list[str], text: str, *, author: Author = "author") -> str:
    """Open a new conversation about *slide_ids*; return its id."""
    slide_ids = [s.removeprefix("@") for s in slide_ids]
    if not slide_ids:
        raise ReviewError(
            "a conversation needs at least one slide — for the whole deck, "
            "write in the deck conversation instead"
        )
    _check_slides(slide_ids)
    ensure_base(pdf_path)
    conv_id = load(pdf_path).next_id()
    _append(pdf_path, Record("open", conv_id, now(), author, slides=tuple(slide_ids), text=text))
    return conv_id


def reply(
    pdf_path: Path,
    conv_id: str,
    text: str,
    *,
    author: Author = "agent",
    add_slides: list[str] | None = None,
) -> None:
    """Add a message to a conversation, optionally widening its slide scope."""
    added = [s.removeprefix("@") for s in add_slides or []]
    conv = _conversation(load(pdf_path), conv_id)
    if added and conv.is_deck:
        raise ReviewError(
            "the deck conversation has no slides — open a slide conversation "
            "for slide changes (`slidesonnet review comment`)"
        )
    if conv.status == "closed":
        raise ReviewError(f"conversation {conv_id} is closed — reopen it first")
    if added:
        _check_slides(added)
    _append(pdf_path, Record("message", conv_id, now(), author, slides=tuple(added), text=text))


def accept(pdf_path: Path, conv_id: str, *, author: Author = "author") -> None:
    conv = _conversation(load(pdf_path), conv_id)
    if conv.is_deck:
        raise ReviewError("the deck conversation never closes")
    if conv.status == "closed":
        raise ReviewError(f"conversation {conv_id} is already closed")
    _append(pdf_path, Record("accept", conv_id, now(), author))


def reopen(pdf_path: Path, conv_id: str, *, author: Author = "author") -> None:
    conv = _conversation(load(pdf_path), conv_id)
    if conv.status == "open":
        raise ReviewError(f"conversation {conv_id} is already open")
    _append(pdf_path, Record("reopen", conv_id, now(), author))


def send(pdf_path: Path, *, author: Author = "author") -> None:
    """Release anyone blocked in :func:`wait` (``review wait``)."""
    _append(pdf_path, Record("send", None, now(), author))


# ---- automatic filing ------------------------------------------------------------


def open_unrequested(pdf_path: Path, slide_ids: list[str]) -> str:
    """Open a system conversation filing *slide_ids* as unrequested changes."""
    conv_id = load(pdf_path).next_id()
    note = f"Changed at {now()[11:16]} without a conversation."
    _append(
        pdf_path,
        Record(
            "open",
            conv_id,
            now(),
            "system",
            slides=tuple(slide_ids),
            origin="unrequested",
            text=note,
        ),
    )
    return conv_id


def file_unrequested(pdf_path: Path) -> str | None:
    """File every changed slide that's in no conversation into a new one.

    Returns the new conversation id, or None when nothing was unfiled (or the
    PDF is a final build, where comparison pauses).
    """
    current = status(pdf_path)
    if not current.unfiled:
        return None
    return open_unrequested(pdf_path, current.unfiled)


def note_author_edit(pdf_path: Path, slide_id: str) -> None:
    """Record that the author edited *slide_id*'s narration in the editor.

    Each open conversation holding the slide gets a system note (so the agent
    sees the edit instead of overwriting it); without one, the slide joins the
    closed "Your edits" conversation — you don't approve your own changes.
    """
    state = load(pdf_path)
    note = AUTHOR_EDIT_NOTE.format(slide=slide_id)
    open_convs = [
        c for c in state.slide_conversations() if c.status == "open" and slide_id in c.slides
    ]
    if open_convs:
        for conv in open_convs:
            if conv.messages and conv.messages[-1].text == note:
                continue  # repeated saves of the same edit: one note is enough
            _append(pdf_path, Record("message", conv.id, now(), "system", text=note))
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
            _append(pdf_path, Record("message", mine.id, now(), "system", slides=(slide_id,)))
        return
    if any(slide_id in c.slides for c in state.slide_conversations()):
        return  # already filed in a closed conversation: its diff covers the edit
    conv_id = state.next_id()
    _append(
        pdf_path,
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


def clear(pdf_path: Path) -> ClearResult:
    """Drop closed conversations and advance the base for their slides.

    A slide that's also in an open conversation keeps its base (it advances
    when that one clears). The base adopts the current slide order unless an
    open conversation holds a moved slide.
    """
    current = status(pdf_path)
    if current.final_build:
        raise ReviewError("the PDF is a final build — recompile it normally before clearing")
    state = current.state
    closed = [c for c in state.slide_conversations() if c.status == "closed"]
    if not closed:
        return ClearResult()
    open_slides = {
        sid for c in state.slide_conversations() if c.status == "open" for sid in c.slides
    }
    closed_slides = [sid for c in closed for sid in c.slides]
    advance = sorted({s for s in closed_slides if s not in open_slides})
    skipped = sorted({s for s in closed_slides if s in open_slides})
    moved = {c.slide_id for c in current.changes if c.moved}
    adopt = not (moved & open_slides)
    base_mod.advance(pdf_path, set(advance), adopt_order=adopt)
    drop = {c.id for c in closed} | state.retired
    path = review_path(pdf_path)
    records = [
        _pin_slides(r, state) for r in read_records(path) if r.conv is None or r.conv not in drop
    ]
    write_records(path, records, lock_path=_lock(pdf_path))
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
