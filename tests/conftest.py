"""Shared test fixtures."""

from collections.abc import Callable
from pathlib import Path

import fitz  # type: ignore[import-untyped]
import pytest

# NiceGUI's in-process `user` fixture (no selenium). The combined plugin pulls
# in selenium for the `screen` fixture, so load only the user plugin.
pytest_plugins = ["nicegui.testing.user_plugin"]

FIXTURES_DIR = Path(__file__).parent / "fixtures"

PdfFactory = Callable[[Path, list[str]], Path]


def write_pdf(path: Path, ids: list[str]) -> Path:
    """Write a PDF with one page per id, each stamped with an invisible SSID marker.

    An empty-string id yields an unmarked page — the same shape a missing
    ``\\ssid`` produces. This lets tests fabricate "recompiled" decks with
    added/renamed/removed slides without running LaTeX.
    """
    doc = fitz.open()
    for slide_id in ids:
        page = doc.new_page(width=400, height=300)  # 4:3, like the beamer fixture
        page.insert_text((20, 280), "page body", fontsize=10)
        if slide_id:
            # render_mode=3 = invisible text, matching slidesonnet.sty's stamping
            page.insert_text((20, 20), f"SSID:{slide_id}", fontsize=4, render_mode=3)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def make_pdf() -> PdfFactory:
    return write_pdf


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def marked_pdf(fixtures_dir):
    return fixtures_dir / "marked.pdf"


@pytest.fixture
def pronunciation_cs(fixtures_dir):
    return fixtures_dir / "pronunciation_cs.md"
