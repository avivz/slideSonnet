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


def simple_narration(text: str) -> str:
    """Convert the legacy flat sidecar grammar to the structured block grammar.

    Lets tests keep seeding narration concisely as ``@id`` + a body line with
    inline ``[pause N]`` (and optional ``:voice``/``:pace`` directives) while the
    on-disk format is the structured one. Per-block voice/pace map onto every
    speech utterance in that block.
    """
    from slidesonnet.narration.format import parse_segments, serialize_sidecar
    from slidesonnet.narration.model import PageNarration, Segment

    blocks: list[PageNarration] = []
    cur: PageNarration | None = None
    voice: str | None = None
    pace: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal cur, voice, pace
        if cur is not None:
            segs = parse_segments(" ".join(body))
            cur.segments = [
                Segment.speech(s.text, voice=voice, pace=pace) if s.is_speech else s  # type: ignore[arg-type]
                for s in segs
            ]
            blocks.append(cur)
        voice = pace = None
        body.clear()

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if raw.lstrip().startswith("#") else raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("@"):
            flush()
            cur = PageNarration(slide_id=stripped[1:].strip())
        elif stripped.startswith(":voice "):
            voice = stripped[len(":voice ") :].strip()
        elif stripped.startswith(":pace "):
            pace = stripped[len(":pace ") :].strip()
        else:
            body.append(stripped)
    flush()
    return serialize_sidecar(blocks)


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def marked_pdf(fixtures_dir):
    return fixtures_dir / "marked.pdf"


@pytest.fixture
def pronunciation_cs(fixtures_dir):
    return fixtures_dir / "pronunciation_cs.md"
