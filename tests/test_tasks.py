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
    action_compile_beamer,
    action_compose_narrated,
    action_compose_silent,
    action_concat_audio,
    action_export_pdf_beamer,
    action_export_pdf_marp,
    action_extract_images,
    action_extract_images_beamer,
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

    def cache_key(self):
        return "mock:default"


def _setup_project(tmp_path):
    """Create a minimal project with playlist + slides."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test Lecture
        tts:
          backend: piper
        video:
          resolution: 640x480
          pad_seconds: 0.2
          silence_duration: 1.0
        modules:
          - 01-intro/slides.md
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

        <!-- nonarration -->
    """)
    )

    return playlist


def _generate(tmp_path, playlist):
    """Parse playlist and generate tasks."""
    raw_config, entries = parse_playlist(playlist)
    config = load_config(raw_config, tmp_path)
    config.pronunciation = {}
    tts = MockTTS()
    build_dir = tmp_path / "cache"
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
    assert "export_pdf" in basenames
    assert "concat" not in basenames
    assert "assemble" in basenames


def test_tts_tasks_per_narrated_slide(tmp_path):
    """One TTS task per narrated slide, none for silent."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    tts_tasks = [t for t in tasks if t["name"].split(":")[0] == "tts"]
    assert len(tts_tasks) == 2  # slides 1 and 2 have <!-- say: -->


def test_compose_tasks_skip_skipped_slides(tmp_path):
    """Compose tasks skip slides with <!-- skip -->."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - 01-intro/slides.md
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

        <!-- nonarration -->
    """)
    )

    tasks = _generate(tmp_path, playlist)
    compose_tasks = [t for t in tasks if t["name"].split(":")[0] == "compose"]
    # Slide 1 (narrated) and slide 3 (silent) compose, slide 2 (skip) doesn't
    assert len(compose_tasks) == 2


def test_content_addressed_audio_targets(tmp_path):
    """TTS targets use content-addressed filenames in new format."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    tts_tasks = [t for t in tasks if t["name"].split(":")[0] == "tts"]
    targets = [t["targets"][0] for t in tts_tasks]

    # Targets should be in audio/ dir with new-format names: {text_hash}.{backend}.{config_hash}.wav
    for target in targets:
        assert "audio" in target
        assert target.endswith(".wav")
        filename = Path(target).name
        parts = filename[:-4].split(".")  # strip .wav, split on dots
        assert len(parts) == 3, f"Expected 3-part filename, got: {filename}"
        assert parts[1] == "mock"  # MockTTS.name() returns "mock"

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


def test_video_passthrough_in_assemble(tmp_path):
    """Video modules are referenced directly in assemble file_dep."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - animations/clip.mp4
    """)
    )

    anim_dir = tmp_path / "animations"
    anim_dir.mkdir()
    (anim_dir / "clip.mp4").write_bytes(b"fake-video")

    tasks = _generate(tmp_path, playlist)

    # No passthrough task
    passthrough = [t for t in tasks if t["name"].split(":")[0] == "passthrough"]
    assert len(passthrough) == 0

    # Assemble depends directly on the source video
    assemble = [t for t in tasks if t["name"] == "assemble"]
    assert len(assemble) == 1
    assert str(anim_dir / "clip.mp4") in assemble[0]["file_dep"]


def test_uptodate_uses_text_content(tmp_path):
    """TTS uptodate checks are based on narration text content."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    tts_tasks = [t for t in tasks if t["name"].split(":")[0] == "tts"]
    for t in tts_tasks:
        assert "uptodate" in t
        assert len(t["uptodate"]) > 0


def test_assemble_depends_on_segments(tmp_path):
    """Final assembly depends on all segment files directly."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    assemble = [t for t in tasks if t["name"] == "assemble"]
    assert len(assemble) == 1
    # 3 slides (say, say, silent) → 3 segments
    assert len(assemble[0]["file_dep"]) == 3


def test_voice_preset_changes_cache_key(tmp_path):
    """Same text with different voice presets produces different audio targets."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        tts:
          backend: piper
        voices:
          alice:
            piper: en_US-amy-medium
          bob:
            piper: en_US-joe-medium
        modules:
          - 01-intro/slides.md
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
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - 01-intro/slides.md
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


def test_missing_backend_mapping_warns(tmp_path, caplog):
    """Voice preset without mapping for active backend warns and falls back to default."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        tts:
          backend: piper
        voices:
          alice:
            elevenlabs: 21m00Tcm4TlvDq8ikWAM
        modules:
          - 01-intro/slides.md
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

        <!-- say(voice=alice): Hello world. -->
    """)
    )

    tasks = _generate(tmp_path, playlist)
    assert "no mapping for backend 'piper'" in caplog.text

    # TTS task still generated (with default voice = None)
    tts_tasks = [t for t in tasks if t["name"].split(":")[0] == "tts"]
    assert len(tts_tasks) == 1
    # The voice arg in the action should be None (fallback to default)
    action_args = tts_tasks[0]["actions"][0][1]
    assert action_args[4] is None  # voice parameter


def test_compose_uses_image_index_for_multi_say(tmp_path: Path) -> None:
    """Compose tasks use image_index (not index) for multi-say slides."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - 01-intro/slides.md
    """)
    )

    slides_dir = tmp_path / "01-intro"
    slides_dir.mkdir()
    # Slide 1: two says, no fragments → both narration entries share image 1
    # Slide 2: single say → uses image 2
    (slides_dir / "slides.md").write_text(
        textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide One

        <!-- say(voice=alice): First voice. -->

        <!-- say(voice=bob): Second voice. -->

        ---

        # Slide Two

        <!-- say: Third. -->
    """)
    )

    tasks = _generate(tmp_path, playlist)
    compose_tasks = [t for t in tasks if t["name"].split(":")[0] == "compose"]
    assert len(compose_tasks) == 3  # 2 narrated + 0 silent (from multi-say) + 1 narrated

    # Extract the slide_index arg passed to compose actions
    compose_image_indices = []
    for ct in compose_tasks:
        action_tuple = ct["actions"][0]
        # action_tuple is (fn, [manifest, slide_index, ...])
        args = action_tuple[1]
        compose_image_indices.append(args[1])  # slide_index arg

    # Both multi-say sub-slides should reference image 1, then slide 2 → image 2
    assert compose_image_indices == [1, 1, 2]


def test_multi_part_tts_generates_per_part_tasks(tmp_path: Path) -> None:
    """Multi-say same sub-slide generates per-part TTS tasks + concat_audio."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - 01-intro/slides.md
    """)
    )

    slides_dir = tmp_path / "01-intro"
    slides_dir.mkdir()
    # Two says targeting same sub-slide (explicit slide=1)
    (slides_dir / "slides.md").write_text(
        textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide One

        <!-- say(1): First part of narration. -->
        <!-- say(1): Second part of narration. -->
    """)
    )

    tasks = _generate(tmp_path, playlist)
    task_names = [t["name"] for t in tasks]

    # Should have per-part TTS tasks
    assert "tts:01_slides_slide_001_part_000" in task_names
    assert "tts:01_slides_slide_001_part_001" in task_names

    # Should have concat_audio task
    assert "concat_audio:01_slides_slide_001" in task_names

    # Should NOT have bare tts:01_slides_slide_001
    assert "tts:01_slides_slide_001" not in task_names

    # concat_audio depends on both part TTS tasks
    concat_task = next(t for t in tasks if t["name"] == "concat_audio:01_slides_slide_001")
    assert "tts:01_slides_slide_001_part_000" in concat_task["task_dep"]
    assert "tts:01_slides_slide_001_part_001" in concat_task["task_dep"]

    # Compose depends on concat_audio, not individual TTS tasks
    compose_task = next(t for t in tasks if t["name"].startswith("compose:01_slides_slide_001"))
    assert any("concat_audio" in dep for dep in compose_task["task_dep"])
    assert not any(dep.startswith("tts:") for dep in compose_task["task_dep"])


def test_single_say_no_concat_audio(tmp_path: Path) -> None:
    """Single say per sub-slide does NOT generate concat_audio tasks."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)
    task_names = [t["name"] for t in tasks]

    # No concat_audio tasks for single-say slides
    assert not any(n.startswith("concat_audio:") for n in task_names)

    # Regular tts tasks exist
    tts_tasks = [n for n in task_names if n.startswith("tts:")]
    assert len(tts_tasks) == 2
    # No "_part_" suffix
    assert all("_part_" not in n for n in tts_tasks)


def test_multi_part_tts_content_addressed(tmp_path: Path) -> None:
    """Each part gets its own content-addressed audio file."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - 01-intro/slides.md
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

        <!-- say(1): First part. -->
        <!-- say(1): Second part. -->
    """)
    )

    tasks = _generate(tmp_path, playlist)
    part_tts = [t for t in tasks if t["name"].startswith("tts:") and "_part_" in t["name"]]
    assert len(part_tts) == 2

    # Different text → different targets
    assert part_tts[0]["targets"] != part_tts[1]["targets"]

    # Both targets are in audio/ dir
    for t in part_tts:
        assert "audio" in t["targets"][0]
        assert t["targets"][0].endswith(".wav")


def test_multi_part_concat_target_is_content_addressed(tmp_path: Path) -> None:
    """concat_audio target uses hash-based filename ending in _concat.wav."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - 01-intro/slides.md
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

        <!-- say(1): First. -->
        <!-- say(1): Second. -->
    """)
    )

    tasks = _generate(tmp_path, playlist)
    concat_task = next(t for t in tasks if t["name"].startswith("concat_audio:"))
    assert concat_task["targets"][0].endswith("_concat.wav")
    assert "audio" in concat_task["targets"][0]


class TestActionConcatAudio:
    """Tests for action_concat_audio()."""

    @patch("slidesonnet.actions.composer.concatenate_audio")
    def test_calls_concatenate_audio(self, mock_concat: MagicMock, tmp_path: Path) -> None:
        paths = [tmp_path / "a.wav", tmp_path / "b.wav"]
        output = tmp_path / "out.wav"

        action_concat_audio(paths, output)

        mock_concat.assert_called_once_with(paths, output)

    @patch("slidesonnet.actions.composer.concatenate_audio")
    def test_creates_output_dir(self, mock_concat: MagicMock, tmp_path: Path) -> None:
        paths = [tmp_path / "a.wav"]
        output = tmp_path / "deep" / "nested" / "out.wav"

        action_concat_audio(paths, output)

        assert output.parent.exists()


# ---- Mocked unit tests for action functions and helpers ----


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
            preset=config.video.preset,
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
            preset=config.video.preset,
        )

    @patch("slidesonnet.actions.composer.compose_silent_segment")
    def test_selects_correct_image_by_index(self, mock_compose: MagicMock, tmp_path: Path) -> None:
        manifest = self._setup_manifest(tmp_path)
        output = tmp_path / "seg.mp4"

        action_compose_silent(manifest, 2, output, ProjectConfig())

        called_image = mock_compose.call_args[1]["image"]
        assert called_image == Path(tmp_path / "slides" / "slide.002.png")

    @patch("slidesonnet.actions.composer.compose_silent_segment")
    def test_calls_compose_silent_with_override(
        self, mock_compose: MagicMock, tmp_path: Path
    ) -> None:
        manifest = self._setup_manifest(tmp_path)
        output = tmp_path / "seg.mp4"
        config = ProjectConfig()

        action_compose_silent(manifest, 1, output, config, silence_override=5.0)

        mock_compose.assert_called_once_with(
            image=Path(tmp_path / "slides" / "slide.001.png"),
            output=output,
            duration=5.0,
            resolution=config.video.resolution,
            fps=config.video.fps,
            crf=config.video.crf,
            preset=config.video.preset,
        )

    @patch("slidesonnet.actions.composer.compose_silent_segment")
    def test_calls_compose_silent_without_override(
        self, mock_compose: MagicMock, tmp_path: Path
    ) -> None:
        manifest = self._setup_manifest(tmp_path)
        output = tmp_path / "seg.mp4"
        config = ProjectConfig(video=VideoConfig(silence_duration=7.0))

        action_compose_silent(manifest, 1, output, config, silence_override=None)

        mock_compose.assert_called_once_with(
            image=Path(tmp_path / "slides" / "slide.001.png"),
            output=output,
            duration=7.0,
            resolution=config.video.resolution,
            fps=config.video.fps,
            crf=config.video.crf,
            preset=config.video.preset,
        )


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

        mock_xfade.assert_called_once_with(
            mods, out, crossfade=0.8, crf=23, preset="medium", resolution="1920x1080", fps=24
        )

    def test_empty_segments_raises(self, tmp_path: Path) -> None:
        out = tmp_path / "final.mp4"

        with pytest.raises(RuntimeError, match="No segments"):
            action_assemble([], out, self._config())


def test_mixed_type_playlist(tmp_path):
    """Mixed-type playlist (MARP + Beamer + video) generates correct task graph."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Mixed Lecture
        video:
          resolution: 640x480
        modules:
          - 01-intro/slides.md
          - animations/clip.mp4
          - 02-theory/slides.tex
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

        <!-- nonarration -->
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
        \nonarration
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

    # -- Module 1 (MARP): extract_images, export_pdf, tts, compose --
    assert "extract_images:01_slides" in task_names
    assert "export_pdf:01_slides" in task_names
    marp_tts = [n for n in task_names if n.startswith("tts:01_slides")]
    assert len(marp_tts) == 1  # only slide 1 is narrated
    marp_compose = [n for n in task_names if n.startswith("compose:01_slides")]
    assert len(marp_compose) == 2  # narrated + silent (not skipped)

    # -- Module 2 (video): no tasks, referenced directly in assemble --
    assert not any(
        n.startswith(("passthrough:", "extract_images:02_", "tts:02_", "compose:02_"))
        for n in task_names
    )

    # -- Module 3 (Beamer): compile_beamer, extract_images, export_pdf, tts, compose --
    assert "compile_beamer:03_slides" in task_names
    assert "extract_images:03_slides" in task_names
    assert "export_pdf:03_slides" in task_names
    beamer_tts = [n for n in task_names if n.startswith("tts:03_slides")]
    assert len(beamer_tts) == 1  # only frame 1 is narrated
    beamer_compose = [n for n in task_names if n.startswith("compose:03_slides")]
    assert len(beamer_compose) == 2  # narrated + silent

    # -- Final assemble depends on all segments + passthrough source --
    # 2 (MARP) + 1 (video passthrough) + 2 (Beamer) = 5
    assemble = [t for t in tasks if t["name"] == "assemble"]
    assert len(assemble) == 1
    assert len(assemble[0]["file_dep"]) == 5
    # Passthrough video source is included directly
    assert str(tmp_path / "animations" / "clip.mp4") in assemble[0]["file_dep"]


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


# ---- Tests for new PDF export action functions ----


class TestActionCompileBeamer:
    """Tests for action_compile_beamer()."""

    @patch("slidesonnet.parsers.beamer.compile_pdf")
    def test_calls_compile_pdf(self, mock_compile: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text("dummy")
        slides_dir = tmp_path / "slides"
        slides_dir.mkdir()
        pdf_path = slides_dir / "slides.pdf"
        pdf_path.touch()  # simulate compile_pdf creating the file

        action_compile_beamer(source, slides_dir, pdf_path)

        mock_compile.assert_called_once_with(source, slides_dir)

    @patch("slidesonnet.parsers.beamer.compile_pdf")
    def test_raises_if_pdf_not_produced(self, mock_compile: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text("dummy")
        slides_dir = tmp_path / "slides"
        slides_dir.mkdir()
        pdf_path = slides_dir / "slides.pdf"
        # Don't create pdf_path — simulate compile failure

        with pytest.raises(RuntimeError, match="Expected PDF not produced"):
            action_compile_beamer(source, slides_dir, pdf_path)


class TestActionExtractImagesBeamer:
    """Tests for action_extract_images_beamer()."""

    @patch("slidesonnet.parsers.beamer.extract_images_from_pdf")
    def test_calls_extract_and_writes_manifest(
        self, mock_extract: MagicMock, tmp_path: Path
    ) -> None:
        import json

        slides_dir = tmp_path / "slides"
        slides_dir.mkdir()
        pdf_path = slides_dir / "slides.pdf"
        pdf_path.touch()
        manifest_path = slides_dir / "manifest.json"

        fake_images = [slides_dir / "slide-1.png", slides_dir / "slide-2.png"]
        mock_extract.return_value = fake_images

        action_extract_images_beamer(pdf_path, slides_dir, manifest_path)

        mock_extract.assert_called_once_with(pdf_path, slides_dir)
        assert manifest_path.exists()
        paths = json.loads(manifest_path.read_text())
        assert len(paths) == 2


class TestActionExportPdfMarp:
    """Tests for action_export_pdf_marp()."""

    @patch("slidesonnet.parsers.marp.export_pdf")
    def test_calls_marp_export_pdf(self, mock_export: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.md"
        source.write_text("dummy")
        output_path = tmp_path / "output" / "slides.pdf"

        action_export_pdf_marp(source, output_path)

        mock_export.assert_called_once_with(source, output_path)


class TestActionExportPdfBeamer:
    """Tests for action_export_pdf_beamer()."""

    def test_copies_pdf(self, tmp_path: Path) -> None:
        cache_pdf = tmp_path / "cache" / "slides.pdf"
        cache_pdf.parent.mkdir()
        cache_pdf.write_bytes(b"fake-pdf-content")
        output_path = tmp_path / "output" / "slides.pdf"

        action_export_pdf_beamer(cache_pdf, output_path)

        assert output_path.exists()
        assert output_path.read_bytes() == b"fake-pdf-content"

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        cache_pdf = tmp_path / "cache" / "slides.pdf"
        cache_pdf.parent.mkdir()
        cache_pdf.write_bytes(b"data")
        output_path = tmp_path / "deep" / "nested" / "slides.pdf"

        action_export_pdf_beamer(cache_pdf, output_path)

        assert output_path.parent.exists()
        assert output_path.exists()


# ---- Tests for PDF export task generation ----


def test_marp_export_pdf_task(tmp_path: Path) -> None:
    """MARP modules generate an export_pdf task."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    export_tasks = [t for t in tasks if t["name"].split(":")[0] == "export_pdf"]
    assert len(export_tasks) == 1

    et = export_tasks[0]
    # Target should be in the playlist directory with .pdf extension
    assert et["targets"][0].endswith(".pdf")
    assert str(tmp_path) in et["targets"][0]
    # Source .md should NOT be in file_dep (visual_hash replaces it)
    assert not any(dep.endswith(".md") for dep in et.get("file_dep", []))
    # Should have visual_hash in uptodate
    assert "uptodate" in et


def test_beamer_compile_and_export_pdf_tasks(tmp_path: Path) -> None:
    """Beamer modules generate compile_beamer and export_pdf tasks."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - 01-theory/slides.tex
    """)
    )

    beamer_dir = tmp_path / "01-theory"
    beamer_dir.mkdir()
    (beamer_dir / "slides.tex").write_text(
        textwrap.dedent(r"""
        \documentclass{beamer}
        \begin{document}
        \begin{frame}
        \say{Hello world.}
        \end{frame}
        \end{document}
    """).lstrip()
    )

    tasks = _generate(tmp_path, playlist)
    task_names = [t["name"] for t in tasks]

    # Should have compile_beamer, extract_images, and export_pdf
    assert "compile_beamer:01_slides" in task_names
    assert "extract_images:01_slides" in task_names
    assert "export_pdf:01_slides" in task_names

    # extract_images depends on compile_beamer
    extract_task = next(t for t in tasks if t["name"] == "extract_images:01_slides")
    assert "compile_beamer:01_slides" in extract_task.get("task_dep", [])

    # export_pdf depends on compile_beamer
    export_task = next(t for t in tasks if t["name"] == "export_pdf:01_slides")
    assert "compile_beamer:01_slides" in export_task.get("task_dep", [])

    # export_pdf target is in the playlist directory
    assert export_task["targets"][0] == str(tmp_path / "slides.pdf")


def test_video_module_no_export_pdf(tmp_path: Path) -> None:
    """Video passthrough modules do not generate export_pdf tasks."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - animations/clip.mp4
    """)
    )

    anim_dir = tmp_path / "animations"
    anim_dir.mkdir()
    (anim_dir / "clip.mp4").write_bytes(b"fake-video")

    tasks = _generate(tmp_path, playlist)
    export_tasks = [t for t in tasks if t["name"].split(":")[0] == "export_pdf"]
    assert len(export_tasks) == 0


def test_uptodate_includes_silence_override(tmp_path: Path) -> None:
    """Silent slide compose tasks include silence_override in uptodate config."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    # Find the compose task for the silent slide (slide 3)
    compose_tasks = [t for t in tasks if t["name"].split(":")[0] == "compose"]
    # The silent slide's compose task uses action_compose_silent
    silent_compose = [t for t in compose_tasks if t["actions"][0][0] is action_compose_silent]
    assert len(silent_compose) == 1

    # Check that uptodate config_changed dict has silence_override key
    uptodate_entry = silent_compose[0]["uptodate"][0]
    # config_changed returns a callable with a .config attribute
    assert "silence_override" in uptodate_entry.config


def test_silence_override_threaded_to_compose_action(tmp_path: Path) -> None:
    """silence_override from parser is passed through to compose action args."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - 01-intro/slides.md
    """)
    )

    slides_dir = tmp_path / "01-intro"
    slides_dir.mkdir()
    (slides_dir / "slides.md").write_text(
        textwrap.dedent("""\
        ---
        marp: true
        ---

        # Silent Slide

        <!-- nonarration(5) -->
    """)
    )

    tasks = _generate(tmp_path, playlist)
    silent_compose = [
        t
        for t in tasks
        if t["name"].split(":")[0] == "compose" and t["actions"][0][0] is action_compose_silent
    ]
    assert len(silent_compose) == 1

    # The 5th arg (index 4) to action_compose_silent should be 5.0
    action_args = silent_compose[0]["actions"][0][1]
    assert action_args[4] == 5.0


def test_beamer_extract_images_depends_on_cache_pdf(tmp_path: Path) -> None:
    """Beamer extract_images file_dep references the cache PDF, not the source .tex."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - 01-theory/slides.tex
    """)
    )

    beamer_dir = tmp_path / "01-theory"
    beamer_dir.mkdir()
    (beamer_dir / "slides.tex").write_text(
        textwrap.dedent(r"""
        \documentclass{beamer}
        \begin{document}
        \begin{frame}
        \say{Test.}
        \end{frame}
        \end{document}
    """).lstrip()
    )

    tasks = _generate(tmp_path, playlist)

    extract_task = next(t for t in tasks if t["name"].startswith("extract_images:"))
    # file_dep should reference the cache PDF, not the .tex source
    assert any(dep.endswith(".pdf") for dep in extract_task["file_dep"])
    assert not any(dep.endswith(".tex") for dep in extract_task["file_dep"])


# ---- Tests for preview crossfade and visual hash ----


def test_preview_disables_crossfade(tmp_path: Path) -> None:
    """Preview mode sets crossfade to 0.0 so assembly uses fast concat demuxer."""
    from slidesonnet.pipeline import _prepare

    playlist = _setup_project(tmp_path)
    prep = _prepare(playlist, tts_override=None)
    # Simulate preview overrides (same logic as pipeline.build with preview=True)
    w, h = prep.config.video.resolution.split("x")
    prep.config.video.resolution = f"{int(w) // 4}x{int(h) // 4}"
    prep.config.video.fps = prep.config.video.fps // 2
    prep.config.video.preset = "ultrafast"
    prep.config.video.crf = 32
    prep.config.video.crossfade = 0.0

    tasks = generate_tasks(
        entries=prep.entries,
        config=prep.config,
        tts=MockTTS(),
        build_dir=tmp_path / "cache",
        playlist_dir=tmp_path,
        output_path=tmp_path / "cache" / "preview.mp4",
    )

    assemble = next(t for t in tasks if t["name"] == "assemble")
    # crossfade=0.0 should be reflected in uptodate config
    assert assemble["uptodate"][0].config["crossfade"] == 0.0


def test_marp_extract_images_uses_visual_hash(tmp_path: Path) -> None:
    """MARP extract_images uses visual_hash instead of source_path in file_dep."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    extract_task = next(t for t in tasks if t["name"].startswith("extract_images:"))
    # Source .md should NOT be in file_dep
    assert not any(dep.endswith(".md") for dep in extract_task.get("file_dep", []))
    # Should have uptodate with visual_hash
    assert "uptodate" in extract_task
    uptodate_entry = extract_task["uptodate"][0]
    assert "visual_hash" in uptodate_entry.config


def test_beamer_compile_uses_visual_hash(tmp_path: Path) -> None:
    """Beamer compile_beamer uses visual_hash instead of source_path in file_dep."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        modules:
          - 01-theory/slides.tex
    """)
    )

    beamer_dir = tmp_path / "01-theory"
    beamer_dir.mkdir()
    (beamer_dir / "slides.tex").write_text(
        textwrap.dedent(r"""
        \documentclass{beamer}
        \begin{document}
        \begin{frame}
        \say{Hello world.}
        \end{frame}
        \end{document}
    """).lstrip()
    )

    tasks = _generate(tmp_path, playlist)

    compile_task = next(t for t in tasks if t["name"].startswith("compile_beamer:"))
    # Source .tex should NOT be in file_dep
    assert not any(dep.endswith(".tex") for dep in compile_task.get("file_dep", []))
    # Should have uptodate with visual_hash
    assert "uptodate" in compile_task
    uptodate_entry = compile_task["uptodate"][0]
    assert "visual_hash" in uptodate_entry.config
