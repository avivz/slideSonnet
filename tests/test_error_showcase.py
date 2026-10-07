"""How the editor reports every reconciliation error, one slide each.

Driven against the committed ``examples/error-showcase`` deck (the same one a
human can open with ``slidesonnet edit``), through the API the editor reads —
the counts, per-slide findings, and unattached narration it shows. How those
appear on screen is covered by the frontend tests.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from slidesonnet.cli import main
from slidesonnet.server.app import create_api_app
from slidesonnet.server.context import SESSION_HEADER
from slidesonnet.server.library import DeckRegistry

EXAMPLE = Path(__file__).parent.parent / "examples" / "error-showcase"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """The example deck copied to tmp, so tests never dirty the committed example."""
    (tmp_path / "error-showcase.pdf").write_bytes((EXAMPLE / "error-showcase.pdf").read_bytes())
    (tmp_path / "error-showcase.narration").write_text(
        (EXAMPLE / "error-showcase.narration").read_text(encoding="utf-8"), encoding="utf-8"
    )
    registry = DeckRegistry(tmp_path)
    registry.rescan()
    with TestClient(create_api_app(registry)) as c:
        c.headers[SESSION_HEADER] = c.get("/api/v1/session").json()["token"]
        yield c


def _snapshot(c: TestClient) -> tuple[str, dict[str, Any]]:
    token = c.get("/api/v1/library").json()["sections"][0]["decks"][0]["token"]
    return token, c.get(f"/api/v1/decks/{token}").json()


def _findings(snap: dict[str, Any], slide: str) -> str:
    return " | ".join(d["message"] for d in snap["diagnostics"] if d["slide_id"] == slide)


def test_example_stays_deliberately_broken() -> None:
    """Guard the example: every advertised finding must keep firing."""
    res = CliRunner().invoke(main, ["check", str(EXAMPLE / "error-showcase.pdf")])
    assert res.exit_code == 1
    assert "renamed to 'twin-2'" in res.output  # duplicate \\ssid: disambiguated + warned
    assert "'double-block' has more than one narration block (lines 12 and 16" in res.output
    assert "double-block-2" not in res.output  # the made-up id stays out of check's report
    assert "'ghost-slide' has no matching PDF page" in res.output
    assert "auto-generated default" in res.output
    assert "slide 'silent-stage' has no narration block" in res.output


def test_every_finding_reaches_the_editor(client: TestClient) -> None:
    _, snap = _snapshot(client)
    errors = [d for d in snap["diagnostics"] if d["severity"] == "error"]
    # two orphans: ghost-slide and double-block-2 (the disambiguated duplicate block)
    assert len(errors) == 2
    ids = [p["slide_id"] for p in snap["pages"]]
    assert ids[0] == "all-good" and _findings(snap, "all-good") == ""
    assert "auto-generated default" in _findings(snap, ids[1])  # the frame without \\ssid
    assert "no narration block" in _findings(snap, "silent-stage")
    assert snap["pages"][2]["audio"]["speech"] == 0  # nothing to play or generate there
    assert "appears on several pages" in _findings(snap, "twin")
    assert "renamed to 'twin-2'" in _findings(snap, "twin-2")  # narratable under its new id
    # a duplicate @block self-heals: the slide keeps the first, the second is unattached
    assert "I am the first of two blocks" in str(snap["narration"]["double-block"])
    assert sorted(snap["orphans"]) == ["double-block-2", "ghost-slide"]
    assert "no longer exists in the PDF" in str(snap["narration"]["ghost-slide"])


def test_unattached_text_folds_into_a_healthy_slide(client: TestClient, tmp_path: Path) -> None:
    token, snap = _snapshot(client)
    r = client.post(
        f"/api/v1/decks/{token}/commands",
        json={"type": "append_orphan", "expected_revision": snap["revisions"]["narration"],
              "orphan_id": "ghost-slide", "target_id": "all-good"},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    sidecar = (tmp_path / "error-showcase.narration").read_text(encoding="utf-8")
    assert "@ghost-slide" not in sidecar and "no longer exists in the PDF" in sidecar


def _preview(client: TestClient, token: str, slide: str) -> dict[str, Any]:
    r = client.post(
        f"/api/v1/decks/{token}/jobs",
        json={"kind": "preview", "slide_id": slide, "engine": "kokoro"},
    )
    assert r.status_code == 202, r.text
    for _ in range(3000):
        job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return dict(job)
        time.sleep(0.1)
    raise AssertionError("preview never finished")


@pytest.mark.integration
def test_previews_survive_every_error(client: TestClient) -> None:
    """Empty pages, twins, and orphans never stop hearing the narration (real Kokoro)."""
    token, _ = _snapshot(client)
    job = _preview(client, token, "twin")  # an ambiguous id
    assert job["status"] == "succeeded", job
    assert job["result"]["duration"] > 0
