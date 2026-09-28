"""ReviewModel — the editor's UI-free view of review state (no NiceGUI)."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from slidesonnet.deck import load_deck
from slidesonnet.review import ops
from slidesonnet.server.review_model import ReviewModel, word_diff
from tests.conftest import simple_narration, write_pdf


def _deck(tmp_path: Path, ids: list[str], narration: str = "") -> Path:
    pdf = write_pdf(tmp_path / "deck.pdf", ids)
    (tmp_path / "deck.narration").write_text(simple_narration(narration), encoding="utf-8")
    return pdf


def _narr(pdf: Path) -> dict:  # type: ignore[type-arg]
    return load_deck(pdf)[0].narration


def _edit_page(pdf: Path, index: int) -> None:
    doc = pymupdf.open(pdf)
    doc[index].insert_text((20, 150), "edited", fontsize=14)
    doc.saveIncr()
    doc.close()


def test_on_once_the_deck_has_a_base(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"], "@a\nHi.\n")
    model = ReviewModel(pdf)
    assert not model.active
    model.ensure_base()
    assert model.active and not ops.review_path(pdf).exists()  # no file until something's said
    assert model.status(_narr(pdf)).changes == []
    _edit_page(pdf, 1)
    assert model.status(_narr(pdf)).changes
    model.mark_seen()
    assert model.status(_narr(pdf)).changes == []


def test_changes_badges_and_conversations(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b", "c"], "@a\nHi.\n")
    model = ReviewModel(pdf)
    model.ensure_base()
    _edit_page(pdf, 1)
    cid = model.comment(["b"], "why?")
    st = model.status(_narr(pdf))
    assert model.change_for(st, "b") is not None and model.change_for(st, "a") is None
    assert [c.id for c in model.conversations_for(st, "b")] == [cid]
    assert model.badge(st, "b") == "agent-turn"
    ops.reply(pdf, cid, "fixed")
    assert model.badge(model.status(_narr(pdf)), "b") == "your-turn"
    model.accept(cid)
    assert model.badge(model.status(_narr(pdf)), "b") == "closed"


def test_page_capture_is_cached_until_the_pdf_changes(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from slidesonnet.server import review_model as review_mod

    pdf = _deck(tmp_path, ["a"])
    model = ReviewModel(pdf)
    model.ensure_base()
    calls = {"n": 0}
    real = review_mod.capture_pages

    def counting(path: Path, **kw: object):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return real(path, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(review_mod, "capture_pages", counting)
    model.status(_narr(pdf))
    model.status(_narr(pdf))
    assert calls["n"] == 1
    _edit_page(pdf, 0)
    model.status(_narr(pdf))
    assert calls["n"] == 2


def test_file_unrequested_only_when_active(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"])
    model = ReviewModel(pdf)
    assert model.file_unrequested(_narr(pdf)) is None  # no base yet: nothing to compare
    model.ensure_base()
    _edit_page(pdf, 1)
    filed = model.file_unrequested(_narr(pdf))
    assert filed is not None
    cid, count = filed
    assert count == 1 and ops.load(pdf).conversations[cid].origin == "unrequested"


def test_author_edits_noted_only_when_active(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a"])
    model = ReviewModel(pdf)
    model.note_edits({"a"})
    assert not ops.review_path(pdf).exists()  # no base yet: nothing to note against
    model.ensure_base()
    model.note_edits({"a"})
    assert any(c.origin == "author-edits" for c in ops.load(pdf).slide_conversations())


def test_narration_diff_and_base_image(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a"], "@a\nThe old words here.\n")
    model = ReviewModel(pdf)
    model.ensure_base()
    (tmp_path / "deck.narration").write_text(
        simple_narration("@a\nThe new words here.\n"), encoding="utf-8"
    )
    diff = model.narration_diff("a", _narr(pdf))
    assert ("-", "old") in diff and ("+", "new") in diff
    image = model.base_image("a")
    assert image is not None and image.exists()


def test_word_diff() -> None:
    assert word_diff("a b c", "a x c") == [("=", "a"), ("-", "b"), ("+", "x"), ("=", "c")]
    assert word_diff("", "new") == [("+", "new")]
