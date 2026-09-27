"""The editor's review tools, via NiceGUI's in-process user simulation."""

from __future__ import annotations

import os
import time
from pathlib import Path

import fitz
import pytest
from nicegui import ui
from nicegui.testing import User

from slidesonnet.review import ops
from tests.conftest import simple_narration, write_pdf

pytestmark = pytest.mark.nicegui_main_file("tests/gui_main.py")


def _deck(tmp_path: Path, ids: list[str], narration: str = "") -> Path:
    pdf = write_pdf(tmp_path / "deck.pdf", ids, plain=True)
    (tmp_path / "deck.narration").write_text(simple_narration(narration), encoding="utf-8")
    return pdf


def _bump(path: Path) -> None:
    later = time.time() + 5
    os.utime(path, (later, later))


def _edit_page(pdf: Path, index: int) -> None:
    doc = fitz.open(pdf)
    doc[index].insert_text((20, 150), "edited", fontsize=14)
    doc.saveIncr()
    doc.close()
    _bump(pdf)


def _textarea(user: User, marker: str) -> ui.textarea:
    return next(iter(user.find(marker=marker).elements))  # type: ignore[return-value]


async def _open(user: User, pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")


async def test_start_review_from_the_editor(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b"], "@a\nHi.\n")
    await _open(user, pdf, monkeypatch)
    user.find(marker="review-start").click()
    await user.should_see(marker="deck-note")
    assert ops.is_active(pdf)


async def test_deck_note_goes_to_the_deck_conversation(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b"])
    ops.start(pdf)
    await _open(user, pdf, monkeypatch)
    user.find(marker="deck-note").type("These are ready — publish them.")
    user.find(marker="deck-note-add").click()
    await user.should_see("These are ready — publish them.")
    deck = ops.load(pdf).conversations["deck"]
    assert deck.messages[-1].text == "These are ready — publish them."
    assert deck.turn == "agent"


async def test_slide_note_opens_a_conversation_and_badges_the_thumb(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b"])
    ops.start(pdf)
    await _open(user, pdf, monkeypatch)
    user.find(marker="slide-note").type("Too wordy.")
    user.find(marker="slide-note-add").click()
    await user.should_see("Too wordy.")
    (conv,) = ops.load(pdf).slide_conversations()
    assert conv.slides == ["a"] and conv.turn == "agent"
    badge = next(iter(user.find(marker="thumb-review-0").elements))
    assert "ss-rv-agent-turn" in badge.classes


async def test_reply_and_accept(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b"])
    ops.start(pdf)
    cid = ops.comment(pdf, ["a"], "Shorten.", author="author")
    ops.reply(pdf, cid, "Done — cut the second sentence.")
    await _open(user, pdf, monkeypatch)
    await user.should_see("Done — cut the second sentence.")
    user.find(marker=f"reply-{cid}").type("Also the title.")
    user.find(marker=f"reply-{cid}-add").click()
    await user.should_see("Also the title.")
    assert ops.load(pdf).conversations[cid].turn == "agent"
    user.find(marker=f"accept-{cid}").click()
    await user.should_not_see(marker=f"reopen-{cid}")  # closed ones are hidden by default
    assert ops.load(pdf).conversations[cid].status == "closed"
    user.find(marker="review-show-closed").click()
    await user.should_see(marker=f"reopen-{cid}")
    await user.should_see(marker=f"conv-row-{cid}")


async def test_sending_a_note_also_releases_wait(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a"])
    ops.start(pdf)
    await _open(user, pdf, monkeypatch)
    user.find(marker="slide-note").type("Too wordy.")
    user.find(marker="slide-note-add").click()
    await user.should_see("Too wordy.")
    assert ops.load(pdf).sends == 1  # a waiting agent wakes up
    await user.should_not_see(marker="review-send")  # no separate Send step


async def test_enter_sends_the_note(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a"])
    ops.start(pdf)
    await _open(user, pdf, monkeypatch)
    user.find(marker="deck-note").type("Publish these.").trigger("keydown.enter")
    await user.should_see("Publish these.")
    assert ops.load(pdf).conversations["deck"].messages[-1].text == "Publish these."
    assert ops.load(pdf).sends == 1


async def test_clear_accepted(user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _deck(tmp_path, ["a"])
    ops.start(pdf)
    cid = ops.comment(pdf, ["a"], "x", author="author")
    ops.accept(pdf, cid)
    await _open(user, pdf, monkeypatch)
    user.find(marker="review-clear").click()
    await user.should_see("Cleared 1")
    assert ops.load(pdf).slide_conversations() == []


async def test_changed_slide_shows_before_and_narration_diff(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b"], "@a\nThe old words.\n")
    ops.start(pdf)
    _edit_page(pdf, 0)
    (tmp_path / "deck.narration").write_text(
        simple_narration("@a\nThe new words.\n"), encoding="utf-8"
    )
    await _open(user, pdf, monkeypatch)
    before = next(iter(user.find(marker="stage-before").elements))
    assert before.visible
    await user.should_see(marker="narration-diff")
    await user.should_see("old")


async def test_unchanged_slide_has_no_before(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a"])
    ops.start(pdf)
    await _open(user, pdf, monkeypatch)
    await user.should_not_see(marker="stage-before")  # hidden elements aren't findable


async def test_recompile_files_unrequested_changes(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b"])
    ops.start(pdf)
    await _open(user, pdf, monkeypatch)
    _edit_page(pdf, 1)
    await user.should_see("without being asked", retries=300)
    (conv,) = ops.load(pdf).slide_conversations()
    assert conv.origin == "unrequested" and conv.slides == ["b"]


async def test_before_strip_appears_when_order_changes(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b", "c"])
    ops.start(pdf)
    write_pdf(pdf, ["a", "c", "b"], plain=True)  # b moved after c
    await _open(user, pdf, monkeypatch)
    await user.should_see(marker="before-strip")
    await user.should_see(marker="before-thumb-b")
    moved = next(iter(user.find(marker="before-thumb-b").elements))
    assert "ss-moved" in moved.classes
    split = next(iter(user.find(marker="split-strip").elements))
    assert split.value == 300  # two strips side by side get twice the room


async def test_strip_narrows_again_when_order_is_restored(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b", "c"])
    ops.start(pdf)
    write_pdf(pdf, ["a", "c", "b"], plain=True)
    await _open(user, pdf, monkeypatch)
    await user.should_see(marker="before-strip")
    write_pdf(pdf, ["a", "b", "c"], plain=True)
    _bump(pdf)
    await user.should_not_see(marker="before-strip", retries=300)
    split = next(iter(user.find(marker="split-strip").elements))
    assert split.value == 150


async def test_conversation_filter_hides_other_slides(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b", "c"])
    ops.start(pdf)
    cid = ops.comment(pdf, ["b"], "x", author="author")
    await _open(user, pdf, monkeypatch)
    user.find(marker=f"conv-row-{cid}").click()
    await user.should_not_see(marker="thumb-0")
    await user.should_see(marker="thumb-1")
    await user.should_not_see(marker="thumb-2")
    user.find(marker="conv-filter-clear").click()
    await user.should_see(marker="thumb-0")
    await user.should_see(marker="thumb-2")


async def test_review_tab_badges_what_waits_for_you(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b"])
    ops.start(pdf)
    cid = ops.comment(pdf, ["a"], "Shorten.", author="author")
    ops.reply(pdf, cid, "Done.")
    await _open(user, pdf, monkeypatch)
    badge = next(iter(user.find(marker="console-tab-review-badge").elements))
    assert badge.visible and badge.text == "1"
    user.find(marker="console-tab-review").click()
    await user.should_see("Done.")


async def test_closed_conversations_are_hidden_until_asked_for(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path, ["a", "b"])
    ops.start(pdf)
    done = ops.comment(pdf, ["a"], "Old business.", author="author")
    ops.accept(pdf, done)
    live = ops.comment(pdf, ["a"], "Still open.", author="author")
    await _open(user, pdf, monkeypatch)
    await user.should_see("Still open.")
    await user.should_see(marker=f"conv-row-{live}")
    await user.should_not_see("Old business.")
    await user.should_not_see(marker=f"conv-row-{done}")
