"""Running the editor: the library it scans, the URL it opens, and --dev's reload factory."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.server import run
from slidesonnet.server.context import context_of
from slidesonnet.server.library import deck_token
from tests.conftest import simple_narration, write_pdf


def _deck(folder: Path, stem: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    pdf = write_pdf(folder / f"{stem}.pdf", ["a"])
    (folder / f"{stem}.narration").write_text(simple_narration("@a\nHi.\n"), encoding="utf-8")
    return pdf


def test_the_library_and_the_first_page(tmp_path: Path) -> None:
    other = _deck(tmp_path / "elsewhere", "outside")
    _deck(tmp_path / "course" / "w1", "intro")
    reg = run.build_registry(other, sidecar_path=None, root=tmp_path / "course")
    # an explicitly opened deck is served even from outside the scanned folder
    assert {e.name for e in reg.entries()} == {"intro", "outside"}
    assert run.start_url(other, "127.0.0.1", 8080) == f"http://127.0.0.1:8080/d/{deck_token(other)}"
    assert run.start_url(None, "0.0.0.0", 9000) == "http://localhost:9000/"  # a wildcard bind


def test_dev_app_rebuilds_the_same_editor_from_its_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path / "w1", "intro")
    env = run.dev_environment(pdf, root=tmp_path, sidecar_path=None, host="0.0.0.0", port=8123)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    app = run.dev_app()
    ctx = context_of(app)
    assert ctx.registry.resolve(deck_token(pdf)) is not None
    assert ctx.on_deck_open is run.retarget_deck_log  # the run-log follows the open deck
