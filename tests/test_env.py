"""The .env loader that feeds API keys to the synthesis path."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from slidesonnet.env import load_env
from slidesonnet.models import TTSConfig
from slidesonnet.tts import create_tts


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
