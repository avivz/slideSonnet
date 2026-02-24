"""Tests for the build pipeline with mock TTS and doit integration."""

import textwrap
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.models import ProjectConfig, TTSConfig
from slidesonnet.pipeline import _create_tts, _run_doit, build


class MockTTS:
    """Mock TTS engine that generates silence WAV files."""

    def __init__(self):
        self.calls = []

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        self.calls.append((text, output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration = max(0.5, len(text) / 100.0)  # ~100 chars/sec
        with wave.open(str(output_path), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(b"\x00\x00" * int(44100 * duration))
        return duration

    def name(self) -> str:
        return "mock"


def _setup_project(tmp_path: Path) -> Path:
    """Create a minimal project with playlist + slides."""
    # Playlist
    playlist = tmp_path / "lecture.md"
    playlist.write_text(
        textwrap.dedent("""\
        ---
        title: Test Lecture
        tts:
          backend: piper
          piper:
            model: en_US-lessac-medium
        video:
          resolution: 640x480
          pad_seconds: 0.2
          silence_duration: 1.0
        ---

        1. [Intro](01-intro/slides.md)
    """)
    )

    # Slides
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

        <!-- say: This is the second slide with more content. -->

        ---

        # Silent Slide

        <!-- silent -->
    """)
    )

    return playlist


def _fake_extract(source, output_dir):
    """Mock extract_images that creates dummy PNGs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    pngs = []
    for i in range(3):
        p = output_dir / f"slides.{i + 1:03d}.png"
        _create_dummy_png(p)
        pngs.append(p)
    return pngs


def _fake_compose_segment(image, audio, output, **kwargs):
    """Mock compose_segment that creates a dummy output file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fake-video-segment")


def _fake_compose_silent(image, output, **kwargs):
    """Mock compose_silent_segment that creates a dummy output file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fake-silent-segment")


def _fake_concat(segments, output):
    """Mock concatenate_segments that creates a dummy output file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fake-concat-video")


@patch("slidesonnet.pipeline._create_tts")
@patch("slidesonnet.parsers.marp.extract_images", side_effect=_fake_extract)
@patch("slidesonnet.video.composer.concatenate_segments", side_effect=_fake_concat)
@patch("slidesonnet.video.composer.compose_silent_segment", side_effect=_fake_compose_silent)
@patch("slidesonnet.video.composer.compose_segment", side_effect=_fake_compose_segment)
@patch("slidesonnet.video.composer.get_duration", return_value=1.0)
def test_pipeline_parses_and_synthesizes(
    mock_duration,
    mock_compose,
    mock_silent,
    mock_concat,
    mock_extract,
    mock_create_tts,
    tmp_path,
):
    """Pipeline parses slides and calls TTS for narrated slides."""
    playlist = _setup_project(tmp_path)
    mock_tts = MockTTS()
    mock_create_tts.return_value = mock_tts

    build(playlist)

    # Should have synthesized 2 slides (slide 1 and 2 have <!-- say: -->)
    assert len(mock_tts.calls) == 2
    assert "Welcome to the first slide" in mock_tts.calls[0][0]
    assert "second slide" in mock_tts.calls[1][0]


@patch("slidesonnet.pipeline._create_tts")
@patch("slidesonnet.parsers.marp.extract_images", side_effect=_fake_extract)
@patch("slidesonnet.video.composer.concatenate_segments", side_effect=_fake_concat)
@patch("slidesonnet.video.composer.compose_silent_segment", side_effect=_fake_compose_silent)
@patch("slidesonnet.video.composer.compose_segment", side_effect=_fake_compose_segment)
@patch("slidesonnet.video.composer.get_duration", return_value=1.0)
def test_content_addressed_cache(
    mock_duration,
    mock_compose,
    mock_silent,
    mock_concat,
    mock_extract,
    mock_create_tts,
    tmp_path,
):
    """Second build with unchanged text should skip TTS (cache hit)."""
    playlist = _setup_project(tmp_path)
    mock_tts = MockTTS()
    mock_create_tts.return_value = mock_tts

    # First build
    build(playlist)
    first_call_count = len(mock_tts.calls)

    # Second build — should hit cache
    build(playlist)
    second_call_count = len(mock_tts.calls)

    assert first_call_count == 2  # 2 narrated slides
    assert second_call_count == 2  # no new calls — cache hit


@patch("slidesonnet.pipeline._create_tts")
@patch("slidesonnet.parsers.marp.extract_images", side_effect=_fake_extract)
@patch("slidesonnet.video.composer.concatenate_segments", side_effect=_fake_concat)
@patch("slidesonnet.video.composer.compose_silent_segment", side_effect=_fake_compose_silent)
@patch("slidesonnet.video.composer.compose_segment", side_effect=_fake_compose_segment)
@patch("slidesonnet.video.composer.get_duration", return_value=1.0)
def test_edit_one_slide_rebuilds_only_that(
    mock_duration,
    mock_compose,
    mock_silent,
    mock_concat,
    mock_extract,
    mock_create_tts,
    tmp_path,
):
    """Editing one slide's narration should only re-synthesize that slide."""
    playlist = _setup_project(tmp_path)
    mock_tts = MockTTS()
    mock_create_tts.return_value = mock_tts

    # First build
    build(playlist)
    assert len(mock_tts.calls) == 2

    # Edit slide 2's narration
    slides_path = tmp_path / "01-intro" / "slides.md"
    text = slides_path.read_text()
    text = text.replace(
        "This is the second slide with more content.",
        "This slide has been edited with new content.",
    )
    slides_path.write_text(text)

    # Second build
    build(playlist)

    # Total: 2 (first build) + 1 (only edited slide) = 3
    assert len(mock_tts.calls) == 3
    assert "edited with new content" in mock_tts.calls[2][0]


@patch("slidesonnet.pipeline._create_tts")
@patch("slidesonnet.parsers.marp.extract_images", side_effect=_fake_extract)
@patch("slidesonnet.video.composer.concatenate_segments", side_effect=_fake_concat)
@patch("slidesonnet.video.composer.compose_silent_segment", side_effect=_fake_compose_silent)
@patch("slidesonnet.video.composer.compose_segment", side_effect=_fake_compose_segment)
@patch("slidesonnet.video.composer.get_duration", return_value=1.0)
def test_utterance_files_created(
    mock_duration,
    mock_compose,
    mock_silent,
    mock_concat,
    mock_extract,
    mock_create_tts,
    tmp_path,
):
    """Build should create utterance text files for debugging."""
    playlist = _setup_project(tmp_path)
    mock_tts = MockTTS()
    mock_create_tts.return_value = mock_tts

    build(playlist)

    utterances_dir = tmp_path / ".build" / "01-intro" / "slides" / "utterances"
    assert utterances_dir.exists()
    files = sorted(utterances_dir.glob("*.txt"))
    assert len(files) == 2  # 2 narrated slides
    assert "Welcome to the first slide" in files[0].read_text()


def _create_dummy_png(path: Path) -> None:
    """Create a minimal valid PNG."""
    import struct
    import zlib

    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 100, 75

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b""
    for _ in range(height):
        raw += b"\x00" + b"\x00\x00\xff" * width
    idat = zlib.compress(raw)

    with open(path, "wb") as f:
        f.write(sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b""))


# ---- Mocked unit tests for _create_tts and _run_doit ----


class TestCreateTTS:
    """Tests for _create_tts()."""

    def test_piper_backend(self) -> None:
        config = ProjectConfig(tts=TTSConfig(backend="piper", piper_model="en_US-lessac-medium"))
        tts = _create_tts(config)
        from slidesonnet.tts.piper import PiperTTS

        assert isinstance(tts, PiperTTS)
        assert tts.model == "en_US-lessac-medium"

    @patch("slidesonnet.tts.elevenlabs.ElevenLabsTTS")
    def test_elevenlabs_backend(self, mock_cls: MagicMock) -> None:
        config = ProjectConfig(tts=TTSConfig(backend="elevenlabs"))
        _create_tts(config)
        mock_cls.assert_called_once_with(config.tts)

    def test_unknown_backend(self) -> None:
        config = ProjectConfig(tts=TTSConfig(backend="unknown_engine"))
        with pytest.raises(ValueError, match="Unknown TTS backend"):
            _create_tts(config)


class TestRunDoit:
    """Tests for _run_doit()."""

    @patch("doit.doit_cmd.DoitMain")
    @patch("doit.task.dict_to_task")
    def test_success(self, mock_d2t: MagicMock, mock_doit: MagicMock, tmp_path: Path) -> None:
        mock_d2t.side_effect = lambda t: t
        mock_main = MagicMock()
        mock_main.run.return_value = 0
        mock_doit.return_value = mock_main

        _run_doit([{"name": "test"}], tmp_path, force=False)

        mock_main.run.assert_called_once()
        args = mock_main.run.call_args[0][0]
        assert args == ["run"]

    @patch("doit.doit_cmd.DoitMain")
    @patch("doit.task.dict_to_task")
    def test_force_flag(self, mock_d2t: MagicMock, mock_doit: MagicMock, tmp_path: Path) -> None:
        mock_d2t.side_effect = lambda t: t
        mock_main = MagicMock()
        mock_main.run.return_value = 0
        mock_doit.return_value = mock_main

        _run_doit([{"name": "test"}], tmp_path, force=True)

        args = mock_main.run.call_args[0][0]
        assert "--always-execute" in args

    @patch("doit.doit_cmd.DoitMain")
    @patch("doit.task.dict_to_task")
    def test_nonzero_exit_raises(
        self, mock_d2t: MagicMock, mock_doit: MagicMock, tmp_path: Path
    ) -> None:
        mock_d2t.side_effect = lambda t: t
        mock_main = MagicMock()
        mock_main.run.return_value = 2
        mock_doit.return_value = mock_main

        with pytest.raises(SystemExit):
            _run_doit([{"name": "test"}], tmp_path, force=False)

    @patch("doit.doit_cmd.DoitMain")
    @patch("doit.task.dict_to_task")
    def test_none_exit_ok(self, mock_d2t: MagicMock, mock_doit: MagicMock, tmp_path: Path) -> None:
        mock_d2t.side_effect = lambda t: t
        mock_main = MagicMock()
        mock_main.run.return_value = None
        mock_doit.return_value = mock_main

        # Should not raise
        _run_doit([{"name": "test"}], tmp_path, force=False)
