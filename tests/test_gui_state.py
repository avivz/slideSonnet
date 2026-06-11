"""Unit tests for EditorState helpers that back the editor's filmstrip."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.gui.state import EditorState

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def _state(tmp_path: Path, sidecar: str = "") -> EditorState:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    if sidecar:
        (tmp_path / "marked.narration").write_text(sidecar, encoding="utf-8")
    return EditorState(pdf)


def test_has_narration(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    assert state.has_narration("intro-title")
    assert not state.has_narration("euler-setup")


def test_status_ready_for_narrated_slide(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    assert state.status_for("intro-title") == "ready"


def test_status_empty_for_unnarrated_slide(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    # missing-narration alone reads as "empty", not as a warning
    assert state.status_for("euler-setup") == "empty"


def test_status_warning_for_auto_id(tmp_path: Path) -> None:
    state = _state(tmp_path)
    auto = [p for p in state.deck.pages if p.startswith("auto-")]
    assert auto, "fixture should contain auto-* pages"
    assert state.status_for(auto[0]) == "warning"


def test_status_error_for_orphan_block(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@no-such-page\nGhost.\n")
    assert state.status_for("no-such-page") == "error"


@pytest.mark.parametrize("sidecar", ["", "@intro-title\nHello.\n"])
def test_statuses_cover_all_pages(tmp_path: Path, sidecar: str) -> None:
    state = _state(tmp_path, sidecar=sidecar)
    for sid in state.deck.pages:
        assert state.status_for(sid) in {"error", "warning", "ready", "empty"}
