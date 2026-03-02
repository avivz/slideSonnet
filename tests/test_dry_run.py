"""Tests for the --dry-run feature."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from slidesonnet.hashing import audio_path as _audio_path
from slidesonnet.pipeline import DryRunResult, dry_run


def _setup_project(
    tmp_path: Path,
    slides_text: str | None = None,
    backend: str = "piper",
) -> Path:
    """Create a minimal project with playlist + MARP slides."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(
        textwrap.dedent(f"""\
        ---
        title: Test Lecture
        tts:
          backend: {backend}
          piper:
            model: en_US-lessac-medium
        video:
          resolution: 640x480
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

        <!-- say: This is the second slide with more content. -->

        ---

        # Silent Slide

        <!-- nonarration -->
    """)
    (slides_dir / "slides.md").write_text(slides_text)

    return playlist


class TestDryRunAllUncached:
    """No cache dir → all slides need TTS."""

    def test_counts(self, tmp_path: Path) -> None:
        playlist = _setup_project(tmp_path)
        result = dry_run(playlist)

        assert result.total_narrated == 2
        assert result.cached == 0
        assert result.needs_tts == 2

    def test_character_count(self, tmp_path: Path) -> None:
        playlist = _setup_project(tmp_path)
        result = dry_run(playlist)

        # Characters should be the post-pronunciation text lengths
        expected = len("Welcome to the first slide.") + len(
            "This is the second slide with more content."
        )
        assert result.uncached_chars == expected


class TestDryRunAllCached:
    """Pre-populated cache → all cached."""

    def test_all_cached(self, tmp_path: Path) -> None:
        playlist = _setup_project(tmp_path)

        # Pre-populate cache with correctly-named files
        audio_dir = tmp_path / "cache" / "audio"
        audio_dir.mkdir(parents=True)

        from slidesonnet.tts.piper import PiperTTS

        tts = PiperTTS(model="en_US-lessac-medium")

        for text in [
            "Welcome to the first slide.",
            "This is the second slide with more content.",
        ]:
            p = _audio_path(audio_dir, text, tts.name(), tts.cache_key(), None)
            p.write_bytes(b"\x00" * 100)  # non-empty

        result = dry_run(playlist)

        assert result.total_narrated == 2
        assert result.cached == 2
        assert result.needs_tts == 0
        assert result.uncached_chars == 0


class TestDryRunPartialCache:
    """Some files cached, some not."""

    def test_partial(self, tmp_path: Path) -> None:
        playlist = _setup_project(tmp_path)

        audio_dir = tmp_path / "cache" / "audio"
        audio_dir.mkdir(parents=True)

        from slidesonnet.tts.piper import PiperTTS

        tts = PiperTTS(model="en_US-lessac-medium")

        # Cache only the first slide
        p = _audio_path(audio_dir, "Welcome to the first slide.", tts.name(), tts.cache_key(), None)
        p.write_bytes(b"\x00" * 100)

        result = dry_run(playlist)

        assert result.total_narrated == 2
        assert result.cached == 1
        assert result.needs_tts == 1
        assert result.uncached_chars == len("This is the second slide with more content.")


class TestDryRunMultiPart:
    """Multi-part slide with partial cache."""

    def test_multi_part_partial(self, tmp_path: Path) -> None:
        slides_text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide One

        <!-- say(1): First part of the narration. -->
        <!-- say(1): Second part of the narration. -->
    """)
        playlist = _setup_project(tmp_path, slides_text=slides_text)

        audio_dir = tmp_path / "cache" / "audio"
        audio_dir.mkdir(parents=True)

        from slidesonnet.tts.piper import PiperTTS

        tts = PiperTTS(model="en_US-lessac-medium")

        # Cache only the first part
        p = _audio_path(
            audio_dir,
            "First part of the narration.",
            tts.name(),
            tts.cache_key(),
            None,
        )
        p.write_bytes(b"\x00" * 100)

        result = dry_run(playlist)

        assert result.total_narrated == 1
        assert result.needs_tts == 1
        # Only count chars for the uncached part
        assert result.uncached_chars == len("Second part of the narration.")

    def test_multi_part_all_cached(self, tmp_path: Path) -> None:
        slides_text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide One

        <!-- say(1): First part. -->
        <!-- say(1): Second part. -->
    """)
        playlist = _setup_project(tmp_path, slides_text=slides_text)

        audio_dir = tmp_path / "cache" / "audio"
        audio_dir.mkdir(parents=True)

        from slidesonnet.tts.piper import PiperTTS

        tts = PiperTTS(model="en_US-lessac-medium")

        for text in ["First part.", "Second part."]:
            p = _audio_path(audio_dir, text, tts.name(), tts.cache_key(), None)
            p.write_bytes(b"\x00" * 100)

        result = dry_run(playlist)

        assert result.total_narrated == 1
        assert result.cached == 1
        assert result.needs_tts == 0
        assert result.uncached_chars == 0


class TestDryRunAlternateExtension:
    """.wav file when backend expects .mp3 → still cached."""

    def test_alternate_ext(self, tmp_path: Path) -> None:
        playlist = _setup_project(tmp_path, backend="elevenlabs")

        audio_dir = tmp_path / "cache" / "audio"
        audio_dir.mkdir(parents=True)

        # Compute the expected .mp3 path using the real ElevenLabs engine
        from slidesonnet.models import ProjectConfig, TTSConfig
        from slidesonnet.tts import create_tts

        config = ProjectConfig(tts=TTSConfig(backend="elevenlabs"))
        tts = create_tts(config)

        mp3_path = _audio_path(
            audio_dir, "Welcome to the first slide.", tts.name(), tts.cache_key(), None
        )
        assert mp3_path.suffix == ".mp3"

        # Write a .wav file with the same stem instead
        wav_path = mp3_path.with_suffix(".wav")
        wav_path.write_bytes(b"\x00" * 100)

        result = dry_run(playlist)

        # The first slide should be detected as cached via alternate extension
        assert result.cached >= 1


class TestDryRunSilentAndSkipSlides:
    """Silent and skip slides not counted in total_narrated."""

    def test_silent_skip_not_counted(self, tmp_path: Path) -> None:
        slides_text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Narrated

        <!-- say: Hello world. -->

        ---

        # Silent

        <!-- nonarration -->

        ---

        # Skipped

        <!-- skip -->
    """)
        playlist = _setup_project(tmp_path, slides_text=slides_text)
        result = dry_run(playlist)

        assert result.total_narrated == 1
        assert result.needs_tts == 1
        assert result.uncached_chars == len("Hello world.")


class TestDryRunNoDirsCreated:
    """dry_run() should not create the cache directory."""

    def test_no_cache_dir(self, tmp_path: Path) -> None:
        playlist = _setup_project(tmp_path)
        cache_dir = tmp_path / "cache"
        assert not cache_dir.exists()

        dry_run(playlist)

        assert not cache_dir.exists()


class TestDryRunBackend:
    """Backend is reported correctly."""

    def test_piper_backend(self, tmp_path: Path) -> None:
        playlist = _setup_project(tmp_path, backend="piper")
        result = dry_run(playlist)
        assert result.tts_backend == "piper"

    def test_elevenlabs_backend(self, tmp_path: Path) -> None:
        playlist = _setup_project(tmp_path, backend="elevenlabs")
        result = dry_run(playlist)
        assert result.tts_backend == "elevenlabs"

    def test_tts_override(self, tmp_path: Path) -> None:
        playlist = _setup_project(tmp_path, backend="piper")
        result = dry_run(playlist, tts_override="elevenlabs")
        assert result.tts_backend == "elevenlabs"


# ---- Integration tests (require marp-cli, piper, ffmpeg) ----


@pytest.mark.integration
class TestDryRunIntegrationShowcase:
    """Run dry_run() on the showcase example."""

    def test_showcase_dry_run(self) -> None:
        showcase = Path("examples/showcase/lecture.md")
        if not showcase.exists():
            pytest.skip("showcase example not found")

        result = dry_run(showcase, tts_override="piper")

        assert isinstance(result, DryRunResult)
        assert result.total_narrated > 0
        assert result.tts_backend == "piper"
        assert result.total_narrated == result.cached + result.needs_tts


@pytest.mark.integration
class TestDryRunIntegrationBuildThenDryRun:
    """Build with piper, then dry-run → all cached."""

    def test_build_then_dry_run_all_cached(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from slidesonnet.pipeline import build

        slides_text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Hello

        <!-- say: Hello world. -->
    """)
        playlist = _setup_project(tmp_path, slides_text=slides_text, backend="piper")

        # Build (uses real marp-cli + piper)
        with patch("slidesonnet.parsers.marp.export_pdf"):
            build(playlist, tts_override="piper")

        # Dry-run should show all cached
        result = dry_run(playlist, tts_override="piper")

        assert result.total_narrated == 1
        assert result.cached == 1
        assert result.needs_tts == 0


@pytest.mark.integration
class TestDryRunIntegrationEditSlide:
    """Build, edit narration, dry-run → 1 needs TTS."""

    def test_edit_then_dry_run(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from slidesonnet.pipeline import build

        slides_text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Hello

        <!-- say: Hello world. -->

        ---

        # Goodbye

        <!-- say: Goodbye world. -->
    """)
        playlist = _setup_project(tmp_path, slides_text=slides_text, backend="piper")

        with patch("slidesonnet.parsers.marp.export_pdf"):
            build(playlist, tts_override="piper")

        # Edit one slide
        slides_path = tmp_path / "01-intro" / "slides.md"
        text = slides_path.read_text()
        text = text.replace("Hello world.", "Hello universe.")
        slides_path.write_text(text)

        result = dry_run(playlist, tts_override="piper")

        assert result.total_narrated == 2
        assert result.cached == 1
        assert result.needs_tts == 1
        assert result.uncached_chars == len("Hello universe.")
