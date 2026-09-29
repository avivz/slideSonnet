"""Shared test fixtures."""

import base64
import io
import sys
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymupdf  # type: ignore[import-untyped]
import pytest

from slidesonnet.tts.base import TTSEngine

_SENTINEL_KEY = "unit-test-no-real-calls"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Sort the browser tier last (stable).

    Playwright's sync API parks a running asyncio loop in the main thread for
    the life of its session-scoped fixtures, so an async test collected after
    a browser test would die with "Runner.run() cannot be called from a
    running event loop".
    """
    items.sort(key=lambda item: item.get_closest_marker("browser") is not None)


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    """Strip slideSonnet's console/file handlers between tests for order-independence.

    Deck commands now attach a rotating file handler (under the deck's tmp_path
    cache) and the CLI group installs a console handler; left in place they would
    keep writing to a previous test's now-deleted directory and leak across tests.
    We remove only our own named handlers, leaving pytest's ``caplog`` alone.
    """
    import logging

    from slidesonnet.logging_setup import PACKAGE_LOGGER

    def _strip() -> None:
        for logger in (logging.getLogger(), logging.getLogger(PACKAGE_LOGGER)):
            for handler in list(logger.handlers):
                if str(getattr(handler, "name", "")).startswith("slidesonnet-"):
                    logger.removeHandler(handler)
                    handler.close()
        logging.getLogger(PACKAGE_LOGGER).setLevel(logging.NOTSET)

    _strip()
    yield
    _strip()


@pytest.fixture(autouse=True)
def _isolate_model_cache() -> Iterator[None]:
    """Reset the process-wide TTS model cache between tests for order-independence.

    ``slidesonnet.tts.qwen3`` caches warmed models in a module-global dict; a test
    that warms a heavy engine would otherwise leave it warm for later tests (e.g.
    a warmup-pending assertion would flake depending on collection order). We clear
    it only when the module is already imported — importing it pulls torch, and the
    bulk of the suite never touches qwen3, so this stays zero-cost for them.
    """

    def clear() -> None:
        mod = sys.modules.get("slidesonnet.tts.qwen3")
        if mod is not None:
            mod._MODEL_CACHE.clear()
        hashing = sys.modules.get("slidesonnet.hashing")
        if hashing is not None:
            hashing._CONTENT_HASHES.clear()  # memoized .pt voice-prompt digests

    clear()
    yield
    clear()


@pytest.fixture(autouse=True)
def _isolate_deck_services() -> Iterator[None]:
    """Forget the process-wide per-deck services (and their pending sweeps) per test.

    ``slidesonnet.server.decks`` keeps one service per deck path; a later test
    reusing a tmp path must not inherit an earlier test's lock or prune timer.
    """
    from slidesonnet.server import previews
    from slidesonnet.server.decks import reset_services
    from slidesonnet.server.review import reset_review_models

    reset_services()
    reset_review_models()
    previews._SILENCES.clear()
    yield
    reset_services()
    reset_review_models()
    previews._SILENCES.clear()


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
def _editor_starts_on_kokoro(monkeypatch: pytest.MonkeyPatch) -> None:
    """The editor starts on paid Inworld when a deck names no engine; tests run on
    the free engine unless they opt in (``engines.EDITOR_DEFAULT_ENGINE``)."""
    from slidesonnet.server import engines

    monkeypatch.setattr(engines, "EDITOR_DEFAULT_ENGINE", "kokoro")


@pytest.fixture(autouse=True)
def _no_pool_env() -> Iterator[None]:
    """Keep ``SLIDESONNET_AUDIO_DIR`` out of every test unless it sets it itself.

    The CLI's ``--audio-dir`` writes the variable into ``os.environ`` for the
    process (that's how every resolver sees it), so a CLI test would otherwise
    leave a pool pinned for the tests collected after it — and a developer's
    own shell export would silently redirect the suite's clips.
    """
    import os

    from slidesonnet.cache import AUDIO_DIR_ENV

    saved = os.environ.pop(AUDIO_DIR_ENV, None)
    yield
    os.environ.pop(AUDIO_DIR_ENV, None)
    if saved is not None:
        os.environ[AUDIO_DIR_ENV] = saved


@pytest.fixture(autouse=True)
def _no_real_inworld(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make a real Inworld call impossible from any test.

    The API key env var is pinned to a sentinel (a process variable beats any
    ``.env``, so a developer's real key in one is never read), and the SDK
    client class is replaced with one that fails fast on construction.
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

    Unit tests that render pages (the editor API, review captures) would
    otherwise shell out to pdftoppm — slow, and a different code path in CI,
    where poppler isn't installed. Real rasterization stays covered by the
    integration tier (test_pdf_reader.py), which this fixture leaves alone.
    """
    if request.node.get_closest_marker("integration") or request.node.get_closest_marker("browser"):
        yield
        return
    if request.node.module.__name__.endswith("test_pdf_reader"):
        yield  # the reader's own tests stub (or need) the real pdftoppm call
        return

    from slidesonnet.pdf.reader import page_count

    def fake_pdftoppm(cmd: list[str], **_kw: object) -> None:
        """Write a stub PNG per requested page, named as pdftoppm would."""
        pdf, prefix = Path(cmd[-2]), cmd[-1]
        total = page_count(pdf)
        first = int(cmd[cmd.index("-f") + 1]) if "-f" in cmd else 1
        last = int(cmd[cmd.index("-l") + 1]) if "-l" in cmd else total
        width = len(str(total))
        for n in range(first, last + 1):
            Path(f"{prefix}-{n:0{width}d}.png").write_bytes(_TINY_PNG)

    monkeypatch.setattr("slidesonnet.pdf.reader.run_tool", fake_pdftoppm)
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
    generation path without a real engine (patch it in for ``synth.create_tts``).
    Reports the configured backend as its ``name()`` so the content-addressed
    cache path matches what the status scan computes."""

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


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def write_pdf(path: Path, ids: list[str], *, final: bool = False, plain: bool = False) -> Path:
    """Write a PDF with one page per id, each stamped with an invisible SSID marker.

    An empty-string id yields an unmarked page — the same shape a missing
    ``\\ssid`` produces. This lets tests fabricate "recompiled" decks with
    added/renamed/removed slides without running LaTeX. *final* stamps the
    ``SSFINAL`` marker a ``\\ssfinal`` build carries; *plain* the ``SSPLAIN``
    marker an ordinary compile with the current ``slidesonnet.sty`` carries.
    """
    doc = pymupdf.open()
    for slide_id in ids:
        page = doc.new_page(width=400, height=300)  # 4:3, like the beamer fixture
        page.insert_text((20, 280), "page body", fontsize=10)
        if slide_id:
            # render_mode=3 = invisible text, matching slidesonnet.sty's stamping
            suffix = " SSFINAL" if final else " SSPLAIN" if plain else ""
            marker = f"SSID:{slide_id}{suffix}"
            page.insert_text((20, 20), marker, fontsize=4, render_mode=3)
    doc.save(path)
    doc.close()
    return path


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
def pronunciation_cs() -> Path:
    return FIXTURES_DIR / "pronunciation_cs.md"
