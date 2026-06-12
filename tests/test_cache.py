"""Cache layout invariants."""

from pathlib import Path

from slidesonnet.cache import audio_dir, cache_root, render_dir


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
