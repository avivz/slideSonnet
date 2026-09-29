"""Review operations over the base + log (what the CLI and the editor call)."""

from __future__ import annotations

import fcntl
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest

from slidesonnet.exceptions import ReviewError
from slidesonnet.review import ops
from slidesonnet.review.base import load_base
from slidesonnet.review.log import DECK
from tests.conftest import simple_narration, write_pdf


@pytest.fixture
def deck(tmp_path: Path) -> Path:
    pdf = write_pdf(tmp_path / "deck.pdf", ["a", "b", "c"])
    (tmp_path / "deck.narration").write_text(simple_narration("@a\nHello.\n"), encoding="utf-8")
    return pdf


def _edit_page(pdf: Path, index: int, body: str = "edited") -> None:
    doc = pymupdf.open(pdf)
    doc[index].insert_text((20, 150), body, fontsize=14)
    doc.saveIncr()
    doc.close()


def _edit_narration(pdf: Path, text: str) -> None:
    pdf.with_suffix(".narration").write_text(simple_narration(text), encoding="utf-8")


def test_status_takes_the_base_on_first_use(deck: Path) -> None:
    assert load_base(deck) is None
    status = ops.status(deck)
    assert load_base(deck) is not None
    assert status.changes == [] and status.unfiled == []
    assert list(status.state.conversations) == [DECK]


def test_comment_reply_accept_reopen_flow(deck: Path) -> None:
    ops.status(deck)
    cid = ops.comment(deck, ["b"], "Shorten this.")
    assert cid == "c1"
    assert ops.load(deck).conversations[cid].turn == "agent"
    ops.reply(deck, cid, "Done.", add_slides=["c"])
    conv = ops.load(deck).conversations[cid]
    assert conv.slides == ["b", "c"] and conv.turn == "author"
    ops.accept(deck, cid)
    assert ops.load(deck).conversations[cid].status == "closed"
    ops.reopen(deck, cid)
    assert ops.load(deck).conversations[cid].status == "open"


def test_reply_validation(deck: Path) -> None:
    ops.status(deck)
    with pytest.raises(ReviewError, match="no conversation"):
        ops.reply(deck, "c9", "hi")
    cid = ops.comment(deck, ["a"], "x")
    with pytest.raises(ReviewError, match="deck conversation"):
        ops.reply(deck, DECK, "hi", add_slides=["a"])
    ops.accept(deck, cid)
    with pytest.raises(ReviewError, match="closed"):
        ops.reply(deck, cid, "more")
    with pytest.raises(ReviewError, match="deck conversation"):
        ops.accept(deck, DECK)
    with pytest.raises(ReviewError, match="at least one slide"):
        ops.comment(deck, [], "no scope")


def test_deck_conversation_takes_messages_from_both_sides(deck: Path) -> None:
    ops.reply(deck, DECK, "These are ready — publish them.", author="author")
    assert ops.load(deck).conversations[DECK].turn == "agent"
    ops.reply(deck, DECK, "Done — exported deck.mp4.")
    assert ops.load(deck).conversations[DECK].turn == "author"


def test_changes_and_unfiled(deck: Path) -> None:
    ops.status(deck)
    _edit_page(deck, 1)
    _edit_narration(deck, "@a\nHello again.\n")
    status = ops.status(deck)
    assert {c.slide_id for c in status.changes} == {"a", "b"}
    assert sorted(status.unfiled) == ["a", "b"]
    ops.comment(deck, ["b"], "why?")
    assert ops.status(deck).unfiled == ["a"]


def test_file_unrequested_groups_unfiled_changes(deck: Path) -> None:
    ops.status(deck)
    _edit_page(deck, 0)
    _edit_page(deck, 2)
    cid = ops.file_unrequested(deck)
    assert cid is not None
    conv = ops.load(deck).conversations[cid]
    assert conv.origin == "unrequested" and conv.slides == ["a", "c"]
    assert conv.turn == "author"
    assert ops.file_unrequested(deck) is None  # nothing left unfiled


def test_author_edit_notes_open_conversation_without_passing_turn(deck: Path) -> None:
    ops.status(deck)
    cid = ops.comment(deck, ["a"], "reword")
    ops.note_author_edit(deck, "a")
    conv = ops.load(deck).conversations[cid]
    assert conv.messages[-1].author == "system" and "edited" in conv.messages[-1].text
    assert conv.turn == "agent"
    ops.note_author_edit(deck, "a")  # repeated saves don't pile up notes
    assert len(ops.load(deck).conversations[cid].messages) == 2


def test_author_edit_without_conversation_goes_to_closed_your_edits(deck: Path) -> None:
    ops.status(deck)
    ops.note_author_edit(deck, "b")
    ops.note_author_edit(deck, "c")
    convs = [c for c in ops.load(deck).slide_conversations() if c.origin == "author-edits"]
    assert len(convs) == 1
    assert convs[0].status == "closed" and convs[0].slides == ["b", "c"]


def test_clear_advances_base_and_drops_closed_conversations(deck: Path) -> None:
    ops.status(deck)
    _edit_page(deck, 0)
    _edit_page(deck, 1)
    ca = ops.comment(deck, ["a"], "x")
    cb = ops.comment(deck, ["b"], "y")
    ops.accept(deck, ca)
    result = ops.clear(deck)
    assert result.cleared == [ca]
    state = ops.load(deck)
    assert ca not in state.conversations and cb in state.conversations
    changed = {c.slide_id for c in ops.status(deck).changes}
    assert changed == {"b"}  # a's new version is now the base


def test_clear_skips_slides_still_in_an_open_conversation(deck: Path) -> None:
    ops.status(deck)
    _edit_page(deck, 0)
    ca = ops.comment(deck, ["a"], "x")
    ops.comment(deck, ["a"], "also this")
    ops.accept(deck, ca)
    result = ops.clear(deck)
    assert result.skipped == ["a"]
    assert {c.slide_id for c in ops.status(deck).changes} == {"a"}


def test_clear_compares_pages_once(deck: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from slidesonnet.review import versions

    ops.status(deck)
    _edit_page(deck, 0)
    cid = ops.comment(deck, ["a"], "Accept")
    ops.accept(deck, cid)
    comparisons = 0
    real = versions.same_picture

    def compare(a: pymupdf.Pixmap, b: pymupdf.Pixmap) -> bool:
        nonlocal comparisons
        comparisons += 1
        return real(a, b)

    monkeypatch.setattr(versions, "same_picture", compare)
    ops.clear(deck)
    assert comparisons == 1  # advancing the base must reuse the comparison


def test_clear_keeps_deck_conversation_and_send_cursor(deck: Path) -> None:
    ops.reply(deck, DECK, "publish", author="author")
    ops.send(deck)
    ca = ops.comment(deck, ["a"], "x")
    ops.accept(deck, ca)
    ops.clear(deck)
    state = ops.load(deck)
    assert state.conversations[DECK].messages and state.sends == 1


def test_open_slide_conversations_ignores_deck_and_closed(deck: Path) -> None:
    ops.reply(deck, DECK, "publish", author="author")
    ca = ops.comment(deck, ["a"], "x")
    cb = ops.comment(deck, ["b"], "y")
    ops.accept(deck, cb)
    assert [c.id for c in ops.open_slide_conversations(deck)] == [ca]


def test_wait_returns_after_a_send(deck: Path) -> None:
    ops.comment(deck, ["a"], "x")
    since = ops.load(deck).sends

    def later() -> None:
        time.sleep(0.3)
        ops.send(deck)

    threading.Thread(target=later).start()
    result = ops.wait(deck, since=since, timeout=5, poll=0.05)
    assert result is not None
    assert result.cursor == since + 1
    assert [c.id for c in result.awaiting_agent] == ["c1"]


def test_wait_times_out(deck: Path) -> None:
    assert ops.wait(deck, since=0, timeout=0.2, poll=0.05) is None


def test_status_on_final_build_pauses_comparison(tmp_path: Path) -> None:
    pdf = write_pdf(tmp_path / "deck.pdf", ["a"])
    ops.status(pdf)
    write_pdf(pdf, ["a"], final=True)
    status = ops.status(pdf)
    assert status.final_build and status.changes == [] and status.unfiled == []


def test_claiming_a_slide_later_moves_it_out_of_unrequested(deck: Path) -> None:
    ops.status(deck)
    mine = ops.comment(deck, ["a"], "shorten", author="author")
    _edit_page(deck, 1)  # agent edits @b before declaring it...
    stray = ops.file_unrequested(deck)  # ...and the editor files it first
    assert stray is not None
    ops.reply(deck, mine, "Shortened; also touched @b.", add_slides=["b"])
    state = ops.load(deck)
    assert stray not in state.conversations  # nothing left in it: gone
    assert state.conversations[mine].slides == ["a", "b"]
    assert ops.status(deck).unfiled == []
    assert state.next_id() != stray  # its id is never reused


def test_claiming_keeps_the_rest_of_an_unrequested_conversation(deck: Path) -> None:
    ops.status(deck)
    _edit_page(deck, 1)
    _edit_page(deck, 2)
    stray = ops.file_unrequested(deck)
    assert stray is not None
    ops.comment(deck, ["b"], "Tightened @b.")
    assert ops.load(deck).conversations[stray].slides == ["c"]


def test_an_unrequested_conversation_you_answered_keeps_its_slides(deck: Path) -> None:
    ops.status(deck)
    _edit_page(deck, 1)
    stray = ops.file_unrequested(deck)
    assert stray is not None
    ops.reply(deck, stray, "Why did this change?", author="author")
    ops.comment(deck, ["b"], "It was me.")
    assert ops.load(deck).conversations[stray].slides == ["b"]


def test_clear_does_not_resurrect_a_retired_unrequested_conversation(deck: Path) -> None:
    ops.status(deck)
    mine = ops.comment(deck, ["a"], "shorten", author="author")
    _edit_page(deck, 1)
    stray = ops.file_unrequested(deck)
    ops.reply(deck, mine, "Done; touched @b too.", add_slides=["b"])
    ops.accept(deck, mine)
    ops.clear(deck)
    assert stray not in ops.load(deck).conversations


def test_clear_keeps_a_partly_claimed_unrequested_conversation_as_it_was(deck: Path) -> None:
    ops.status(deck)
    mine = ops.comment(deck, ["a"], "shorten", author="author")
    _edit_page(deck, 1)
    _edit_page(deck, 2)
    stray = ops.file_unrequested(deck)
    assert stray is not None
    ops.reply(deck, mine, "Done; touched @b too.", add_slides=["b"])
    ops.accept(deck, mine)
    ops.clear(deck)
    assert ops.load(deck).conversations[stray].slides == ["c"]


def test_a_slide_can_be_declared_before_it_is_compiled(deck: Path) -> None:
    """The agent declares first, then compiles: a new id isn't in the PDF yet."""
    ops.status(deck)
    cid = ops.comment(deck, ["a"], "shorten", author="author")
    ops.reply(deck, cid, "Splitting @a; the second half is @a-part2.", add_slides=["a-part2"])
    assert ops.status(deck).pending == {"a-part2": [cid]}  # declared, not compiled yet
    write_pdf(deck, ["a", "a-part2", "b", "c"])  # the compile lands
    st = ops.status(deck)
    assert st.pending == {}
    assert "a-part2" in {c.slide_id for c in st.changes if c.new}
    assert st.unfiled == []  # already filed: it was declared


def test_not_in_deck_names_ids_the_pdf_lacks(deck: Path) -> None:
    ops.status(deck)
    assert ops.not_in_deck(deck, ["a", "typo"]) == ["typo"]


def test_ids_are_never_reused_after_clear(deck: Path) -> None:
    first = ops.comment(deck, ["a"], "x")
    ops.accept(deck, first)
    ops.clear(deck)
    assert ops.comment(deck, ["b"], "y") != first


def _lock_held(pdf: Path) -> bool:
    fd = os.open(ops._lock(pdf), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)  # closing also drops a lock this probe took
    return False


_WRITES: dict[str, Callable[[Path], object]] = {
    "comment": lambda d: ops.comment(d, ["a"], "x"),
    "reply": lambda d: ops.reply(d, DECK, "x"),
    "accept": lambda d: ops.accept(d, "c1"),
    "reopen": lambda d: (ops.accept(d, "c1"), ops.reopen(d, "c1")),
    "retitle": lambda d: ops.retitle(d, "c1", "T"),
    "unrequested": lambda d: ops.open_unrequested(d, ["b"]),
    "author edit": lambda d: ops.note_author_edit(d, "c"),
    "clear": lambda d: (ops.accept(d, "c1"), ops.clear(d)),
    "mark seen": lambda d: ops.mark_seen(d),
}


@pytest.mark.parametrize("action", _WRITES.values(), ids=_WRITES.keys())
def test_writes_decide_and_save_under_the_review_lock(
    deck: Path, monkeypatch: pytest.MonkeyPatch, action: Callable[[Path], object]
) -> None:
    """Load → decide → append/compact/save is one transaction, so concurrent
    writers can't share an id or drop each other's records."""
    from slidesonnet.review import base as base_mod

    ops.comment(deck, ["a"], "seed")
    unlocked: list[str] = []

    def guard(name: str, real: Callable[..., object]) -> Callable[..., object]:
        def wrapper(*args: object, **kwargs: object) -> object:
            if not _lock_held(deck):
                unlocked.append(name)
            return real(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(ops, "read_state", guard("read", ops.read_state))
    monkeypatch.setattr(base_mod, "_save", guard("save", base_mod._save))
    action(deck)
    assert unlocked == []
