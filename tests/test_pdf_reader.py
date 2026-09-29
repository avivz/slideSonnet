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
    open_render,
    page_aspect,
    page_count,
    rasterize,
    read_page_ids,
    render_page_range,
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


def test_page_images_appear_whole_never_half_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The editor sends page images while pdftoppm renders (a recompile): pdftoppm
    writes elsewhere and each finished image is moved into place in one step."""
    out = tmp_path / "pages"
    out.mkdir()
    old = out / "page-1.png"
    old.write_bytes(b"the previous render")
    written_in: list[Path] = []

    def fake_pdftoppm(cmd: list[str], **kw: object) -> object:
        prefix = Path(cmd[-1])
        written_in.append(prefix.parent)
        (prefix.parent / f"{prefix.name}-1.png").write_bytes(b"the new render")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("slidesonnet.proc.subprocess.run", fake_pdftoppm)
    pages = render_page_range(MARKED, out, 0, 0)
    assert written_in and all(d != out for d in written_in)  # never where images are served
    assert pages[0].read_bytes() == b"the new render" and pages[0].parent == out
    assert sorted(p.name for p in out.iterdir()) == ["page-1.png"]  # no scratch left behind
    rasterize(MARKED, out)
    assert all(d != out for d in written_in)


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


def test_a_recompile_during_rendering_is_not_stamped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stamp certifies the PDF as it was when rendering *began*: if it changes
    while pdftoppm runs, the images may be of the old build, so nothing is stamped
    and the next open renders again."""
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(MARKED.read_bytes())

    def recompile_midway(cmd: list[str], **kw: object) -> object:
        prefix = Path(cmd[-1])
        (prefix.parent / f"{prefix.name}-1.png").write_bytes(b"old build")
        pdf.write_bytes(MARKED.read_bytes() + b"\n% recompiled\n")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("slidesonnet.proc.subprocess.run", recompile_midway)
    rasterize(pdf, tmp_path / "pages")
    assert cached_pages(pdf, tmp_path / "pages") is None


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


def test_plain_build_is_not_final(tmp_path: Path) -> None:
    from slidesonnet.pdf.reader import is_final_build
    from tests.conftest import write_pdf

    assert is_final_build(write_pdf(tmp_path / "d.pdf", ["a", "b"])) is False


def test_final_build_detected_and_ids_unaffected(tmp_path: Path) -> None:
    from slidesonnet.pdf.reader import is_final_build
    from tests.conftest import write_pdf

    pdf = write_pdf(tmp_path / "d.pdf", ["a", "b"], final=True)
    assert is_final_build(pdf) is True
    assert read_page_ids(pdf) == ["a", "b"]  # the marker never leaks into the id


def test_plain_marker_detected(tmp_path: Path) -> None:
    from slidesonnet.pdf.reader import is_final_build, is_plain_build
    from tests.conftest import write_pdf

    plain = write_pdf(tmp_path / "p.pdf", ["a"], plain=True)
    legacy = write_pdf(tmp_path / "l.pdf", ["a"])  # an older .sty: no build marker
    assert is_plain_build(plain) and not is_final_build(plain)
    assert not is_plain_build(legacy) and not is_final_build(legacy)
    assert read_page_ids(plain) == ["a"]


# ---- rendering page by page (the editor opens before the strip is ready) ----


def _fake_pdftoppm(monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]) -> None:
    """Stand in for pdftoppm: write the -f..-l pages it was asked for."""

    def run(cmd: list[str], **_kw: object) -> None:
        calls.append(cmd)
        first, last = int(cmd[cmd.index("-f") + 1]), int(cmd[cmd.index("-l") + 1])
        for n in range(first, last + 1):
            Path(f"{cmd[-1]}-{n:02d}.png").write_bytes(b"\x89PNG")

    monkeypatch.setattr("slidesonnet.pdf.reader.run_tool", run)


def test_open_render_starts_empty_and_keeps_what_was_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    _fake_pdftoppm(monkeypatch, calls)
    pdf, pages = _pdf(tmp_path), tmp_path / "pages"
    assert open_render(pdf, pages, page_count=12) == {}
    got = render_page_range(pdf, pages, 3, 4)
    assert sorted(got) == [3, 4] and got[3].name == "page-04.png"
    assert [c[c.index("-f") + 1 : c.index("-l") + 2] for c in calls] == [["4", "-l", "5"]]
    assert sorted(open_render(pdf, pages, page_count=12)) == [3, 4]  # reopened: kept
    assert cached_pages(pdf, pages) is None  # partial: not a complete render


def test_open_render_drops_pages_of_an_older_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pdftoppm(monkeypatch, [])
    pdf, pages = _pdf(tmp_path), tmp_path / "pages"
    open_render(pdf, pages, page_count=3)
    render_page_range(pdf, pages, 0, 2)
    assert cached_pages(pdf, pages) is not None  # all pages: a complete render
    pdf.write_bytes(b"%PDF-1.4\nrecompiled, different size\n")
    assert open_render(pdf, pages, page_count=3) == {}
    assert not list(pages.glob("page-*.png"))
