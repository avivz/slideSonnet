"""Tests for doit task generation."""

import textwrap
from pathlib import Path

import pytest

from slidesonnet.config import load_config
from slidesonnet.playlist import parse_playlist
from slidesonnet.tasks import generate_tasks
from slidesonnet.tts.base import TTSEngine


class MockTTS(TTSEngine):
    def synthesize(self, text, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-audio")
        return 1.0

    def name(self):
        return "mock"


def _setup_project(tmp_path):
    """Create a minimal project with playlist + slides."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(textwrap.dedent("""\
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
    """))

    slides_dir = tmp_path / "01-intro"
    slides_dir.mkdir()
    (slides_dir / "slides.md").write_text(textwrap.dedent("""\
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
    """))

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

    basenames = [t['name'].split(':')[0] for t in tasks]
    assert 'extract_images' in basenames
    assert 'tts' in basenames
    assert 'compose' in basenames
    assert 'concat' in basenames
    assert 'assemble' in basenames


def test_tts_tasks_per_narrated_slide(tmp_path):
    """One TTS task per narrated slide, none for silent."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    tts_tasks = [t for t in tasks if t['name'].split(':')[0] == 'tts']
    assert len(tts_tasks) == 2  # slides 1 and 2 have <!-- say: -->


def test_compose_tasks_skip_skipped_slides(tmp_path):
    """Compose tasks skip slides with <!-- skip -->."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(textwrap.dedent("""\
        ---
        title: Test
        ---

        1. [Intro](01-intro/slides.md)
    """))

    slides_dir = tmp_path / "01-intro"
    slides_dir.mkdir()
    (slides_dir / "slides.md").write_text(textwrap.dedent("""\
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
    """))

    tasks = _generate(tmp_path, playlist)
    compose_tasks = [t for t in tasks if t['name'].split(':')[0] == 'compose']
    # Slide 1 (narrated) and slide 3 (silent) compose, slide 2 (skip) doesn't
    assert len(compose_tasks) == 2


def test_content_addressed_audio_targets(tmp_path):
    """TTS targets use content-addressed filenames."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    tts_tasks = [t for t in tasks if t['name'].split(':')[0] == 'tts']
    targets = [t['targets'][0] for t in tts_tasks]

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

    compose_tasks = [t for t in tasks if t['name'].split(':')[0] == 'compose']
    for ct in compose_tasks:
        # All compose tasks depend on extract_images
        assert any('extract_images' in dep for dep in ct.get('task_dep', []))

    # Narrated compose tasks also depend on tts
    narrated = [ct for ct in compose_tasks if any('tts' in dep for dep in ct.get('task_dep', []))]
    assert len(narrated) == 2  # 2 narrated slides


def test_video_passthrough_task(tmp_path):
    """Video modules create passthrough tasks."""
    playlist = tmp_path / "lecture.md"
    playlist.write_text(textwrap.dedent("""\
        ---
        title: Test
        ---

        1. [Clip](animations/clip.mp4)
    """))

    anim_dir = tmp_path / "animations"
    anim_dir.mkdir()
    (anim_dir / "clip.mp4").write_bytes(b"fake-video")

    tasks = _generate(tmp_path, playlist)

    passthrough = [t for t in tasks if t['name'].split(':')[0] == 'passthrough']
    assert len(passthrough) == 1
    assert str(anim_dir / "clip.mp4") in passthrough[0]['file_dep']


def test_uptodate_uses_text_content(tmp_path):
    """TTS uptodate checks are based on narration text content."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    tts_tasks = [t for t in tasks if t['name'].split(':')[0] == 'tts']
    for t in tts_tasks:
        assert 'uptodate' in t
        assert len(t['uptodate']) > 0


def test_concat_depends_on_segments(tmp_path):
    """Module concat task depends on all segment files."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    concat_tasks = [t for t in tasks if t['name'].split(':')[0] == 'concat']
    assert len(concat_tasks) == 1

    # Should depend on segment files (3 slides - 0 skips = 3 segments)
    # Slides: say, say, silent → 3 compose tasks → 3 segments
    assert len(concat_tasks[0]['file_dep']) == 3


def test_assemble_depends_on_modules(tmp_path):
    """Final assembly depends on module videos."""
    playlist = _setup_project(tmp_path)
    tasks = _generate(tmp_path, playlist)

    assemble = [t for t in tasks if t['name'].split(':')[0] == 'assemble']
    assert len(assemble) == 1
    assert len(assemble[0]['file_dep']) == 1  # 1 module
