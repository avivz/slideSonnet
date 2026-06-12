"""Tests for PDF slide-id extraction and rasterization."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from slidesonnet.exceptions import ParserError
from slidesonnet.pdf.reader import page_aspect, page_count, rasterize, read_page_ids

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def test_read_page_ids() -> None:
    ids = read_page_ids(MARKED)
    assert ids[:4] == ["intro-title", "euler-setup", "euler-trick", "euler-result"]


def test_unnamed_steps_get_auto_defaults() -> None:
    ids = read_page_ids(MARKED)
    # last frame is deliberately unnamed -> auto ids, unique per page
    assert all(i.startswith("auto-p") for i in ids[4:])
    assert len(set(ids)) == len(ids)  # all unique


def test_page_count() -> None:
    assert page_count(MARKED) == len(read_page_ids(MARKED))


def test_read_missing_pdf_raises() -> None:
    with pytest.raises(ParserError):
        read_page_ids(FIXTURES / "does-not-exist.pdf")


def test_page_count_missing_pdf_raises() -> None:
    with pytest.raises(ParserError):
        page_count(FIXTURES / "does-not-exist.pdf")


def test_page_aspect_missing_pdf_raises() -> None:
    with pytest.raises(ParserError):
        page_aspect(FIXTURES / "does-not-exist.pdf")


def test_page_aspect_is_wider_than_tall() -> None:
    assert page_aspect(MARKED) > 1.0  # beamer slides are landscape


def test_rasterize_missing_pdf_raises(tmp_path: Path) -> None:
    with pytest.raises(ParserError, match="PDF not found"):
        rasterize(FIXTURES / "does-not-exist.pdf", tmp_path)


def test_rasterize_without_pdftoppm_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_run(cmd: list[str], **kwargs: object) -> object:
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr("slidesonnet.proc.subprocess.run", missing_run)
    with pytest.raises(ParserError, match="poppler-utils"):
        rasterize(MARKED, tmp_path)


def test_rasterize_pdftoppm_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_run(cmd: list[str], **kwargs: object) -> object:
        raise subprocess.CalledProcessError(1, cmd, stderr="corrupt page tree")

    monkeypatch.setattr("slidesonnet.proc.subprocess.run", failing_run)
    with pytest.raises(ParserError, match="corrupt page tree"):
        rasterize(MARKED, tmp_path)


def test_rasterize_no_output_raises_and_clears_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = tmp_path / "page-3.png"
    stale.write_bytes(b"old render")
    monkeypatch.setattr(
        "slidesonnet.proc.subprocess.run",
        lambda cmd, **kw: SimpleNamespace(returncode=0, stderr=""),
    )
    with pytest.raises(ParserError, match="produced no images"):
        rasterize(MARKED, tmp_path)
    assert not stale.exists()  # stale page images are cleared before rendering


@pytest.mark.integration
def test_rasterize(tmp_path: Path) -> None:
    pages = rasterize(MARKED, tmp_path, dpi=72)
    assert len(pages) == page_count(MARKED)
    assert all(p.suffix == ".png" and p.stat().st_size > 0 for p in pages)
    # page order preserved numerically (not lexically)
    assert pages == sorted(pages, key=lambda p: int(p.stem.split("-")[-1]))
