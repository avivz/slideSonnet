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


def test_an_ipv6_host_is_bracketed_in_the_url() -> None:
    assert run.start_url(None, "::1", 8080) == "http://[::1]:8080/"
    assert run.start_url(None, "::", 8080) == "http://localhost:8080/"


@pytest.mark.parametrize(
    ("host", "allow", "outcome"),
    [
        ("127.0.0.1", [], None),
        ("localhost", [], None),
        ("::1", [], None),
        ("192.168.1.20", [], "warn"),  # that address is accepted as a Host
        ("0.0.0.0", ["192.168.1.20"], "warn"),
        ("0.0.0.0", [], "refuse"),  # would answer no one but localhost: say how to fix it
        ("::", [], "refuse"),
    ],
)
def test_binding_beyond_this_machine_is_explicit(
    host: str, allow: list[str], outcome: str | None
) -> None:
    if outcome == "refuse":
        with pytest.raises(run.BindRefused, match="--allow-host"):
            run.check_bind(host, 8080, allow)
        return
    warning = run.check_bind(host, 8080, allow)
    assert (warning is not None and "other machines" in warning) == (outcome == "warn")


def test_edit_refuses_a_wildcard_bind_without_allow_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from click.testing import CliRunner

    from slidesonnet.cli import main

    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("the server must not start")

    monkeypatch.setattr(run, "run_editor", never)
    pdf = _deck(tmp_path, "intro")
    result = CliRunner().invoke(
        main, ["--no-log-file", "edit", str(pdf), "--host", "0.0.0.0", "--no-browser"]
    )
    assert result.exit_code == 2 and "--allow-host" in result.output
    assert "--allow-host" in CliRunner().invoke(main, ["edit", "--help"]).output


def test_dev_app_rebuilds_the_same_editor_from_its_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _deck(tmp_path / "w1", "intro")
    env = run.dev_environment(
        pdf, root=tmp_path, sidecar_path=None, host="0.0.0.0", port=8123, allow_hosts=["a.lan"]
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    app = run.dev_app()
    ctx = context_of(app)
    assert ctx.registry.resolve(deck_token(pdf)) is not None
    assert ctx.on_deck_open is run.retarget_deck_log  # the run-log follows the open deck
    assert "a.lan" in ctx.allowed_hosts and "0.0.0.0" not in ctx.allowed_hosts
