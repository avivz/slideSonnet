"""Shared test fixtures."""

import base64
import io
import sys
import wave
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import fitz  # type: ignore[import-untyped]
import pytest

from slidesonnet.tts.base import TTSEngine

# NiceGUI's in-process `user` fixture (no selenium). The combined plugin pulls
# in selenium for the `screen` fixture, so load only the user plugin.
pytest_plugins = ["nicegui.testing.user_plugin"]

_SENTINEL_KEY = "unit-test-no-real-calls"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-mark slow GUI tests, then sort the browser tier last.

    Any test using NiceGUI's in-process ``user`` fixture spins up (and tears
    down) a server per test — ~0.8 s of pure lifecycle overhead and ~95 % of the
    unit tier's wall time. Tag those ``gui`` so a fast inner loop can skip them
    with ``-m "not gui"`` (see CLAUDE.md). ``tryfirst`` guarantees the marks land
    before pytest's own ``-m`` deselection reads them.

    Browser tests then sort last (stable): Playwright's sync API parks a running
    asyncio loop in the main thread for the life of its session-scoped fixtures,
    so once one browser test has run, any later pytest-asyncio setup — every
    nicegui ``user`` test — dies with "Runner.run() cannot be called from a
    running event loop".
    """
    for item in items:
        if "user" in getattr(item, "fixturenames", ()):
            item.add_marker("gui")
    items.sort(key=lambda item: item.get_closest_marker("browser") is not None)


@pytest.fixture(autouse=True)
def _isolate_model_cache() -> Iterator[None]:
    """Reset the process-wide TTS model cache between tests for order-independence.

    ``slidesonnet.tts.qwen3`` caches warmed models in a module-global dict; a test
    that warms a heavy engine would otherwise leave it warm for later tests (e.g.
    a warmup-pending assertion would flake depending on collection order). We clear
    it only when the module is already imported — importing it pulls torch, and the
    bulk of the suite never touches qwen3, so this stays zero-cost for them.
    """
    mod = sys.modules.get("slidesonnet.tts.qwen3")
    if mod is not None:
        mod._MODEL_CACHE.clear()
    yield
    mod = sys.modules.get("slidesonnet.tts.qwen3")
    if mod is not None:
        mod._MODEL_CACHE.clear()


class _GuardedInworld:
    """Stand-in for the real Inworld client: any construction is a test bug.

    Tests that need a client mock ``@patch("slidesonnet.tts.inworld.InworldClient")``
    over this, so only an unmocked (would-be real, would-be billed) construction
    ever reaches here.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "test constructed a real Inworld client — this would call the paid API; "
            "mock slidesonnet.tts.inworld.InworldClient instead"
        )


@pytest.fixture(autouse=True)
def _no_real_inworld(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make a real Inworld call impossible from any test.

    The API key env var is pinned to a sentinel (so doctor's ``load_dotenv()``
    can't leak a real key from ``.env``), and the SDK client class is replaced
    with one that fails fast on construction.
    """
    monkeypatch.setenv("INWORLD_API_KEY", _SENTINEL_KEY)
    monkeypatch.setattr("slidesonnet.tts.inworld.InworldClient", _GuardedInworld)
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


def _silent_wav_bytes() -> bytes:
    """A tiny but valid mono WAV (10 ms of silence), enough for ffprobe."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24_000)
        w.writeframes(b"\x00\x00" * 240)
    return buf.getvalue()


_TINY_WAV = _silent_wav_bytes()


class _StubTTS(TTSEngine):
    """Writes a tiny WAV instead of synthesizing — lets unit-tier tests drive the
    generation/preview path without a real engine. Reports the configured backend
    as its ``name()`` so the content-addressed cache path matches what the status
    scan computes (both go through ``synth.create_tts``)."""

    def __init__(self, backend: str) -> None:
        self._backend = backend

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(_TINY_WAV)
        return 1.0

    def name(self) -> str:
        return self._backend

    def cache_key(self) -> str:
        return "stub"


@pytest.fixture(autouse=True)
def _stub_tts_synthesis(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Replace real TTS synthesis with a stub for GUI unit tests.

    A GUI test that plays/generates would otherwise shell out to a real engine
    (Kokoro) — slow locally, and broken in CI where ``kokoro``/``torch`` aren't
    installed (the deck-synthesis path raises "kokoro package not installed",
    erroring the test). This patches only ``synth.create_tts`` (the actual
    synthesis chokepoint), so ``state.py``'s engine construction — voice lists,
    model-warmup status — keeps its real behavior.

    Scope is the ``gui`` marker (auto-applied to any ``user``-fixture test): the
    tests that exercise synthesis *internals* — cache-key, pace→speed, clean's
    keep-set — are non-GUI (``test_kokoro``/``test_clean``/``test_synth``) and
    must keep the real engine, so they're left alone. Real GUI-with-Kokoro
    coverage stays in the integration tier.
    """
    skip = (
        request.node.get_closest_marker("gui") is None
        or request.node.get_closest_marker("integration") is not None
        or request.node.get_closest_marker("browser") is not None
    )
    if skip:
        yield
        return

    from slidesonnet.audio import synth as synth_mod

    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: _StubTTS(cfg.backend))
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
