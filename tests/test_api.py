"""Tests for the headless api layer (sty/init/check)."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet import api

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def test_sty_text_has_macro() -> None:
    assert "\\ssid" in api.sty_text()


def test_packaged_sty_matches_repo_root() -> None:
    root = (Path(__file__).parent.parent / "slidesonnet.sty").read_text(encoding="utf-8")
    assert api.sty_text() == root  # guard against drift


def test_write_sty_to_dir(tmp_path: Path) -> None:
    written = api.write_sty(tmp_path)
    assert written == tmp_path / "slidesonnet.sty"
    assert written.exists()


def test_init_then_check(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    sidecar = api.init_sidecar(pdf)
    assert sidecar.exists()
    diags = api.check_deck(pdf)
    # blank scaffold -> no errors (all ids present), warnings for empty narration? No: blocks exist
    assert not any(d.severity == "error" for d in diags)


def test_init_force_overwrites(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    sidecar = api.init_sidecar(pdf)
    sidecar.write_text("@intro-title\nEdited.\n", encoding="utf-8")
    api.init_sidecar(pdf, force=True)
    assert "Edited." not in sidecar.read_text(encoding="utf-8")


def test_init_no_overwrite_raises(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    api.init_sidecar(pdf)
    with pytest.raises(FileExistsError):
        api.init_sidecar(pdf)
