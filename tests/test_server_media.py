"""Per-deck media: isolation between decks and the caching policy.

(Ported from the in-process NiceGUI tests in test_gui_switching.py: the route
is plain FastAPI now, so a test client sees exactly what a browser would.)
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slidesonnet.cache import render_dir
from slidesonnet.gui.library import DeckRegistry, deck_token
from slidesonnet.server.app import create_api_app
from slidesonnet.server.media import is_content_stamp
from tests.conftest import simple_narration, write_pdf


def _deck(root: Path, stem: str) -> Path:
    folder = root / stem
    folder.mkdir(parents=True)
    pdf = write_pdf(folder / f"{stem}.pdf", ["a"])
    (folder / f"{stem}.narration").write_text(simple_narration("@a\nHi.\n"), encoding="utf-8")
    return pdf


@pytest.fixture
def decks(tmp_path: Path) -> tuple[Path, Path]:
    return _deck(tmp_path, "intro"), _deck(tmp_path, "llm")


@pytest.fixture
def client(tmp_path: Path, decks: tuple[Path, Path]) -> Iterator[TestClient]:
    registry = DeckRegistry(tmp_path)
    registry.rescan()
    with TestClient(create_api_app(registry)) as c:
        yield c


def _put(pdf: Path, rel: str, body: bytes) -> str:
    path = render_dir(pdf) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return f"/ssmedia/{deck_token(pdf)}/{rel}"


def test_each_deck_serves_its_own_files(client: TestClient, decks: tuple[Path, Path]) -> None:
    """One route serves every deck; the token picks the deck (never the first one opened)."""
    for pdf in decks:
        _put(pdf, "pages/probe.png", pdf.stem.encode())
    for pdf in decks:
        r = client.get(f"/ssmedia/{deck_token(pdf)}/pages/probe.png")
        assert r.status_code == 200 and r.content == pdf.stem.encode()


@pytest.mark.parametrize(
    ("rel", "query", "immutable"),
    [
        ("pages/page-1.png", "?v=1737000000000000000-4096", True),  # a content stamp
        ("pages/page-1.png", "", False),
        ("track.wav", "?v=1", False),  # rewritten in place: never pinned in the cache
        ("previews/0123abcd.wav", "", True),  # content-addressed preview track
    ],
)
def test_only_immutable_files_are_cached_hard(
    client: TestClient, decks: tuple[Path, Path], rel: str, query: str, immutable: bool
) -> None:
    url = _put(decks[0], rel, b"bytes") + query
    r = client.get(url)
    assert r.status_code == 200
    assert ("immutable" in r.headers["cache-control"]) is immutable


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1737000000000000000-4096", True),  # a real _media_url stamp
        ("1", False),  # the player's per-page-load counter — restarts every reload
        ("42", False),
        ("", False),
        (None, False),
        ("abc-4096", False),
        ("1737000000000000000-", False),
    ],
)
def test_only_a_real_content_stamp_earns_the_immutable_cache(
    value: str | None, expected: bool
) -> None:
    assert is_content_stamp(value) is expected
