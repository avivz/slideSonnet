"""Tests for id-only reconciliation diagnostics."""

from __future__ import annotations

from slidesonnet.diagnostics import (
    count_by_severity,
    diagnose,
    has_errors,
    transition_length_diagnostics,
)
from slidesonnet.narration.model import PageNarration, Segment, Transition


def test_transition_too_long_is_warned() -> None:
    a = PageNarration("a", [Segment.speech("hi")], transition_out=Transition("wipeleft", 2.0))
    b = PageNarration("b", [Segment.speech("hi")])
    blocks = {"a": a, "b": b}
    # slide b is only 0.3s, so a 2s wipe out of 'a' will be clamped -> warn.
    diags = transition_length_diagnostics(["a", "b"], blocks, [5.0, 0.3])
    assert [d.code for d in diags] == ["transition-too-long"]
    assert diags[0].slide_id == "a"
    # roomy slides -> no warning
    assert transition_length_diagnostics(["a", "b"], blocks, [5.0, 5.0]) == []


def _blocks(*ids: str) -> list[PageNarration]:
    return [PageNarration(slide_id=i, segments=[Segment.speech("hi")]) for i in ids]


def test_clean_deck_no_findings() -> None:
    diags = diagnose(["a", "b", "c"], _blocks("a", "b", "c"))
    assert diags == []
    assert not has_errors(diags)


def test_duplicate_page_ids_are_renamed_with_warnings() -> None:
    # duplicate \ssid is disambiguated upstream (deck.dedupe_page_ids), not an error
    from slidesonnet.deck import dedupe_page_ids

    pages, diags = dedupe_page_ids(["a", "a", "b"])
    assert pages == ["a", "a-2", "b"]
    assert not has_errors(diags)
    assert any(d.code == "duplicate-id" and d.severity == "warning" for d in diags)


def test_auto_id_is_warning() -> None:
    diags = diagnose(["auto-p1-s1", "b"], _blocks("auto-p1-s1", "b"))
    assert any(d.code == "auto-id" and d.severity == "warning" for d in diags)


def test_missing_narration_is_warning() -> None:
    diags = diagnose(["a", "b"], _blocks("a"))
    assert any(d.code == "missing-narration" and d.slide_id == "b" for d in diags)


def test_duplicate_sidecar_block_is_renamed_with_warnings() -> None:
    # a repeated @id is disambiguated upstream (deck.dedupe_block_ids), not an error,
    # so the second block's text is preserved instead of collapsing away
    from slidesonnet.deck import dedupe_block_ids

    blocks, diags = dedupe_block_ids(_blocks("a", "a", "b"))
    assert [b.slide_id for b in blocks] == ["a", "a-2", "b"]
    assert not has_errors(diags)
    assert any(d.code == "duplicate-block" and d.severity == "warning" for d in diags)


def test_orphan_narration_is_error() -> None:
    diags = diagnose(["a"], _blocks("a", "ghost"))
    assert has_errors(diags)
    assert any(d.code == "orphan-narration" and d.slide_id == "ghost" for d in diags)


def test_unmarked_page_is_warning() -> None:
    diags = diagnose(["a", "", "c"], _blocks("a", "c"))
    assert any(d.code == "unmarked-page" for d in diags)


def test_order_drift_is_info() -> None:
    diags = diagnose(["a", "b"], _blocks("b", "a"))
    assert any(d.code == "order-drift" and d.severity == "info" for d in diags)


def test_errors_sorted_first() -> None:
    # orphan block (error) must sort ahead of the auto-id warning
    diags = diagnose(["a", "auto-x"], _blocks("a", "auto-x", "ghost"))
    assert diags[0].severity == "error"


def test_count_by_severity() -> None:
    diags = diagnose(["a", "b"], _blocks("a", "b", "ghost"))
    counts = count_by_severity(diags)
    assert counts["error"] == 1  # orphan narration
