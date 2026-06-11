"""Unit tests for EditorState helpers that back the editor's filmstrip."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from slidesonnet.gui.state import EditorState, cue_start

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


def test_uncached_count_counts_speech_segments(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello. [pause 1] World.\n")
    assert state.uncached_count("intro-title") == 2  # nothing synthesized yet
    assert state.uncached_count("euler-setup") == 0  # no narration at all
    assert state.uncached_total() == 2


def test_tts_is_paid_default_kokoro(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.tts_is_paid is False


def _bump_mtime(path: Path) -> None:
    """Force a visibly newer mtime regardless of filesystem timestamp granularity."""
    later = time.time() + 5
    os.utime(path, (later, later))


def test_poll_sources_false_when_unchanged(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    assert state.poll_sources() is False


def test_poll_sources_picks_up_external_sidecar_edit(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    sidecar = tmp_path / "marked.narration"
    sidecar.write_text("@intro-title\nChanged externally.\n", encoding="utf-8")
    _bump_mtime(sidecar)
    assert state.poll_sources() is True
    assert "Changed externally." in state.body_text
    assert state.poll_sources() is False  # baseline refreshed


def test_own_save_does_not_trigger_reload(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    state.save("Edited in the GUI.")
    assert state.poll_sources() is False


def test_pdf_change_invalidates_image_cache(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state._images = [tmp_path / "fake.png"]  # primed cache
    _bump_mtime(tmp_path / "marked.pdf")
    assert state.poll_sources() is True
    assert state._images is None


def test_config_change_reloads_config(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.config.tts.backend == "kokoro"
    (tmp_path / "slidesonnet.toml").write_text('[tts]\nbackend = "elevenlabs"\n', encoding="utf-8")
    assert state.poll_sources() is True
    assert state.config.tts.backend == "elevenlabs"


# ---- recompiling the deck while the editor is open ------------------------


def _factory_state(tmp_path: Path, ids: list[str], sidecar: str = "") -> EditorState:
    from tests.conftest import write_pdf

    pdf = write_pdf(tmp_path / "deck.pdf", ids)
    if sidecar:
        (tmp_path / "deck.narration").write_text(sidecar, encoding="utf-8")
    return EditorState(pdf)


def _recompile(state: EditorState, ids: list[str]) -> None:
    from tests.conftest import write_pdf

    write_pdf(state.pdf_path, ids)
    _bump_mtime(state.pdf_path)


def test_recompile_added_slide_flags_missing_narration(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n\n@b\nBye.\n")
    assert state.error_count == 0
    _recompile(state, ["a", "b", "c"])
    assert state.poll_sources() is True
    assert state.page_count == 3
    assert any(d.code == "missing-narration" and d.slide_id == "c" for d in state.diagnostics)


def test_recompile_renamed_slide_yields_orphan_error(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n\n@b\nBye.\n")
    _recompile(state, ["a", "b-renamed"])
    assert state.poll_sources() is True
    assert any(d.code == "orphan-narration" and d.slide_id == "b" for d in state.diagnostics)
    assert state.status_for("b") == "error"


def test_recompile_shrunk_deck_clamps_index(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b", "c"])
    state.go(2)
    _recompile(state, ["a"])
    assert state.poll_sources() is True
    assert state.index == 0
    assert state.current_id == "a"


def test_poll_survives_pdf_missing_mid_recompile(tmp_path: Path) -> None:
    # latexmk deletes/rewrites the PDF; a poll tick in that window must not crash
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n")
    state.pdf_path.unlink()
    assert state.poll_sources() is False  # keeps showing the last good deck
    assert state.page_count == 2
    _recompile(state, ["a", "b", "c"])  # compile finished
    assert state.poll_sources() is True
    assert state.page_count == 3


def test_poll_survives_partially_written_pdf(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n")
    state.pdf_path.write_bytes(b"%PDF-1.5 garbage truncated")
    _bump_mtime(state.pdf_path)
    assert state.poll_sources() is False  # unreadable: keep last good deck, retry next tick
    assert state.page_count == 2
    _recompile(state, ["a", "b"])
    assert state.poll_sources() is True


def test_poll_survives_malformed_config_edit(tmp_path: Path) -> None:
    # a half-saved slidesonnet.toml must not crash the poll loop
    state = _factory_state(tmp_path, ["a"], sidecar="@a\nHi.\n")
    cfg = tmp_path / "slidesonnet.toml"
    cfg.write_text("[tts\nbackend = ", encoding="utf-8")
    _bump_mtime(cfg)
    assert state.poll_sources() is False
    cfg.write_text('[tts]\nbackend = "kokoro"\n', encoding="utf-8")
    _bump_mtime(cfg)
    assert state.poll_sources() is True


def test_cue_start_finds_slide() -> None:
    cues = [(0.0, "a"), (3.5, "b"), (9.0, "c")]
    assert cue_start(cues, "b") == 3.5
    assert cue_start(cues, "a") == 0.0
    assert cue_start(cues, "zzz") is None
