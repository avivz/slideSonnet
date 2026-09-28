"""Diffing two deck versions by slide id (pure — no PDFs)."""

from __future__ import annotations

from slidesonnet.review.diff import SlideChange, diff_versions, moved_ids
from slidesonnet.review.versions import DeckVersion, SlideVersion


def _v(order: list[str], **overrides: SlideVersion) -> DeckVersion:
    slides = {sid: SlideVersion(image_hash=f"img-{sid}", text=sid, narration="") for sid in order}
    slides.update(overrides)
    return DeckVersion(order=tuple(order), slides=slides)


def _by_id(changes: list[SlideChange]) -> dict[str, SlideChange]:
    return {c.slide_id: c for c in changes}


def test_identical_versions_have_no_changes() -> None:
    assert diff_versions(_v(["a", "b"]), _v(["a", "b"])) == []


def test_new_and_deleted_slides() -> None:
    changes = _by_id(diff_versions(_v(["a", "b"]), _v(["a", "c"])))
    assert set(changes) == {"b", "c"}
    assert changes["c"].new and changes["c"].current_index == 1
    assert changes["b"].deleted and changes["b"].base_index == 1


def test_edited_image_and_narration_are_separate_flags() -> None:
    base = _v(["a", "b"])
    cur = _v(
        ["a", "b"],
        a=SlideVersion(image_hash="img-a2", text="a", narration=""),
        b=SlideVersion(image_hash="img-b", text="b", narration="@b\n  utterance: …"),
    )
    changes = _by_id(diff_versions(base, cur))
    assert changes["a"].image and not changes["a"].narration
    assert changes["b"].narration and not changes["b"].image
    assert changes["a"].kinds == ("edited",)


def test_insert_does_not_mark_the_rest_as_moved() -> None:
    changes = diff_versions(_v(["a", "b", "c"]), _v(["a", "x", "b", "c"]))
    assert [c.slide_id for c in changes] == ["x"]  # only the insert


def test_reorder_marks_only_the_moved_slide() -> None:
    changes = _by_id(diff_versions(_v(["a", "b", "c", "d"]), _v(["a", "c", "d", "b"])))
    assert set(changes) == {"b"}  # c, d keep their relative order (the LCS)
    assert changes["b"].moved and changes["b"].kinds == ("moved",)
    assert (changes["b"].base_index, changes["b"].current_index) == (1, 3)


def test_moved_and_edited_both_reported() -> None:
    cur = _v(["b", "a"], a=SlideVersion(image_hash="new", text="a", narration=""))
    change = _by_id(diff_versions(_v(["a", "b"]), cur))
    # one of a/b is "moved" (LCS keeps the other); a is also edited
    assert "edited" in change["a"].kinds


def test_changes_are_in_current_order_then_deleted_in_base_order() -> None:
    changes = diff_versions(_v(["a", "gone1", "b", "gone2"]), _v(["n1", "a", "b", "n2"]))
    assert [c.slide_id for c in changes] == ["n1", "n2", "gone1", "gone2"]


def test_moved_ids_uses_longest_common_subsequence() -> None:
    assert moved_ids(("a", "b", "c", "d"), ("b", "c", "d", "a")) == {"a"}
    assert moved_ids(("a", "b"), ("a", "b")) == set()
    assert moved_ids(("a", "b", "c"), ("a", "c")) == set()  # deletion isn't a move
