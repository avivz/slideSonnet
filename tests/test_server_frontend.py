"""Serving the Vue bundle: the shell at /, hashed assets cached hard, a clear unbuilt page.

Uses a stand-in bundle in a temp dir, so the Python tier never needs Node.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slidesonnet.gui.library import DeckRegistry
from slidesonnet.server import frontend
from slidesonnet.server.app import create_api_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_api_app(DeckRegistry(tmp_path))) as c:
        yield c


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<div id=app></div>", encoding="utf-8")
    (static / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(frontend, "STATIC_DIR", static)
    return static


def test_shell_and_assets(client: TestClient, bundle: Path) -> None:
    shell = client.get("/")
    assert shell.status_code == 200 and "id=app" in shell.text
    assert shell.headers["cache-control"] == "no-cache"  # a new build must show up at once
    asset = client.get("/ui/assets/index-abc123.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    for missing in ("/ui/assets/gone.js", "/ui/index.html", "/ui/../../secret"):
        assert client.get(missing).status_code == 404  # never the shell for a missing asset


def test_unbuilt_checkout_says_how_to_build(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(frontend, "STATIC_DIR", tmp_path / "nothing-here")
    page = client.get("/")
    assert page.status_code == 503
    assert "make frontend" in page.text
