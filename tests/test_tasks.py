"""Tests for doit task generation."""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.config import load_config
from slidesonnet.models import ModuleType, ProjectConfig, VideoConfig
from slidesonnet.playlist import parse_playlist
from slidesonnet.tasks import (
    _action_assemble,
    _action_concat,
    _action_passthrough,
    _action_tts,
    _get_parser_and_extractor,
    generate_tasks,
)
from slidesonnet.tts.base import TTSEngine


class MockTTS(TTSEngine):
    def synthesize(self, text, output_path, voice=None):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-audio")
        return 1.0

    def name(self):
        return "mock"


def _setup_project(tmp_path):
    """Create a minimal project with playlist + slides."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(
        textwrap.dedent("""\
        ---
        title: Test Lecture
        tts:
          backend: piper
        video:
          resolution: 640x480
          pad_seconds: 0.2
          silence_duration: 1.0
        ---

        1. [Intro](01-intro/slides.md)
    """)
    )

    slides_dir = tmp_path / "01-intro"
    slides_dir.mkdir()
    (slides_dir / "slides.md").write_text(
        textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide One

        <!-- say: Welcome to the first slide. -->

        ---

        # Slide Two

        <!-- say: This is the second slide. -->

        ---

        # Silent Slide

        <!-- silent -->
    """)
    )

    return playlist


def _generate(tmp_path, playlist):
    """Parse playlist and generate tasks."""
    raw_config, entries = parse_playlist(playlist)
    config = load_config(raw_config, tmp_path)
    config.pronunciation = {}
    tts = MockTTS()
    build_dir = tmp_path / ".build"
    build_dir.mkdir()
    output_path = build_dir / "lecture.mp4"

    tasks = generate_tasks(
        entries=entries,
        config=config,
        tts=tts,
        build_dir=build_dir,
        playlist_dir=tmp_path,
        output_path=output_path,
    )
    return tasks


def test_generates_correct_task_types(tmp_path):
    """Task generation produces the right task types."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    basenames = [t["name"].split(":")[0] for t in tasks]
    assert "extract_images" in basenames
    assert "tts" in basenames
    assert "compose" in basenames
    assert "concat" in basenames
    assert "assemble" in basenames


def test_tts_tasks_per_narrated_slide(tmp_path):
    """One TTS task per narrated slide, none for silent."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    tts_tasks = [t for t in tasks if t["name"].split(":")[0] == "tts"]
    assert len(tts_tasks) == 2  # slides 1 and 2 have <!-- say: -->


def test_compose_tasks_skip_skipped_slides(tmp_path):
    """Compose tasks skip slides with <!-- skip -->."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(
        textwrap.dedent("""\
        ---
        title: Test
        ---

        1. [Intro](01-intro/slides.md)
    """)
    )

    slides_dir = tmp_path / "01-intro"
    slides_dir.mkdir()
    (slides_dir / "slides.md").write_text(
        textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide One

        <!-- say: Hello. -->

        ---

        # Hidden

        <!-- skip -->

        ---

        # Visible

        <!-- silent -->
    """)
    )

    tasks = _generate(tmp_path, playlist)
    compose_tasks = [t for t in tasks if t["name"].split(":")[0] == "compose"]
    # Slide 1 (narrated) and slide 3 (silent) compose, slide 2 (skip) doesn't
    assert len(compose_tasks) == 2


def test_content_addressed_audio_targets(tmp_path):
    """TTS targets use content-addressed filenames."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    tts_tasks = [t for t in tasks if t["name"].split(":")[0] == "tts"]
    targets = [t["targets"][0] for t in tts_tasks]

    # Targets should be in audio/ dir with hash-based names
    for target in targets:
        assert "audio" in target
        assert target.endswith(".wav")

    # Different text → different targets
    assert targets[0] != targets[1]


def test_task_dependencies(tmp_path):
    """Compose tasks depend on extract_images and tts."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    compose_tasks = [t for t in tasks if t["name"].split(":")[0] == "compose"]
    for ct in compose_tasks:
        # All compose tasks depend on extract_images
        assert any("extract_images" in dep for dep in ct.get("task_dep", []))

    # Narrated compose tasks also depend on tts
    narrated = [ct for ct in compose_tasks if any("tts" in dep for dep in ct.get("task_dep", []))]
    assert len(narrated) == 2  # 2 narrated slides


def test_video_passthrough_task(tmp_path):
    """Video modules create passthrough tasks."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(
        textwrap.dedent("""\
        ---
        title: Test
        ---

        1. [Clip](animations/clip.mp4)
    """)
    )

    anim_dir = tmp_path / "animations"
    anim_dir.mkdir()
    (anim_dir / "clip.mp4").write_bytes(b"fake-video")

    tasks = _generate(tmp_path, playlist)

    passthrough = [t for t in tasks if t["name"].split(":")[0] == "passthrough"]
    assert len(passthrough) == 1
    assert str(anim_dir / "clip.mp4") in passthrough[0]["file_dep"]


def test_uptodate_uses_text_content(tmp_path):
    """TTS uptodate checks are based on narration text content."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    tts_tasks = [t for t in tasks if t["name"].split(":")[0] == "tts"]
    for t in tts_tasks:
        assert "uptodate" in t
        assert len(t["uptodate"]) > 0


def test_concat_depends_on_segments(tmp_path):
    """Module concat task depends on all segment files."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    concat_tasks = [t for t in tasks if t["name"].split(":")[0] == "concat"]
    assert len(concat_tasks) == 1

    # Should depend on segment files (3 slides - 0 skips = 3 segments)
    # Slides: say, say, silent → 3 compose tasks → 3 segments
    assert len(concat_tasks[0]["file_dep"]) == 3


def test_assemble_depends_on_modules(tmp_path):
    """Final assembly depends on module videos."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    assemble = [t for t in tasks if t["name"].split(":")[0] == "assemble"]
    assert len(assemble) == 1
    assert len(assemble[0]["file_dep"]) == 1  # 1 module


def test_voice_preset_changes_cache_key(tmp_path):
    """Same text with different voice presets produces different audio targets."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(
        textwrap.dedent("""\
        ---
        title: Test
        voices:
          alice: en_US-amy-medium
          bob: en_US-joe-medium
        ---

        1. [Intro](01-intro/slides.md)
    """)
    )

    slides_dir = tmp_path / "01-intro"
    slides_dir.mkdir()
    (slides_dir / "slides.md").write_text(
        textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide One

        <!-- say(voice=alice): Same text for both slides. -->

        ---

        # Slide Two

        <!-- say(voice=bob): Same text for both slides. -->
    """)
    )

    tasks = _generate(tmp_path, playlist)
    tts_tasks = [t for t in tasks if t["name"].split(":")[0] == "tts"]
    assert len(tts_tasks) == 2

    # Different voice → different cache targets
    assert tts_tasks[0]["targets"] != tts_tasks[1]["targets"]


def test_unknown_voice_warns(tmp_path, capsys):
    """Unknown voice preset emits a warning but still generates tasks."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(
        textwrap.dedent("""\
        ---
        title: Test
        ---

        1. [Intro](01-intro/slides.md)
    """)
    )

    slides_dir = tmp_path / "01-intro"
    slides_dir.mkdir()
    (slides_dir / "slides.md").write_text(
        textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide One

        <!-- say(voice=nonexistent): Hello world. -->
    """)
    )

    tasks = _generate(tmp_path, playlist)
    captured = capsys.readouterr()
    assert "unknown voice 'nonexistent'" in captured.err

    # Task still generated
    tts_tasks = [t for t in tasks if t["name"].split(":")[0] == "tts"]
    assert len(tts_tasks) == 1


# ---- Mocked unit tests for action functions and helpers ----


class TestActionPassthrough:
    """Tests for _action_passthrough()."""

    def test_copies_file(self, tmp_path: Path) -> None:
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video-data")
        out = tmp_path / "build" / "module.mp4"

        _action_passthrough(src, out)

        assert out.exists()
        assert out.read_bytes() == b"video-data"

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        src = tmp_path / "input.mp4"
        src.write_bytes(b"data")
        out = tmp_path / "deep" / "nested" / "out.mp4"

        _action_passthrough(src, out)

        assert out.parent.exists()
        assert out.exists()


class TestActionTTS:
    """Tests for _action_tts()."""

    def test_cache_hit_skips_synthesis(self, tmp_path: Path) -> None:
        cached = tmp_path / "audio" / "abc123.wav"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"cached-audio")
        utterance = tmp_path / "utterances" / "slide_001.txt"
        mock_tts = MagicMock()

        _action_tts("Hello", cached, mock_tts, utterance, force=False)

        mock_tts.synthesize.assert_not_called()
        assert utterance.read_text() == "Hello"

    def test_force_overrides_cache(self, tmp_path: Path) -> None:
        cached = tmp_path / "audio" / "abc123.wav"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"cached-audio")
        utterance = tmp_path / "utterances" / "slide_001.txt"
        mock_tts = MagicMock()

        _action_tts("Hello", cached, mock_tts, utterance, force=True)

        mock_tts.synthesize.assert_called_once_with("Hello", cached, voice=None)

    def test_synthesizes_when_no_cache(self, tmp_path: Path) -> None:
        cached = tmp_path / "audio" / "abc123.wav"
        utterance = tmp_path / "utterances" / "slide_001.txt"
        mock_tts = MagicMock()

        _action_tts("Hello", cached, mock_tts, utterance, force=False)

        mock_tts.synthesize.assert_called_once_with("Hello", cached, voice=None)

    def test_passes_voice(self, tmp_path: Path) -> None:
        cached = tmp_path / "audio" / "abc123.wav"
        utterance = tmp_path / "utterances" / "slide_001.txt"
        mock_tts = MagicMock()

        _action_tts("Hello", cached, mock_tts, utterance, force=False, voice="alice")

        mock_tts.synthesize.assert_called_once_with("Hello", cached, voice="alice")

    def test_writes_utterance_file(self, tmp_path: Path) -> None:
        cached = tmp_path / "audio" / "abc123.wav"
        utterance = tmp_path / "utterances" / "slide_001.txt"
        mock_tts = MagicMock()

        _action_tts("Some narration text", cached, mock_tts, utterance, force=False)

        assert utterance.exists()
        assert utterance.read_text() == "Some narration text"


class TestActionConcat:
    """Tests for _action_concat()."""

    def _config(self, crossfade: float = 0.0) -> ProjectConfig:
        return ProjectConfig(video=VideoConfig(crossfade=crossfade))

    def test_single_segment_copies(self, tmp_path: Path) -> None:
        seg = tmp_path / "seg.mp4"
        seg.write_bytes(b"segment-data")
        out = tmp_path / "out" / "module.mp4"

        _action_concat([seg], out, self._config())

        assert out.read_bytes() == b"segment-data"

    @patch("slidesonnet.tasks.composer.concatenate_segments")
    def test_multiple_segments_concatenates(self, mock_concat: MagicMock, tmp_path: Path) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = tmp_path / "module.mp4"

        _action_concat(segs, out, self._config(crossfade=0.0))

        mock_concat.assert_called_once_with(segs, out)

    @patch("slidesonnet.tasks.composer.concatenate_segments")
    def test_empty_segments_noop(self, mock_concat: MagicMock, tmp_path: Path) -> None:
        out = tmp_path / "module.mp4"

        _action_concat([], out, self._config())

        mock_concat.assert_not_called()
        assert not out.exists()

    @patch("slidesonnet.tasks.composer.concatenate_segments_xfade")
    def test_crossfade_dispatches_xfade(self, mock_xfade: MagicMock, tmp_path: Path) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = tmp_path / "module.mp4"
        cfg = self._config(crossfade=0.5)

        _action_concat(segs, out, cfg)

        mock_xfade.assert_called_once_with(segs, out, crossfade=0.5, crf=23)

    @patch("slidesonnet.tasks.composer.concatenate_segments")
    def test_zero_crossfade_uses_concat(self, mock_concat: MagicMock, tmp_path: Path) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = tmp_path / "module.mp4"

        _action_concat(segs, out, self._config(crossfade=0.0))

        mock_concat.assert_called_once_with(segs, out)


class TestActionAssemble:
    """Tests for _action_assemble()."""

    def _config(self, crossfade: float = 0.0) -> ProjectConfig:
        return ProjectConfig(video=VideoConfig(crossfade=crossfade))

    def test_single_module_copies(self, tmp_path: Path) -> None:
        mod = tmp_path / "module.mp4"
        mod.write_bytes(b"module-data")
        out = tmp_path / "out" / "final.mp4"

        _action_assemble([mod], out, self._config())

        assert out.read_bytes() == b"module-data"

    @patch("slidesonnet.tasks.composer.concatenate_segments")
    def test_multiple_modules_concatenates(self, mock_concat: MagicMock, tmp_path: Path) -> None:
        mods = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = tmp_path / "final.mp4"

        _action_assemble(mods, out, self._config(crossfade=0.0))

        mock_concat.assert_called_once_with(mods, out)

    @patch("slidesonnet.tasks.composer.concatenate_segments_xfade")
    def test_crossfade_dispatches_xfade(self, mock_xfade: MagicMock, tmp_path: Path) -> None:
        mods = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = tmp_path / "final.mp4"
        cfg = self._config(crossfade=0.8)

        _action_assemble(mods, out, cfg)

        mock_xfade.assert_called_once_with(mods, out, crossfade=0.8, crf=23)


class TestGetParserAndExtractor:
    """Tests for _get_parser_and_extractor()."""

    def test_marp(self) -> None:
        from slidesonnet.parsers.marp import MarpParser
        from slidesonnet.parsers.marp import extract_images as marp_extract

        cls, fn = _get_parser_and_extractor(ModuleType.MARP)
        assert cls is MarpParser
        assert fn is marp_extract

    def test_beamer(self) -> None:
        from slidesonnet.parsers.beamer import BeamerParser
        from slidesonnet.parsers.beamer import extract_images as beamer_extract

        cls, fn = _get_parser_and_extractor(ModuleType.BEAMER)
        assert cls is BeamerParser
        assert fn is beamer_extract

    def test_video_raises(self) -> None:
        with pytest.raises(ValueError, match="No parser"):
            _get_parser_and_extractor(ModuleType.VIDEO)
