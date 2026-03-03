"""Tests for the clean module."""

from __future__ import annotations

import textwrap
from pathlib import Path

from slidesonnet.clean import clean
from slidesonnet.hashing import audio_filename


def _create_playlist(tmp_path: Path, slides_text: str | None = None) -> Path:
    """Create a minimal playlist + slides project."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(
        textwrap.dedent("""\
        ---
        title: Test
        tts:
          backend: piper
          piper:
            model: en_US-lessac-medium
        ---

        1. [Intro](01-intro/slides.md)
    """)
    )

    slides_dir = tmp_path / "01-intro"
    slides_dir.mkdir()
    if slides_text is None:
        slides_text = textwrap.dedent("""\
            ---
            marp: true
            ---

            # Slide One

            <!-- say: Welcome to the first slide. -->

            ---

            # Slide Two

            <!-- say: This is the second slide. -->

            ---

            # Silent

            <!-- nonarration -->
        """)
    (slides_dir / "slides.md").write_text(slides_text)
    return playlist


def _populate_cache(tmp_path: Path) -> dict[str, Path]:
    """Create a cache dir with various audio files and build artifacts.

    Returns dict of name -> path for easy assertions.
    """
    cache = tmp_path / "cache"
    cache.mkdir()
    audio = cache / "audio"
    audio.mkdir()

    # Build artifacts
    module_dir = cache / "01-intro" / "slides"
    module_dir.mkdir(parents=True)
    (module_dir / "manifest.json").write_text("[]")
    slides_dir = module_dir / "slides"
    slides_dir.mkdir()
    segments_dir = cache / "01-intro" / "slides" / "segments"
    segments_dir.mkdir()
    (segments_dir / "seg_001.mp4").write_bytes(b"fake")

    doit_db = cache / ".doit.db"
    doit_db.write_text("{}")
    doit_bak = cache / ".doit.db.bak"
    doit_bak.write_text("{}")

    files: dict[str, Path] = {
        "module_dir": module_dir,
        "doit_db": doit_db,
        "doit_bak": doit_bak,
    }

    # Piper audio (current utterances)
    piper_key = "piper:en_US-lessac-medium:None"
    for i, text in enumerate(["Welcome to the first slide.", "This is the second slide."]):
        name = audio_filename(text, "piper", piper_key)
        path = audio / name
        path.write_bytes(b"piper-audio")
        files[f"piper_current_{i}"] = path

    # ElevenLabs audio (current utterance — same text, different engine)
    el_key = "elevenlabs:voice:model:0.5:0.75"
    el_name = audio_filename("Welcome to the first slide.", "elevenlabs", el_key)
    el_path = audio / el_name
    el_path.write_bytes(b"elevenlabs-audio")
    files["elevenlabs_current"] = el_path

    # Orphaned piper audio (text no longer in slides)
    orphan_piper = audio_filename("Old text that was removed.", "piper", piper_key)
    orphan_piper_path = audio / orphan_piper
    orphan_piper_path.write_bytes(b"orphan-piper")
    files["orphan_piper"] = orphan_piper_path

    # Orphaned elevenlabs audio
    orphan_el = audio_filename("Old text that was removed.", "elevenlabs", el_key)
    orphan_el_path = audio / orphan_el
    orphan_el_path.write_bytes(b"orphan-el")
    files["orphan_elevenlabs"] = orphan_el_path

    # Stale-config piper audio (current text but different piper model)
    stale_key = "piper:en_US-joe-medium:0"
    stale_name = audio_filename("Welcome to the first slide.", "piper", stale_key)
    stale_path = audio / stale_name
    stale_path.write_bytes(b"stale-piper")
    files["stale_piper"] = stale_path

    # Old-format audio (plain hash.wav — from before the naming change)
    old_format = audio / "abcdef1234567890.wav"
    old_format.write_bytes(b"old-format")
    files["old_format"] = old_format

    # Concat audio
    concat = audio / "abcdef1234567890_concat.wav"
    concat.write_bytes(b"concat")
    files["concat"] = concat

    return files


class TestCleanNothing:
    def test_removes_entire_cache(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        _populate_cache(tmp_path)
        cache = tmp_path / "cache"
        assert cache.exists()

        clean(playlist, keep="nothing")

        assert not cache.exists()

    def test_no_cache_is_noop(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        # No cache dir — should not raise
        clean(playlist, keep="nothing")


class TestCleanKeepApi:
    def test_removes_build_artifacts(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="api")

        assert not files["module_dir"].exists()
        assert not files["doit_db"].exists()
        assert not files["doit_bak"].exists()

    def test_removes_piper_audio(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="api")

        assert not files["piper_current_0"].exists()
        assert not files["piper_current_1"].exists()
        assert not files["orphan_piper"].exists()
        assert not files["stale_piper"].exists()

    def test_keeps_elevenlabs_audio(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="api")

        assert files["elevenlabs_current"].exists()
        assert files["orphan_elevenlabs"].exists()

    def test_removes_old_format_and_concat(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="api")

        assert not files["old_format"].exists()
        assert not files["concat"].exists()


class TestCleanKeepUtterances:
    def test_removes_build_artifacts(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="current")

        assert not files["module_dir"].exists()
        assert not files["doit_db"].exists()

    def test_keeps_current_utterance_audio_any_backend(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="current")

        assert files["piper_current_0"].exists()
        assert files["piper_current_1"].exists()
        assert files["elevenlabs_current"].exists()

    def test_removes_orphaned_audio(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="current")

        assert not files["orphan_piper"].exists()
        assert not files["orphan_elevenlabs"].exists()

    def test_keeps_stale_config_if_text_matches(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="current")

        # Stale config but same text → text_hash matches → kept
        assert files["stale_piper"].exists()

    def test_removes_old_format_and_concat(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="current")

        assert not files["old_format"].exists()
        assert not files["concat"].exists()


class TestCleanKeepExact:
    def test_removes_build_artifacts(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="exact")

        assert not files["module_dir"].exists()
        assert not files["doit_db"].exists()

    def test_keeps_exact_match_only(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="exact")

        # Current piper config matches → kept
        assert files["piper_current_0"].exists()
        assert files["piper_current_1"].exists()

    def test_removes_orphaned_audio(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="exact")

        assert not files["orphan_piper"].exists()
        assert not files["orphan_elevenlabs"].exists()

    def test_removes_stale_config_audio(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="exact")

        # Same text but different piper model → removed
        assert not files["stale_piper"].exists()

    def test_removes_different_backend_audio(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="exact")

        # ElevenLabs audio for current text — but config is piper → removed
        assert not files["elevenlabs_current"].exists()

    def test_removes_old_format_and_concat(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist, keep="exact")

        assert not files["old_format"].exists()
        assert not files["concat"].exists()


class TestCleanEdgeCases:
    def test_empty_cache(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        cache = tmp_path / "cache"
        cache.mkdir()

        clean(playlist, keep="api")
        assert cache.exists()  # empty cache dir not removed by api level

    def test_no_cache_dir(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        # Should not raise for any level
        for level in ("nothing", "api", "current", "exact"):
            clean(playlist, keep=level)  # type: ignore[arg-type]

    def test_default_keep_is_api(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        files = _populate_cache(tmp_path)

        clean(playlist)  # default

        assert files["elevenlabs_current"].exists()
        assert not files["piper_current_0"].exists()

    def test_audio_dir_removed_when_empty(self, tmp_path: Path) -> None:
        playlist = _create_playlist(tmp_path)
        cache = tmp_path / "cache"
        cache.mkdir()
        audio = cache / "audio"
        audio.mkdir()
        # Only old-format files — all will be removed
        (audio / "deadbeef12345678.wav").write_bytes(b"old")

        clean(playlist, keep="api")

        assert not audio.exists()
