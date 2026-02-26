"""Tests for doit task generation."""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.config import load_config
from slidesonnet.models import ModuleType, ProjectConfig, VideoConfig
from slidesonnet.playlist import parse_playlist
from slidesonnet.actions import (
    action_assemble,
    action_compose_narrated,
    action_compose_silent,
    action_concat,
    action_extract_images,
    action_passthrough,
    action_tts,
    get_parser_and_extractor,
)
from slidesonnet.tasks import generate_tasks
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


def test_unknown_voice_warns(tmp_path, caplog):
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
    assert "unknown voice 'nonexistent'" in caplog.text

    # Task still generated
    tts_tasks = [t for t in tasks if t["name"].split(":")[0] == "tts"]
    assert len(tts_tasks) == 1


# ---- Mocked unit tests for action functions and helpers ----


class TestActionPassthrough:
    """Tests for action_passthrough()."""

    def test_copies_file(self, tmp_path: Path) -> None:
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video-data")
        out = tmp_path / "build" / "module.mp4"

        action_passthrough(src, out)

        assert out.exists()
        assert out.read_bytes() == b"video-data"

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        src = tmp_path / "input.mp4"
        src.write_bytes(b"data")
        out = tmp_path / "deep" / "nested" / "out.mp4"

        action_passthrough(src, out)

        assert out.parent.exists()
        assert out.exists()


class TestActionTTS:
    """Tests for action_tts()."""

    def test_synthesizes(self, tmp_path: Path) -> None:
        cached = tmp_path / "audio" / "abc123.wav"
        utterance = tmp_path / "utterances" / "slide_001.txt"
        mock_tts = MagicMock()

        action_tts("Hello", cached, mock_tts, utterance)

        mock_tts.synthesize.assert_called_once_with("Hello", cached, voice=None)

    def test_passes_voice(self, tmp_path: Path) -> None:
        cached = tmp_path / "audio" / "abc123.wav"
        utterance = tmp_path / "utterances" / "slide_001.txt"
        mock_tts = MagicMock()

        action_tts("Hello", cached, mock_tts, utterance, voice="alice")

        mock_tts.synthesize.assert_called_once_with("Hello", cached, voice="alice")

    def test_writes_utterance_file(self, tmp_path: Path) -> None:
        cached = tmp_path / "audio" / "abc123.wav"
        utterance = tmp_path / "utterances" / "slide_001.txt"
        mock_tts = MagicMock()

        action_tts("Some narration text", cached, mock_tts, utterance)

        assert utterance.exists()
        assert utterance.read_text() == "Some narration text"


class TestActionExtractImages:
    """Tests for action_extract_images()."""

    def test_writes_manifest(self, tmp_path: Path) -> None:
        source = tmp_path / "slides.md"
        source.write_text("dummy")
        slides_dir = tmp_path / "slides"
        manifest = tmp_path / "slides" / "manifest.json"

        fake_images = [slides_dir / "slide.001.png", slides_dir / "slide.002.png"]

        def mock_extract(src: Path, out_dir: Path) -> list[Path]:
            out_dir.mkdir(parents=True, exist_ok=True)
            for img in fake_images:
                img.touch()
            return fake_images

        action_extract_images(source, slides_dir, mock_extract, manifest)

        assert manifest.exists()
        import json

        paths = json.loads(manifest.read_text())
        assert len(paths) == 2
        assert all("slide" in p for p in paths)

    def test_creates_slides_dir(self, tmp_path: Path) -> None:
        source = tmp_path / "slides.md"
        source.write_text("dummy")
        slides_dir = tmp_path / "deep" / "nested" / "slides"
        manifest = slides_dir / "manifest.json"

        def mock_extract(src: Path, out_dir: Path) -> list[Path]:
            return []

        action_extract_images(source, slides_dir, mock_extract, manifest)

        assert slides_dir.exists()
        assert manifest.exists()

    def test_passes_source_and_dir_to_extract_fn(self, tmp_path: Path) -> None:
        source = tmp_path / "slides.md"
        source.write_text("dummy")
        slides_dir = tmp_path / "slides"
        manifest = tmp_path / "slides" / "manifest.json"
        mock_fn = MagicMock(return_value=[])

        action_extract_images(source, slides_dir, mock_fn, manifest)

        mock_fn.assert_called_once_with(source, slides_dir)


class TestActionComposeNarrated:
    """Tests for action_compose_narrated()."""

    def _setup_manifest(self, tmp_path: Path) -> Path:
        import json

        slides_dir = tmp_path / "slides"
        slides_dir.mkdir(parents=True)
        images = [str(slides_dir / "slide.001.png"), str(slides_dir / "slide.002.png")]
        for img in images:
            Path(img).touch()
        manifest = slides_dir / "manifest.json"
        manifest.write_text(json.dumps(images))
        return manifest

    @patch("slidesonnet.actions.composer.get_duration", return_value=5.0)
    @patch("slidesonnet.actions.composer.compose_segment")
    def test_calls_compose_segment(
        self, mock_compose: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        manifest = self._setup_manifest(tmp_path)
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")
        output = tmp_path / "seg.mp4"
        config = ProjectConfig()

        action_compose_narrated(manifest, 1, audio, output, config)

        mock_dur.assert_called_once_with(audio)
        mock_compose.assert_called_once_with(
            image=Path(tmp_path / "slides" / "slide.001.png"),
            audio=audio,
            output=output,
            duration=5.0,
            pad_seconds=config.video.pad_seconds,
            pre_silence=config.video.pre_silence,
            resolution=config.video.resolution,
            fps=config.video.fps,
            crf=config.video.crf,
        )

    @patch("slidesonnet.actions.composer.get_duration", return_value=3.0)
    @patch("slidesonnet.actions.composer.compose_segment")
    def test_selects_correct_image_by_index(
        self, mock_compose: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        manifest = self._setup_manifest(tmp_path)
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")
        output = tmp_path / "seg.mp4"

        action_compose_narrated(manifest, 2, audio, output, ProjectConfig())

        called_image = mock_compose.call_args[1]["image"]
        assert called_image == Path(tmp_path / "slides" / "slide.002.png")


class TestActionComposeSilent:
    """Tests for action_compose_silent()."""

    def _setup_manifest(self, tmp_path: Path) -> Path:
        import json

        slides_dir = tmp_path / "slides"
        slides_dir.mkdir(parents=True)
        images = [str(slides_dir / "slide.001.png"), str(slides_dir / "slide.002.png")]
        for img in images:
            Path(img).touch()
        manifest = slides_dir / "manifest.json"
        manifest.write_text(json.dumps(images))
        return manifest

    @patch("slidesonnet.actions.composer.compose_silent_segment")
    def test_calls_compose_silent_segment(self, mock_compose: MagicMock, tmp_path: Path) -> None:
        manifest = self._setup_manifest(tmp_path)
        output = tmp_path / "seg.mp4"
        config = ProjectConfig()

        action_compose_silent(manifest, 1, output, config)

        mock_compose.assert_called_once_with(
            image=Path(tmp_path / "slides" / "slide.001.png"),
            output=output,
            duration=config.video.silence_duration,
            resolution=config.video.resolution,
            fps=config.video.fps,
            crf=config.video.crf,
        )

    @patch("slidesonnet.actions.composer.compose_silent_segment")
    def test_selects_correct_image_by_index(self, mock_compose: MagicMock, tmp_path: Path) -> None:
        manifest = self._setup_manifest(tmp_path)
        output = tmp_path / "seg.mp4"

        action_compose_silent(manifest, 2, output, ProjectConfig())

        called_image = mock_compose.call_args[1]["image"]
        assert called_image == Path(tmp_path / "slides" / "slide.002.png")


class TestActionConcat:
    """Tests for action_concat()."""

    def _config(self, crossfade: float = 0.0) -> ProjectConfig:
        return ProjectConfig(video=VideoConfig(crossfade=crossfade))

    def test_single_segment_copies(self, tmp_path: Path) -> None:
        seg = tmp_path / "seg.mp4"
        seg.write_bytes(b"segment-data")
        out = tmp_path / "out" / "module.mp4"

        action_concat([seg], out, self._config())

        assert out.read_bytes() == b"segment-data"

    @patch("slidesonnet.actions.composer.concatenate_segments")
    def test_multiple_segments_concatenates(self, mock_concat: MagicMock, tmp_path: Path) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = tmp_path / "module.mp4"

        action_concat(segs, out, self._config(crossfade=0.0))

        mock_concat.assert_called_once_with(segs, out)

    def test_empty_segments_raises(self, tmp_path: Path) -> None:
        out = tmp_path / "module.mp4"

        with pytest.raises(RuntimeError, match="No segments"):
            action_concat([], out, self._config())

    @patch("slidesonnet.actions.composer.concatenate_segments_xfade")
    def test_crossfade_dispatches_xfade(self, mock_xfade: MagicMock, tmp_path: Path) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = tmp_path / "module.mp4"
        cfg = self._config(crossfade=0.5)

        action_concat(segs, out, cfg)

        mock_xfade.assert_called_once_with(segs, out, crossfade=0.5, crf=23)

    @patch("slidesonnet.actions.composer.concatenate_segments")
    def test_zero_crossfade_uses_concat(self, mock_concat: MagicMock, tmp_path: Path) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = tmp_path / "module.mp4"

        action_concat(segs, out, self._config(crossfade=0.0))

        mock_concat.assert_called_once_with(segs, out)


class TestActionAssemble:
    """Tests for action_assemble()."""

    def _config(self, crossfade: float = 0.0) -> ProjectConfig:
        return ProjectConfig(video=VideoConfig(crossfade=crossfade))

    def test_single_module_copies(self, tmp_path: Path) -> None:
        mod = tmp_path / "module.mp4"
        mod.write_bytes(b"module-data")
        out = tmp_path / "out" / "final.mp4"

        action_assemble([mod], out, self._config())

        assert out.read_bytes() == b"module-data"

    @patch("slidesonnet.actions.composer.concatenate_segments")
    def test_multiple_modules_concatenates(self, mock_concat: MagicMock, tmp_path: Path) -> None:
        mods = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = tmp_path / "final.mp4"

        action_assemble(mods, out, self._config(crossfade=0.0))

        mock_concat.assert_called_once_with(mods, out)

    @patch("slidesonnet.actions.composer.concatenate_segments_xfade")
    def test_crossfade_dispatches_xfade(self, mock_xfade: MagicMock, tmp_path: Path) -> None:
        mods = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = tmp_path / "final.mp4"
        cfg = self._config(crossfade=0.8)

        action_assemble(mods, out, cfg)

        mock_xfade.assert_called_once_with(mods, out, crossfade=0.8, crf=23)

    def test_empty_modules_raises(self, tmp_path: Path) -> None:
        out = tmp_path / "final.mp4"

        with pytest.raises(RuntimeError, match="No module videos"):
            action_assemble([], out, self._config())


def test_mixed_type_playlist(tmp_path):
    """Mixed-type playlist (MARP + Beamer + video) generates correct task graph."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(
        textwrap.dedent("""\
        ---
        title: Mixed Lecture
        video:
          resolution: 640x480
        ---

        1. [Intro](01-intro/slides.md)
        2. [Animation](animations/clip.mp4)
        3. [Theory](02-theory/slides.tex)
    """)
    )

    # MARP module: 2 slides (1 narrated, 1 silent)
    marp_dir = tmp_path / "01-intro"
    marp_dir.mkdir()
    (marp_dir / "slides.md").write_text(
        textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide One

        <!-- say: Welcome to the intro. -->

        ---

        # Slide Two

        <!-- silent -->
    """)
    )

    # Video passthrough
    anim_dir = tmp_path / "animations"
    anim_dir.mkdir()
    (anim_dir / "clip.mp4").write_bytes(b"fake-video")

    # Beamer module: 2 frames (1 narrated, 1 silent)
    beamer_dir = tmp_path / "02-theory"
    beamer_dir.mkdir()
    (beamer_dir / "slides.tex").write_text(
        textwrap.dedent(r"""
        \documentclass{beamer}
        \begin{document}

        \begin{frame}
        \frametitle{Frame One}
        \say{This is the theory section.}
        \end{frame}

        \begin{frame}
        \frametitle{Frame Two}
        \silent
        \end{frame}

        \end{document}
    """).lstrip()
    )

    tasks = _generate(tmp_path, playlist)
    task_names = [t["name"] for t in tasks]

    # Module names follow "{i:02d}_{path.stem}" pattern:
    #   01-intro/slides.md  → "01_slides"
    #   animations/clip.mp4 → "02_clip"
    #   02-theory/slides.tex → "03_slides"
    # Use the sequence prefix to distinguish modules with the same stem.

    # -- Module 1 (MARP): extract_images, tts, compose, concat --
    assert "extract_images:01_slides" in task_names
    marp_tts = [n for n in task_names if n.startswith("tts:01_slides")]
    assert len(marp_tts) == 1  # only slide 1 is narrated
    marp_compose = [n for n in task_names if n.startswith("compose:01_slides")]
    assert len(marp_compose) == 2  # narrated + silent (not skipped)
    assert "concat:01_slides" in task_names

    # -- Module 2 (video): passthrough only, no parse/tts/compose --
    passthrough = [n for n in task_names if n.startswith("passthrough:")]
    assert len(passthrough) == 1
    assert passthrough[0] == "passthrough:02_clip"
    assert not any(
        n.startswith(("extract_images:02_", "tts:02_", "compose:02_")) for n in task_names
    )

    # -- Module 3 (Beamer): extract_images, tts, compose, concat --
    assert "extract_images:03_slides" in task_names
    beamer_tts = [n for n in task_names if n.startswith("tts:03_slides")]
    assert len(beamer_tts) == 1  # only frame 1 is narrated
    beamer_compose = [n for n in task_names if n.startswith("compose:03_slides")]
    assert len(beamer_compose) == 2  # narrated + silent
    assert "concat:03_slides" in task_names

    # -- Final assemble depends on all 3 module videos --
    assemble = [t for t in tasks if t["name"] == "assemble"]
    assert len(assemble) == 1
    assert len(assemble[0]["file_dep"]) == 3


class TestGetParserAndExtractor:
    """Tests for get_parser_and_extractor()."""

    def test_marp(self) -> None:
        from slidesonnet.parsers.marp import MarpParser
        from slidesonnet.parsers.marp import extract_images as marp_extract

        cls, fn = get_parser_and_extractor(ModuleType.MARP)
        assert cls is MarpParser
        assert fn is marp_extract

    def test_beamer(self) -> None:
        from slidesonnet.parsers.beamer import BeamerParser
        from slidesonnet.parsers.beamer import extract_images as beamer_extract

        cls, fn = get_parser_and_extractor(ModuleType.BEAMER)
        assert cls is BeamerParser
        assert fn is beamer_extract

    def test_video_raises(self) -> None:
        with pytest.raises(ValueError, match="No parser"):
            get_parser_and_extractor(ModuleType.VIDEO)
