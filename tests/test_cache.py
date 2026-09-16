"""Cache layout invariants and speech-clip pool resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.cache import (
    AUDIO_DIR_ENV,
    adopt_legacy_audio,
    audio_dir,
    cache_root,
    default_audio_dir,
    render_dir,
    resolve_audio_dir,
)
from slidesonnet.config import Config


def test_cache_root_is_sibling_dotdir(tmp_path: Path) -> None:
    assert cache_root(tmp_path / "deck.pdf") == tmp_path / ".slidesonnet"


def test_audio_cache_is_shared_across_decks_in_a_dir(tmp_path: Path) -> None:
    # content-addressed clips: sharing across decks is safe and saves money
    assert audio_dir(tmp_path / "a.pdf") == audio_dir(tmp_path / "b.pdf")


def test_render_dirs_are_per_deck(tmp_path: Path) -> None:
    """Render artifacts use positional names (track.wav, page-N.png) — two decks
    in one directory must not share a render dir or concurrent operations
    interleave each other's files."""
    a = render_dir(tmp_path / "a.pdf")
    b = render_dir(tmp_path / "b.pdf")
    assert a != b
    assert a.parent == b.parent == cache_root(tmp_path / "a.pdf") / "render"


# ---- pool resolution: env var > [cache] audio_dir > default ---------------


def test_default_pool_is_the_deck_local_audio_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(AUDIO_DIR_ENV, raising=False)
    res = resolve_audio_dir(tmp_path / "deck.pdf", Config())
    assert (
        res.path == default_audio_dir(tmp_path / "deck.pdf") == tmp_path / ".slidesonnet" / "audio"
    )
    assert res.source == "default"
    assert not res.shared


def test_config_audio_dir_wins_over_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(AUDIO_DIR_ENV, raising=False)
    pool = tmp_path / "pool"
    res = resolve_audio_dir(tmp_path / "decks" / "deck.pdf", Config(audio_dir=pool))
    assert res.path == pool
    assert res.source == "config"
    assert res.shared


def test_env_var_wins_over_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A worktree carries its own copy of slidesonnet.toml, so the shell (or a
    course .env) is where one pool for every checkout gets pinned."""
    monkeypatch.setenv(AUDIO_DIR_ENV, str(tmp_path / "env-pool"))
    res = resolve_audio_dir(tmp_path / "deck.pdf", Config(audio_dir=tmp_path / "toml-pool"))
    assert res.path == tmp_path / "env-pool"
    assert res.source == "env"


def test_env_var_expands_tilde(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(AUDIO_DIR_ENV, "~/pool")
    assert audio_dir(tmp_path / "deck.pdf") == tmp_path / "pool"


def test_blank_env_var_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AUDIO_DIR_ENV, "   ")
    assert resolve_audio_dir(tmp_path / "deck.pdf", Config()).source == "default"


def test_config_pointing_at_the_default_dir_is_not_shared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pinning the pool to the main checkout's own cache dir is the recommended
    worktree setup; from the main checkout that resolves to the default and
    keeps per-deck clean's full semantics."""
    monkeypatch.delenv(AUDIO_DIR_ENV, raising=False)
    pdf = tmp_path / "deck.pdf"
    res = resolve_audio_dir(pdf, Config(audio_dir=default_audio_dir(pdf)))
    assert not res.shared


# ---- migration: clips in the old deck-local cache are adopted into the pool --


def _clip(directory: Path, name: str, data: bytes = b"clip") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_bytes(data)
    return p


def test_adopt_legacy_audio_copies_parseable_clips_into_the_pool(tmp_path: Path) -> None:
    pdf = tmp_path / "deck.pdf"
    legacy = default_audio_dir(pdf)
    _clip(legacy, "aaaa.kokoro.bbbb.wav")
    _clip(legacy, "cccc.inworld.dddd.mp3", b"paid")
    _clip(legacy, "notes.txt")  # not a clip: never copied
    pool = tmp_path / "pool"

    assert adopt_legacy_audio(pdf, pool) == 2
    assert (pool / "cccc.inworld.dddd.mp3").read_bytes() == b"paid"
    assert not (pool / "notes.txt").exists()
    assert (legacy / "cccc.inworld.dddd.mp3").exists()  # copy, not move — clean removes it


def test_adopt_legacy_audio_skips_clips_already_in_the_pool(tmp_path: Path) -> None:
    pdf = tmp_path / "deck.pdf"
    _clip(default_audio_dir(pdf), "aaaa.kokoro.bbbb.wav", b"local")
    pool = tmp_path / "pool"
    _clip(pool, "aaaa.kokoro.bbbb.wav", b"pool")
    assert adopt_legacy_audio(pdf, pool) == 0
    assert (pool / "aaaa.kokoro.bbbb.wav").read_bytes() == b"pool"


def test_adopt_legacy_audio_is_a_noop_without_a_pool_or_legacy_dir(tmp_path: Path) -> None:
    pdf = tmp_path / "deck.pdf"
    assert adopt_legacy_audio(pdf, default_audio_dir(pdf)) == 0  # pool *is* the legacy dir
    assert adopt_legacy_audio(pdf, tmp_path / "pool") == 0  # nothing to adopt
    assert not (tmp_path / "pool").exists()
