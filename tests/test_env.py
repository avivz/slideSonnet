"""Per-deck ``.env`` values: read for each deck, never written into ``os.environ``."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slidesonnet.cache import AUDIO_DIR_ENV, resolve_audio_dir
from slidesonnet.env import getenv
from slidesonnet.models import TTSConfig
from slidesonnet.tts import create_tts
from tests.conftest import prep_marked_deck, write_pdf


@pytest.fixture
def two_decks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Decks A and B, each with its own ``.env`` (fake key, own pool); no shell exports."""
    monkeypatch.chdir(tmp_path)  # no developer .env reachable from the cwd
    monkeypatch.delenv("INWORLD_API_KEY", raising=False)
    decks = {}
    for name in ("a", "b"):
        d = tmp_path / name
        d.mkdir()
        (d / ".env").write_text(
            f"INWORLD_API_KEY=fake-{name}\n{AUDIO_DIR_ENV}={tmp_path / f'pool-{name}'}\n",
            encoding="utf-8",
        )
        decks[name] = write_pdf(d / "deck.pdf", ["intro"])
    return decks


def _inworld_key(deck: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    from slidesonnet.tts.inworld import InworldTTS

    client = MagicMock()
    monkeypatch.setattr("slidesonnet.tts.inworld.InworldClient", client)
    InworldTTS(TTSConfig(backend="inworld", env_dir=deck.parent))._ensure_client()
    return str(client.call_args.kwargs["api_key"])


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_each_deck_uses_its_own_env_whatever_the_order(
    two_decks: dict[str, Path], monkeypatch: pytest.MonkeyPatch, order: tuple[str, str]
) -> None:
    for name in order:
        deck = two_decks[name]
        assert _inworld_key(deck, monkeypatch) == f"fake-{name}"
        res = resolve_audio_dir(deck)
        assert (res.path.name, res.source) == (f"pool-{name}", "env")
    assert "INWORLD_API_KEY" not in os.environ and AUDIO_DIR_ENV not in os.environ


def test_a_shell_export_wins_over_the_deck_env(
    two_decks: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INWORLD_API_KEY", "from-shell")
    monkeypatch.setenv(AUDIO_DIR_ENV, str(tmp_path / "shell-pool"))
    assert _inworld_key(two_decks["a"], monkeypatch) == "from-shell"
    assert resolve_audio_dir(two_decks["a"]).path.name == "shell-pool"


def test_the_deck_env_is_found_from_anywhere_and_beats_the_cwd_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The editor may be launched from a directory the deck's tree never reaches."""
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    (cwd / ".env").write_text("SS_PROBE=from_cwd\nSS_ONLY_CWD=yes\n", encoding="utf-8")
    deck_dir = tmp_path / "decks" / "talk"
    deck_dir.mkdir(parents=True)
    (tmp_path / "decks" / ".env").write_text("SS_PROBE=from_deck_tree\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("SS_PROBE", raising=False)
    assert getenv("SS_PROBE", deck_dir) == "from_deck_tree"
    assert getenv("SS_ONLY_CWD", deck_dir) == "yes"
    assert getenv("SS_PROBE") == "from_cwd"
    assert "SS_PROBE" not in os.environ


def test_the_synthesis_path_points_the_engine_at_the_deck_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet import api

    pdf = prep_marked_deck(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SS_PROBE=from_deck_dir\n", encoding="utf-8")
    _deck, config, _diags = api._load(pdf, None, None, "kokoro")
    assert config.tts.env_dir == pdf.resolve().parent
    create_tts(config.tts)
    assert "SS_PROBE" not in os.environ  # nothing leaks into the process for the next deck
