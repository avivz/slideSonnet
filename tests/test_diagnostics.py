"""Tests for id-only reconciliation diagnostics."""

from __future__ import annotations

from slidesonnet.diagnostics import count_by_severity, diagnose, has_errors
from slidesonnet.narration.model import PageNarration, Segment


def _blocks(*ids: str) -> list[PageNarration]:
    return [PageNarration(slide_id=i, segments=[Segment.speech("hi")]) for i in ids]


def test_clean_deck_no_findings() -> None:
    diags = diagnose(["a", "b", "c"], _blocks("a", "b", "c"))
    assert diags == []
    assert not has_errors(diags)


def test_duplicate_page_id_is_error() -> None:
    diags = diagnose(["a", "a", "b"], _blocks("a", "b"))
    assert has_errors(diags)
    assert any(d.code == "duplicate-id" for d in diags)


def test_auto_id_is_warning() -> None:
    diags = diagnose(["auto-p1-s1", "b"], _blocks("auto-p1-s1", "b"))
    assert any(d.code == "auto-id" and d.severity == "warning" for d in diags)


def test_missing_narration_is_warning() -> None:
    diags = diagnose(["a", "b"], _blocks("a"))
    assert any(d.code == "missing-narration" and d.slide_id == "b" for d in diags)


def test_duplicate_sidecar_block_is_error() -> None:
    diags = diagnose(["a"], _blocks("a", "a"))
    assert has_errors(diags)
    assert any(d.code == "duplicate-block" and d.slide_id == "a" for d in diags)


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
    diags = diagnose(["a", "a", "auto-x"], _blocks("a", "auto-x"))
    assert diags[0].severity == "error"


def test_count_by_severity() -> None:
    diags = diagnose(["a", "a"], _blocks("a", "ghost"))
    counts = count_by_severity(diags)
    assert counts["error"] == 2  # duplicate-id + orphan
