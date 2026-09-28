"""Review over the API: one read model and typed author commands (``review/*`` underneath)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from slidesonnet.gui.library import DeckRegistry
from slidesonnet.review import ops
from slidesonnet.server.app import create_api_app
from slidesonnet.server.context import SESSION_HEADER
from tests.conftest import simple_narration, write_pdf


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    (tmp_path / "d").mkdir()
    pdf = write_pdf(tmp_path / "d" / "deck.pdf", ["a", "b", "c"])
    (tmp_path / "d" / "deck.narration").write_text(
        simple_narration("@a\nHello there.\n@b\nSecond.\n"), encoding="utf-8"
    )
    return pdf


@pytest.fixture
def client(pdf: Path) -> Iterator[TestClient]:
    registry = DeckRegistry(pdf.parent.parent)
    registry.rescan()
    with TestClient(create_api_app(registry)) as c:
        c.headers[SESSION_HEADER] = c.get("/api/v1/session").json()["token"]
        yield c


def _token(c: TestClient) -> str:
    return str(c.get("/api/v1/library").json()["sections"][0]["decks"][0]["token"])


def _cmd(c: TestClient, token: str, **body: object) -> dict:  # type: ignore[type-arg]
    r = c.post(f"/api/v1/decks/{token}/review/commands", json=body)
    assert r.status_code == 200, r.text
    return dict(r.json())


def _edit_page(pdf: Path, index: int) -> None:
    doc = fitz.open(pdf)
    doc[index].insert_text((20, 150), "edited", fontsize=14)
    doc.saveIncr()
    doc.close()


def test_a_review_round_through_the_api(client: TestClient, pdf: Path) -> None:
    token = _token(client)
    assert client.get(f"/api/v1/decks/{token}/review").json()["active"] is False
    _cmd(client, token, type="start")
    _edit_page(pdf, 1)
    sidecar = pdf.with_suffix(".narration")
    sidecar.write_text(simple_narration("@a\nHello over there.\n@b\nSecond.\n"), "utf-8")

    review = client.get(f"/api/v1/decks/{token}/review").json()
    changed = {c["slide_id"]: c for c in review["changes"]}
    assert changed["b"]["image"] and changed["a"]["narration"]
    assert "b" in review["base_images"]  # the before picture for the compare view
    assert ["+", "over"] in review["diffs"]["a"]
    assert set(review["unfiled"]) == {"a", "b"} and review["badges"]["b"] == "unfiled"

    conv = _cmd(client, token, type="comment", slides=["b", "zeta"], text="Why the change?")
    review = client.get(f"/api/v1/decks/{token}/review").json()
    assert review["badges"]["b"] == "agent-turn"
    assert review["pending"] == {"zeta": [conv["conversation"]]}  # declared, not compiled yet
    ops.reply(pdf, conv["conversation"], "Clearer now.", author="agent")
    assert client.get(f"/api/v1/decks/{token}/review").json()["badges"]["b"] == "your-turn"

    _cmd(client, token, type="accept", conversation=conv["conversation"])
    assert client.get(f"/api/v1/decks/{token}/review").json()["badges"]["b"] == "closed"
    _cmd(client, token, type="reopen", conversation=conv["conversation"])
    _cmd(client, token, type="accept", conversation=conv["conversation"])
    assert "Cleared 1" in _cmd(client, token, type="clear")["message"]


def test_unrequested_changes_are_filed_and_refusals_are_readable(
    client: TestClient, pdf: Path
) -> None:
    token = _token(client)
    _cmd(client, token, type="start")
    _edit_page(pdf, 0)
    filed = _cmd(client, token, type="file_unrequested")
    assert filed["count"] == 1 and filed["conversation"] and filed["focus"] is False
    bad = client.post(
        f"/api/v1/decks/{token}/review/commands", json={"type": "reply", "conversation": "c99",
                                                        "text": "?"},
    )  # fmt: skip
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "review_refused"
