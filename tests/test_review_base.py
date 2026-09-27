"""Capturing a deck version from PDF + sidecar, and the stored base."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from slidesonnet.exceptions import ReviewError
from slidesonnet.review import base as base_mod
from slidesonnet.review.versions import capture
from tests.conftest import simple_narration, write_pdf


def _deck(tmp_path: Path, ids: list[str], narration: str = "", **kw: bool) -> Path:
    pdf = write_pdf(tmp_path / "deck.pdf", ids, **kw)
    if narration:
        (tmp_path / "deck.narration").write_text(simple_narration(narration), encoding="utf-8")
    return pdf


def _retext(pdf: Path, index: int, body: str) -> None:
    """Draw extra visible text on one page (an 'edit' to that slide)."""
    doc = fitz.open(pdf)
    doc[index].insert_text((20, 150), body, fontsize=14)
    doc.saveIncr()
    doc.close()


def test_capture_reads_ids_images_text_and_narration(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"], "@a\nHello there.\n")
    version = capture(pdf)
    assert version.order == ("a", "b")
    assert "Hello there." in version.slides["a"].narration
    assert version.slides["b"].narration == ""
    assert "page body" in version.slides["a"].text
    assert "SSID" not in version.slides["a"].text  # markers stay out of the text
    # identical-looking pages hash identically; the id marker is invisible
    assert version.slides["a"].image_hash == version.slides["b"].image_hash


def test_capture_skips_unmarked_and_auto_ids(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "", "auto-p3-s1"])
    assert capture(pdf).order == ("a",)


def test_visible_edit_changes_only_that_hash(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"])
    before = capture(pdf)
    _retext(pdf, 1, "An edit")
    after = capture(pdf)
    assert after.slides["a"].image_hash == before.slides["a"].image_hash
    assert after.slides["b"].image_hash != before.slides["b"].image_hash
    assert "An edit" in after.slides["b"].text


def test_snapshot_round_trips_and_stores_images(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"], "@a\nHi.\n")
    assert base_mod.load_base(pdf) is None
    taken = base_mod.snapshot(pdf)
    assert base_mod.load_base(pdf) == taken
    image = base_mod.base_image(pdf, "a")
    assert image is not None and image.exists() and image.suffix == ".png"
    assert base_mod.base_image(pdf, "missing") is None


def test_snapshot_refuses_a_final_build(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a"], final=True)
    with pytest.raises(ReviewError, match="final build"):
        base_mod.snapshot(pdf)


def test_advance_updates_only_named_slides(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b", "c"])
    base_mod.snapshot(pdf)
    _retext(pdf, 0, "edit a")
    _retext(pdf, 1, "edit b")
    base_mod.advance(pdf, {"a"}, adopt_order=True)
    stored = base_mod.load_base(pdf)
    current = capture(pdf)
    assert stored is not None
    assert stored.slides["a"] == current.slides["a"]  # advanced
    assert stored.slides["b"] != current.slides["b"]  # still the old version


def test_advance_drops_deleted_and_adds_new(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"])
    base_mod.snapshot(pdf)
    write_pdf(pdf, ["a", "n"])  # b deleted, n inserted
    base_mod.advance(pdf, {"b", "n"}, adopt_order=True)
    stored = base_mod.load_base(pdf)
    assert stored is not None
    assert set(stored.slides) == {"a", "n"}
    assert stored.order == ("a", "n")


def test_advance_keeps_order_when_told(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"])
    base_mod.snapshot(pdf)
    write_pdf(pdf, ["b", "a"])
    base_mod.advance(pdf, {"a"}, adopt_order=False)
    stored = base_mod.load_base(pdf)
    assert stored is not None and stored.order == ("a", "b")


def test_unreferenced_images_are_pruned(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a"])
    base_mod.snapshot(pdf)
    old = base_mod.base_image(pdf, "a")
    _retext(pdf, 0, "changed")
    base_mod.snapshot(pdf)
    new = base_mod.base_image(pdf, "a")
    assert old is not None and new is not None and old != new
    assert not old.exists()
