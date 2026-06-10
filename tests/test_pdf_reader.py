"""Tests for PDF slide-id extraction and rasterization."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.exceptions import ParserError
from slidesonnet.pdf.reader import page_count, rasterize, read_page_ids

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


@pytest.mark.integration
def test_rasterize(tmp_path: Path) -> None:
    pages = rasterize(MARKED, tmp_path, dpi=72)
    assert len(pages) == page_count(MARKED)
    assert all(p.suffix == ".png" and p.stat().st_size > 0 for p in pages)
    # page order preserved numerically (not lexically)
    assert pages == sorted(pages, key=lambda p: int(p.stem.split("-")[-1]))
