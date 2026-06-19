"""The .env loader that feeds API keys to the synthesis path."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from slidesonnet.env import load_env
from slidesonnet.models import TTSConfig
from slidesonnet.tts import create_tts

from tests.conftest import prep_marked_deck


def test_load_env_reads_dotenv_into_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SS_ENV_PROBE=from_dotenv\n", encoding="utf-8")
    monkeypatch.delenv("SS_ENV_PROBE", raising=False)
    load_env()
    assert os.environ.get("SS_ENV_PROBE") == "from_dotenv"


def test_load_env_does_not_override_exported_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An already-exported variable wins over .env (python-dotenv override=False)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SS_ENV_PROBE=from_dotenv\n", encoding="utf-8")
    monkeypatch.setenv("SS_ENV_PROBE", "from_shell")
    load_env()
    assert os.environ.get("SS_ENV_PROBE") == "from_shell"


def test_load_env_finds_dotenv_at_anchor_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the deck (and its ``.env``) may live outside the cwd tree —
    e.g. the editor launched from ``$HOME``. ``load_env`` must find the deck's
    ``.env`` when anchored at the deck directory, regardless of cwd. Previously
    the search ran only from the cwd upward, so a key sitting next to the deck was
    invisible and Inworld failed with "API_KEY not set"."""
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    deck_dir = tmp_path / "decks" / "talk"
    deck_dir.mkdir(parents=True)
    (deck_dir / ".env").write_text("SS_ENV_ANCHOR=from_deck_dir\n", encoding="utf-8")
    monkeypatch.chdir(cwd)  # no .env reachable upward from cwd
    monkeypatch.delenv("SS_ENV_ANCHOR", raising=False)
    load_env(deck_dir)
    assert os.environ.get("SS_ENV_ANCHOR") == "from_deck_dir"


def test_load_env_anchor_does_not_override_exported_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shell export still wins over a deck-dir ``.env`` (override=False)."""
    deck_dir = tmp_path / "talk"
    deck_dir.mkdir()
    (deck_dir / ".env").write_text("SS_ENV_ANCHOR=from_deck_dir\n", encoding="utf-8")
    monkeypatch.setenv("SS_ENV_ANCHOR", "from_shell")
    load_env(deck_dir)
    assert os.environ.get("SS_ENV_ANCHOR") == "from_shell"


def test_synthesize_path_anchors_dotenv_at_deck_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API synthesis path loads the deck-dir ``.env`` even when the cwd has
    no reachable ``.env`` — the user's failure mode (editor launched from a
    directory the repo ``.env`` doesn't sit under)."""
    import slidesonnet.api as api

    pdf = prep_marked_deck(tmp_path)  # deck lives in tmp_path
    (tmp_path / ".env").write_text("SS_ENV_ANCHOR=from_deck_dir\n", encoding="utf-8")
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("SS_ENV_ANCHOR", raising=False)
    # No segments to synthesize (only_ids=set()) → _load runs, but no engine is
    # constructed and no model loads; we only assert .env reached os.environ.
    api.synthesize_deck(pdf, engine="kokoro", only_ids=set())
    assert os.environ.get("SS_ENV_ANCHOR") == "from_deck_dir"


def test_create_tts_loads_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a key in .env must reach the engines. create_tts() — the one
    factory every synthesis path (CLI, GUI preview, background queue) flows
    through — loads .env so os.environ has the key before any engine reads it.
    Previously only `slidesonnet doctor` called load_dotenv, so a key sitting in
    .env was invisible to actual generation."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SS_ENV_PROBE=from_dotenv\n", encoding="utf-8")
    monkeypatch.delenv("SS_ENV_PROBE", raising=False)
    create_tts(TTSConfig())  # default backend; construction is lazy (no model load)
    assert os.environ.get("SS_ENV_PROBE") == "from_dotenv"
