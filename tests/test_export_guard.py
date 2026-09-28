"""export refuses a plain build or a deck with open review conversations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from slidesonnet import api
from slidesonnet.api import ExportResult
from slidesonnet.cli import main
from slidesonnet.exceptions import ExportRefused
from slidesonnet.review import ops
from tests.conftest import write_pdf


class _Reached(Exception):
    """Raised by a stubbed loader: export got past its guard."""


@pytest.fixture
def stub_load(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise _Reached

    monkeypatch.setattr(api, "_load", boom)


def test_plain_build_is_refused(tmp_path: Path, stub_load: None) -> None:
    pdf = write_pdf(tmp_path / "deck.pdf", ["a"], plain=True)
    with pytest.raises(ExportRefused, match="ssfinal"):
        api.export(pdf, tmp_path / "deck.mp4")


def test_open_conversation_is_refused(tmp_path: Path, stub_load: None) -> None:
    pdf = write_pdf(tmp_path / "deck.pdf", ["a"], final=True)
    ops.comment(pdf, ["a"], "fix this", author="author")
    with pytest.raises(ExportRefused, match="c1"):
        api.export(pdf, tmp_path / "deck.mp4")


def test_deck_conversation_and_closed_ones_dont_block(tmp_path: Path, stub_load: None) -> None:
    pdf = write_pdf(tmp_path / "deck.pdf", ["a"], final=True)
    ops.reply(pdf, "deck", "publish", author="author")
    cid = ops.comment(pdf, ["a"], "x", author="author")
    ops.accept(pdf, cid)
    with pytest.raises(_Reached):
        api.export(pdf, tmp_path / "deck.mp4")


def test_legacy_pdf_without_markers_still_exports(tmp_path: Path, stub_load: None) -> None:
    with pytest.raises(_Reached):
        api.export(write_pdf(tmp_path / "deck.pdf", ["a"]), tmp_path / "deck.mp4")


def test_draft_bypasses_the_guard(tmp_path: Path, stub_load: None) -> None:
    pdf = write_pdf(tmp_path / "deck.pdf", ["a"], plain=True)
    with pytest.raises(_Reached):
        api.export(pdf, tmp_path / "deck.mp4", draft=True)


def test_draft_output_name() -> None:
    assert api.draft_output(Path("out/deck.mp4")) == Path("out/deck.draft.mp4")
    assert api.draft_output(Path("deck.draft.mp4")) == Path("deck.draft.mp4")


def test_export_blockers_lists_every_reason(tmp_path: Path) -> None:
    pdf = write_pdf(tmp_path / "deck.pdf", ["a"], plain=True)
    ops.comment(pdf, ["a"], "x", author="author")
    reasons = api.export_blockers(pdf)
    assert len(reasons) == 2


def test_cli_draft_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_export(pdf: Path, output: Path, **kwargs: Any) -> ExportResult:
        seen.update(kwargs)
        return ExportResult(
            video=api.draft_output(output), subtitles=[], duration=1.0, silent=False
        )

    monkeypatch.setattr("slidesonnet.api.export", fake_export)
    pdf = write_pdf(tmp_path / "deck.pdf", ["a"])
    result = CliRunner().invoke(
        main, ["--no-log-file", "export", str(pdf), "-o", str(tmp_path / "deck.mp4"), "--draft"]
    )
    assert result.exit_code == 0, result.output
    assert seen["draft"] is True
    assert "deck.draft.mp4" in result.output
