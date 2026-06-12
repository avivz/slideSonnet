"""Shared test fixtures."""

import base64
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import fitz  # type: ignore[import-untyped]
import pytest

# NiceGUI's in-process `user` fixture (no selenium). The combined plugin pulls
# in selenium for the `screen` fixture, so load only the user plugin.
pytest_plugins = ["nicegui.testing.user_plugin"]

_SENTINEL_KEY = "unit-test-no-real-calls"


class _GuardedElevenLabs:
    """Stand-in for the real ElevenLabs client: any construction is a test bug.

    Tests that need a client mock ``@patch("slidesonnet.tts.elevenlabs.ElevenLabs")``
    over this, so only an unmocked (would-be real, would-be billed) construction
    ever reaches here.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "test constructed a real ElevenLabs client — this would call the paid API; "
            "mock slidesonnet.tts.elevenlabs.ElevenLabs instead"
        )


@pytest.fixture(autouse=True)
def _no_real_elevenlabs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make a real ElevenLabs call impossible from any test.

    Two layers: the API key env var is pinned to a sentinel (load_dotenv won't
    override an existing var, so doctor's ``load_dotenv()`` can't leak the real
    key from the repo-root ``.env`` into the suite), and the client class is
    replaced with one that fails fast on construction.
    """
    monkeypatch.setenv("ELEVENLABS_API_KEY", _SENTINEL_KEY)
    monkeypatch.setattr("slidesonnet.tts.elevenlabs.ElevenLabs", _GuardedElevenLabs)
    yield


# 1x1 black pixel — a valid PNG for stubbing rasterized page images
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "h6FO1AAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def _stub_page_rasterize(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Replace per-test pdftoppm rasterization with stub PNGs in the unit tier.

    GUI unit tests would otherwise shell out to pdftoppm for every test (the
    suite's main time sink) — and silently exercise a different code path in
    CI, where poppler isn't installed. Real rasterization stays covered by the
    integration tier (test_pdf_reader.py), which this fixture leaves alone.
    """
    if request.node.get_closest_marker("integration") or request.node.get_closest_marker("browser"):
        yield
        return

    from slidesonnet.cache import render_dir
    from slidesonnet.gui.state import EditorState

    def fake_ensure_images(self: EditorState) -> list[Path]:
        if self._images is None:
            out = render_dir(self.pdf_path) / "pages"
            out.mkdir(parents=True, exist_ok=True)
            images: list[Path] = []
            for i in range(len(self.deck.pages)):
                page = out / f"page-{i + 1}.png"
                page.write_bytes(_TINY_PNG)
                images.append(page)
            self._images = images
        return self._images

    monkeypatch.setattr(EditorState, "ensure_images", fake_ensure_images)
    yield


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


MARKED_PDF = FIXTURES_DIR / "marked.pdf"


def prep_marked_deck(tmp_path: Path, sidecar: str = "") -> Path:
    """Copy the marked fixture PDF into *tmp_path*, optionally seeding a sidecar.

    *sidecar* uses the concise legacy flat grammar (see simple_narration).
    The canonical deck-prep helper — test files should use this instead of
    re-implementing the copy-and-seed dance.
    """
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED_PDF.read_bytes())
    if sidecar:
        (tmp_path / "marked.narration").write_text(simple_narration(sidecar), encoding="utf-8")
    return pdf


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def marked_pdf(fixtures_dir):
    return fixtures_dir / "marked.pdf"


@pytest.fixture
def pronunciation_cs(fixtures_dir):
    return fixtures_dir / "pronunciation_cs.md"
