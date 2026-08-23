"""Tests for PDF slide-id extraction and rasterization."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from slidesonnet.exceptions import ParserError
from slidesonnet.pdf.reader import (
    cached_pages,
    page_aspect,
    page_count,
    rasterize,
    read_page_ids,
    write_render_stamp,
)

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


# ---- reusing an existing render ----------------------------------------
#
# Rasterizing is ~3.5 s for a 49-page deck, and it used to run on every editor
# page build — invisible when that happened once per launch, but the deck
# library opens a deck per switch. These cover the reuse decision without
# needing pdftoppm, so they run in the fast tier.


def _fake_render(out_dir: Path, pdf: Path, count: int, *, dpi: int = 150) -> None:
    """Lay down *count* page PNGs plus a stamp, as a real rasterize would."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (out_dir / f"page-{i:02d}.png").write_bytes(b"\x89PNG")
    write_render_stamp(pdf, out_dir, dpi=dpi, prefix="page", count=count)


def _pdf(tmp_path: Path, body: bytes = b"%PDF-1.4\n") -> Path:
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(body)
    return pdf


def test_cached_pages_returns_the_existing_render(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path)
    pages = tmp_path / "pages"
    _fake_render(pages, pdf, 3)
    found = cached_pages(pdf, pages)
    assert found is not None
    assert [p.name for p in found] == ["page-01.png", "page-02.png", "page-03.png"]


def test_cached_pages_is_none_without_a_previous_render(tmp_path: Path) -> None:
    assert cached_pages(_pdf(tmp_path), tmp_path / "pages") is None


def test_a_recompiled_pdf_invalidates_the_render(tmp_path: Path) -> None:
    """A recompile must re-rasterize, or the editor shows the old slides."""
    pdf = _pdf(tmp_path)
    pages = tmp_path / "pages"
    _fake_render(pages, pdf, 3)
    pdf.write_bytes(b"%PDF-1.4\nrecompiled, different size\n")
    assert cached_pages(pdf, pages) is None


def test_a_same_size_recompile_still_invalidates(tmp_path: Path) -> None:
    """Size alone can't be trusted — WSL/network mounts report coarse mtimes,
    so the stamp carries nanosecond mtime *and* size (as _stat_stamp does)."""
    pdf = _pdf(tmp_path, b"%PDF-1.4\naaaa\n")
    pages = tmp_path / "pages"
    _fake_render(pages, pdf, 3)
    os.utime(pdf, ns=(1_000_000_000, 1_234_000_000_000))
    assert cached_pages(pdf, pages) is None


def test_a_different_dpi_invalidates_the_render(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path)
    pages = tmp_path / "pages"
    _fake_render(pages, pdf, 3, dpi=150)
    assert cached_pages(pdf, pages, dpi=300) is None


def test_missing_page_images_invalidate_the_render(tmp_path: Path) -> None:
    """Someone cleaned the cache but left the stamp: render again, don't 404."""
    pdf = _pdf(tmp_path)
    pages = tmp_path / "pages"
    _fake_render(pages, pdf, 3)
    (pages / "page-02.png").unlink()
    assert cached_pages(pdf, pages) is None


def test_a_corrupt_stamp_invalidates_the_render(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path)
    pages = tmp_path / "pages"
    _fake_render(pages, pdf, 3)
    (pages / ".render-stamp.json").write_text("{not json", encoding="utf-8")
    assert cached_pages(pdf, pages) is None


def test_a_vanished_pdf_invalidates_the_render(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path)
    pages = tmp_path / "pages"
    _fake_render(pages, pdf, 3)
    pdf.unlink()
    assert cached_pages(pdf, pages) is None


@pytest.mark.integration
def test_rasterize_reuse_skips_a_second_render(tmp_path: Path) -> None:
    """The real thing: a reused render leaves the PNGs untouched on disk."""
    first = rasterize(MARKED, tmp_path, dpi=72, reuse=True)
    stamps = [p.stat().st_mtime_ns for p in first]
    second = rasterize(MARKED, tmp_path, dpi=72, reuse=True)
    assert second == first
    assert [p.stat().st_mtime_ns for p in second] == stamps  # not re-rendered


@pytest.mark.integration
def test_rasterize_without_reuse_always_renders(tmp_path: Path) -> None:
    rasterize(MARKED, tmp_path, dpi=72)
    assert cached_pages(MARKED, tmp_path, dpi=72) is not None  # stamp still written
