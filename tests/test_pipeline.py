"""Tests for the build pipeline with mock TTS and doit integration."""

import textwrap
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.models import ProjectConfig, TTSConfig
from slidesonnet.pipeline import (
    _PreparedBuild,
    _filter_tasks_until,
    _prepare,
    _resolve_output_name,
    _run_doit,
    build,
)
from slidesonnet.tts import create_tts


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

    def cache_key(self) -> str:
        return "mock:default"


def _setup_project(tmp_path: Path) -> Path:
    """Create a minimal project with playlist + slides."""
    # Playlist
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test Lecture
        tts:
          backend: piper
          piper:
            model: en_US-lessac-medium
        video:
          resolution: 640x480
          pad_seconds: 0.2
          silence_duration: 1.0
        modules:
          - 01-intro/slides.md
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

        <!-- nonarration -->
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


def _fake_concat_xfade(segments, output, **kwargs):
    """Mock concatenate_segments_xfade that creates a dummy output file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fake-xfade-video")


def _fake_export_pdf(source, output_path):
    """Mock export_pdf that creates a dummy PDF file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"%PDF-1.4 fake")


@patch("slidesonnet.pipeline.create_tts")
@patch("slidesonnet.parsers.marp.export_pdf", side_effect=_fake_export_pdf)
@patch("slidesonnet.parsers.marp.extract_images", side_effect=_fake_extract)
@patch("slidesonnet.video.composer.concatenate_segments_xfade", side_effect=_fake_concat_xfade)
@patch("slidesonnet.video.composer.concatenate_segments", side_effect=_fake_concat)
@patch("slidesonnet.video.composer.compose_silent_segment", side_effect=_fake_compose_silent)
@patch("slidesonnet.video.composer.compose_segment", side_effect=_fake_compose_segment)
@patch("slidesonnet.video.composer.get_duration", return_value=1.0)
@patch("slidesonnet.tasks.action_concat_pdfs", return_value=None)
def test_pipeline_parses_and_synthesizes(
    mock_concat_pdfs,
    mock_duration,
    mock_compose,
    mock_silent,
    mock_concat,
    mock_concat_xfade,
    mock_extract,
    mock_export_pdf,
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
    texts = {call[0] for call in mock_tts.calls}
    assert any("Welcome to the first slide" in t for t in texts)
    assert any("second slide" in t for t in texts)


@patch("slidesonnet.pipeline.create_tts")
@patch("slidesonnet.parsers.marp.export_pdf", side_effect=_fake_export_pdf)
@patch("slidesonnet.parsers.marp.extract_images", side_effect=_fake_extract)
@patch("slidesonnet.video.composer.concatenate_segments_xfade", side_effect=_fake_concat_xfade)
@patch("slidesonnet.video.composer.concatenate_segments", side_effect=_fake_concat)
@patch("slidesonnet.video.composer.compose_silent_segment", side_effect=_fake_compose_silent)
@patch("slidesonnet.video.composer.compose_segment", side_effect=_fake_compose_segment)
@patch("slidesonnet.video.composer.get_duration", return_value=1.0)
@patch("slidesonnet.tasks.action_concat_pdfs", return_value=None)
def test_content_addressed_cache(
    mock_concat_pdfs,
    mock_duration,
    mock_compose,
    mock_silent,
    mock_concat,
    mock_concat_xfade,
    mock_extract,
    mock_export_pdf,
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


@patch("slidesonnet.pipeline.create_tts")
@patch("slidesonnet.parsers.marp.export_pdf", side_effect=_fake_export_pdf)
@patch("slidesonnet.parsers.marp.extract_images", side_effect=_fake_extract)
@patch("slidesonnet.video.composer.concatenate_segments_xfade", side_effect=_fake_concat_xfade)
@patch("slidesonnet.video.composer.concatenate_segments", side_effect=_fake_concat)
@patch("slidesonnet.video.composer.compose_silent_segment", side_effect=_fake_compose_silent)
@patch("slidesonnet.video.composer.compose_segment", side_effect=_fake_compose_segment)
@patch("slidesonnet.video.composer.get_duration", return_value=1.0)
@patch("slidesonnet.tasks.action_concat_pdfs", return_value=None)
def test_edit_one_slide_rebuilds_only_that(
    mock_concat_pdfs,
    mock_duration,
    mock_compose,
    mock_silent,
    mock_concat,
    mock_concat_xfade,
    mock_extract,
    mock_export_pdf,
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


@patch("slidesonnet.pipeline.create_tts")
@patch("slidesonnet.parsers.marp.export_pdf", side_effect=_fake_export_pdf)
@patch("slidesonnet.parsers.marp.extract_images", side_effect=_fake_extract)
@patch("slidesonnet.video.composer.concatenate_segments_xfade", side_effect=_fake_concat_xfade)
@patch("slidesonnet.video.composer.concatenate_segments", side_effect=_fake_concat)
@patch("slidesonnet.video.composer.compose_silent_segment", side_effect=_fake_compose_silent)
@patch("slidesonnet.video.composer.compose_segment", side_effect=_fake_compose_segment)
@patch("slidesonnet.video.composer.get_duration", return_value=1.0)
@patch("slidesonnet.tasks.action_concat_pdfs", return_value=None)
def test_utterance_files_created(
    mock_concat_pdfs,
    mock_duration,
    mock_compose,
    mock_silent,
    mock_concat,
    mock_concat_xfade,
    mock_extract,
    mock_export_pdf,
    mock_create_tts,
    tmp_path,
):
    """Build should create utterance text files for debugging."""
    playlist = _setup_project(tmp_path)
    mock_tts = MockTTS()
    mock_create_tts.return_value = mock_tts

    build(playlist)

    utterances_dir = tmp_path / "cache" / "01-intro" / "slides" / "utterances"
    assert utterances_dir.exists()
    files = sorted(utterances_dir.glob("*.txt"))
    assert len(files) == 2  # 2 narrated slides
    assert "Welcome to the first slide" in files[0].read_text()


def _fake_concat_audio(audio_paths: list[Path], output: Path) -> None:
    """Mock concatenate_audio that creates a dummy output file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fake-concat-audio")


@patch("slidesonnet.pipeline.create_tts")
@patch("slidesonnet.parsers.marp.export_pdf", side_effect=_fake_export_pdf)
@patch("slidesonnet.parsers.marp.extract_images", side_effect=_fake_extract)
@patch("slidesonnet.video.composer.concatenate_segments_xfade", side_effect=_fake_concat_xfade)
@patch("slidesonnet.video.composer.concatenate_segments", side_effect=_fake_concat)
@patch("slidesonnet.video.composer.concatenate_audio", side_effect=_fake_concat_audio)
@patch("slidesonnet.video.composer.compose_silent_segment", side_effect=_fake_compose_silent)
@patch("slidesonnet.video.composer.compose_segment", side_effect=_fake_compose_segment)
@patch("slidesonnet.video.composer.get_duration", return_value=1.0)
@patch("slidesonnet.tasks.action_concat_pdfs", return_value=None)
def test_multi_part_per_say_caching(
    mock_concat_pdfs: MagicMock,
    mock_duration: MagicMock,
    mock_compose: MagicMock,
    mock_silent: MagicMock,
    mock_concat_audio: MagicMock,
    mock_concat: MagicMock,
    mock_concat_xfade: MagicMock,
    mock_extract: MagicMock,
    mock_export_pdf: MagicMock,
    mock_create_tts: MagicMock,
    tmp_path: Path,
) -> None:
    """Editing one say in a multi-say slide only re-synthesizes that part."""
    # Setup project with multi-say slide
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

        <!-- say(1): First part of the narration. -->
        <!-- say(1): Second part of the narration. -->
    """)
    )

    mock_tts = MockTTS()
    mock_create_tts.return_value = mock_tts

    # First build
    build(playlist)
    first_call_count = len(mock_tts.calls)
    assert first_call_count == 2  # two parts synthesized

    # Second build — should hit cache for both parts
    build(playlist)
    assert len(mock_tts.calls) == 2  # no new calls

    # Edit only the second say
    slides_path = slides_dir / "slides.md"
    text = slides_path.read_text()
    text = text.replace(
        "Second part of the narration.",
        "Edited second part of the narration.",
    )
    slides_path.write_text(text)

    # Third build — only the edited part should be re-synthesized
    build(playlist)
    assert len(mock_tts.calls) == 3  # only 1 new call
    assert "Edited second part" in mock_tts.calls[2][0]


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


class TestElevenLabsAPIKeyValidation:
    """Tests for early ElevenLabs API key validation in _prepare()."""

    def test_missing_api_key_raises_early(self, tmp_path: Path) -> None:
        """_prepare() should raise SlideSonnetError when ElevenLabs key is missing."""
        playlist = tmp_path / "slidesonnet.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: elevenlabs
              elevenlabs:
                voice_id: abc123
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Slide\n<!-- say: Hello -->\n")

        # Ensure the env var is unset
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SlideSonnetError, match="ElevenLabs API key not found"):
                _prepare(playlist)

    def test_present_api_key_passes(self, tmp_path: Path) -> None:
        """_prepare() should succeed when ElevenLabs key is set."""
        playlist = tmp_path / "slidesonnet.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: elevenlabs
              elevenlabs:
                voice_id: abc123
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Slide\n<!-- say: Hello -->\n")

        with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "test-key-123"}):
            prep = _prepare(playlist)
            assert prep.config.tts.backend == "elevenlabs"

    def test_piper_backend_skips_api_key_check(self, tmp_path: Path) -> None:
        """_prepare() should not check API key for piper backend."""
        playlist = tmp_path / "slidesonnet.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Slide\n<!-- say: Hello -->\n")

        # Should not raise even without any env vars
        prep = _prepare(playlist)
        assert prep.config.tts.backend == "piper"


class TestCreateTTS:
    """Tests for create_tts()."""

    def test_piper_backend(self) -> None:
        config = ProjectConfig(tts=TTSConfig(backend="piper", piper_model="en_US-lessac-medium"))
        tts = create_tts(config)
        from slidesonnet.tts.piper import PiperTTS

        assert isinstance(tts, PiperTTS)
        assert tts.model == "en_US-lessac-medium"

    @patch("slidesonnet.tts.elevenlabs.ElevenLabsTTS")
    def test_elevenlabs_backend(self, mock_cls: MagicMock) -> None:
        config = ProjectConfig(tts=TTSConfig(backend="elevenlabs"))
        create_tts(config)
        mock_cls.assert_called_once_with(config.tts)

    def test_unknown_backend(self) -> None:
        config = ProjectConfig(tts=TTSConfig(backend="unknown_engine"))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Unknown TTS backend"):
            create_tts(config)


class TestRunDoit:
    """Tests for _run_doit()."""

    @patch("doit.doit_cmd.DoitMain")
    @patch("doit.task.dict_to_task")
    def test_success(self, mock_d2t: MagicMock, mock_doit: MagicMock, tmp_path: Path) -> None:
        mock_d2t.side_effect = lambda t: t
        mock_main = MagicMock()
        mock_main.run.return_value = 0
        mock_doit.return_value = mock_main

        _run_doit([{"name": "test"}], tmp_path)

        mock_main.run.assert_called_once()
        args = mock_main.run.call_args[0][0]
        assert args == ["run"]

    @patch("doit.doit_cmd.DoitMain")
    @patch("doit.task.dict_to_task")
    def test_nonzero_exit_raises(
        self, mock_d2t: MagicMock, mock_doit: MagicMock, tmp_path: Path
    ) -> None:
        mock_d2t.side_effect = lambda t: t
        mock_main = MagicMock()
        mock_main.run.return_value = 2
        mock_doit.return_value = mock_main

        with pytest.raises(SlideSonnetError, match="doit exit code"):
            _run_doit([{"name": "test"}], tmp_path)

    @patch("doit.doit_cmd.DoitMain")
    @patch("doit.task.dict_to_task")
    def test_none_exit_ok(self, mock_d2t: MagicMock, mock_doit: MagicMock, tmp_path: Path) -> None:
        mock_d2t.side_effect = lambda t: t
        mock_main = MagicMock()
        mock_main.run.return_value = None
        mock_doit.return_value = mock_main

        # Should not raise
        _run_doit([{"name": "test"}], tmp_path)

    @patch("doit.doit_cmd.DoitMain")
    @patch("doit.task.dict_to_task")
    def test_no_parallel_flags(
        self, mock_d2t: MagicMock, mock_doit: MagicMock, tmp_path: Path
    ) -> None:
        """doit config should not contain parallel settings."""
        mock_d2t.side_effect = lambda t: t
        mock_main = MagicMock()
        mock_main.run.return_value = 0
        mock_doit.return_value = mock_main

        _run_doit([{"name": "test"}], tmp_path)

        # Inspect the loader config
        loader = mock_doit.call_args[0][0]
        config = loader.load_doit_config()
        assert "num_process" not in config
        assert "par_type" not in config


class TestFilterTasksUntil:
    """Tests for _filter_tasks_until()."""

    _SAMPLE_TASKS: list[dict[str, str]] = [
        {"name": "compile_beamer:01_intro"},
        {"name": "extract_images:01_intro"},
        {"name": "export_pdf:01_intro"},
        {"name": "assemble_pdf"},
        {"name": "tts:01_intro_slide_001"},
        {"name": "tts:01_intro_slide_002"},
        {"name": "concat_audio:01_intro_slide_001"},
        {"name": "compose:01_intro_slide_001"},
        {"name": "compose:01_intro_slide_002"},
        {"name": "assemble"},
    ]

    def test_none_returns_all(self) -> None:
        result = _filter_tasks_until(self._SAMPLE_TASKS, None)
        assert result == self._SAMPLE_TASKS

    def test_slides_stage(self) -> None:
        result = _filter_tasks_until(self._SAMPLE_TASKS, "slides")
        names = [t["name"] for t in result]
        assert names == [
            "compile_beamer:01_intro",
            "extract_images:01_intro",
            "export_pdf:01_intro",
            "assemble_pdf",
        ]

    def test_tts_stage(self) -> None:
        result = _filter_tasks_until(self._SAMPLE_TASKS, "tts")
        names = [t["name"] for t in result]
        assert names == [
            "compile_beamer:01_intro",
            "extract_images:01_intro",
            "export_pdf:01_intro",
            "assemble_pdf",
            "tts:01_intro_slide_001",
            "tts:01_intro_slide_002",
            "concat_audio:01_intro_slide_001",
        ]

    def test_segments_stage(self) -> None:
        result = _filter_tasks_until(self._SAMPLE_TASKS, "segments")
        names = [t["name"] for t in result]
        # Everything except "assemble"
        assert "assemble" not in names
        assert len(names) == 9


class TestAudioCacheExists:
    """Tests for _audio_cache_exists()."""

    def test_file_exists_nonempty(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import _audio_cache_exists

        f = tmp_path / "audio.wav"
        f.write_bytes(b"\x00" * 100)
        assert _audio_cache_exists(f) is True

    def test_file_exists_empty(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import _audio_cache_exists

        f = tmp_path / "audio.wav"
        f.touch()
        assert _audio_cache_exists(f) is False

    def test_file_not_found(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import _audio_cache_exists

        assert _audio_cache_exists(tmp_path / "nope.wav") is False

    def test_alternate_extension_found(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import _audio_cache_exists

        # Request .mp3, but .wav exists
        mp3 = tmp_path / "audio.mp3"
        wav = tmp_path / "audio.wav"
        wav.write_bytes(b"\x00" * 100)
        assert _audio_cache_exists(mp3) is True

    def test_alternate_extension_empty(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import _audio_cache_exists

        mp3 = tmp_path / "audio.mp3"
        wav = tmp_path / "audio.wav"
        wav.touch()  # empty
        assert _audio_cache_exists(mp3) is False


class TestPreflightMultiPart:
    """Tests for _preflight_api_check with multi-part slides."""

    def test_multi_part_uncached_raises(self) -> None:
        from slidesonnet.models import SlideAnnotation, SlideNarration
        from slidesonnet.pipeline import _PreparedBuild, _preflight_api_check

        config = MagicMock()
        config.tts.backend = "elevenlabs"
        config.pronunciation_for.return_value = {}
        config.voices = {}

        tts = MagicMock()
        tts.name.return_value = "elevenlabs"
        tts.cache_key.return_value = "key123"

        entry = MagicMock()
        entry.module_type = MagicMock()
        entry.path = Path("01-intro/slides.md")

        prep = _PreparedBuild(
            playlist_path=Path("/fake/lecture.yaml"),
            playlist_dir=Path("/fake"),
            build_dir=Path("/fake/cache"),
            config=config,
            entries=[entry],
            tts=tts,
            output_path=Path("/fake/lecture.mp4"),
            pdf_output_path=Path("/fake/lecture.pdf"),
        )

        # Multi-part slide (2 parts)
        slide = SlideNarration(
            index=1,
            annotation=SlideAnnotation.SAY,
            narration_raw="Part one. Part two.",
            narration_parts=["Part one.", "Part two."],
        )

        with (
            patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.pipeline._audio_cache_exists", return_value=False),
            patch("slidesonnet.pipeline.apply_pronunciation", side_effect=lambda t, _: t),
        ):
            parser = MagicMock()
            parser.parse.return_value = [slide]
            mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())

            from slidesonnet.exceptions import APINotAllowedError

            with pytest.raises(APINotAllowedError) as exc_info:
                _preflight_api_check(prep)

            msg = str(exc_info.value)
            assert "1 uncached slide" in msg
            assert "Part one" in msg

    def test_multi_part_all_cached_passes(self) -> None:
        from slidesonnet.models import SlideAnnotation, SlideNarration
        from slidesonnet.pipeline import _PreparedBuild, _preflight_api_check

        config = MagicMock()
        config.tts.backend = "elevenlabs"
        config.pronunciation_for.return_value = {}
        config.voices = {}

        tts = MagicMock()
        tts.name.return_value = "elevenlabs"
        tts.cache_key.return_value = "key123"

        entry = MagicMock()
        entry.module_type = MagicMock()
        entry.path = Path("01-intro/slides.md")

        prep = _PreparedBuild(
            playlist_path=Path("/fake/lecture.yaml"),
            playlist_dir=Path("/fake"),
            build_dir=Path("/fake/cache"),
            config=config,
            entries=[entry],
            tts=tts,
            output_path=Path("/fake/lecture.mp4"),
            pdf_output_path=Path("/fake/lecture.pdf"),
        )

        slide = SlideNarration(
            index=1,
            annotation=SlideAnnotation.SAY,
            narration_raw="Part one. Part two.",
            narration_parts=["Part one.", "Part two."],
        )

        with (
            patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.pipeline._audio_cache_exists", return_value=True),
            patch("slidesonnet.pipeline.apply_pronunciation", side_effect=lambda t, _: t),
        ):
            parser = MagicMock()
            parser.parse.return_value = [slide]
            mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())

            # Should not raise
            _preflight_api_check(prep)


class TestPreflightVideoEntry:
    """Tests for _preflight_api_check skipping video entries."""

    def test_video_entry_skipped(self) -> None:
        from slidesonnet.models import ModuleType
        from slidesonnet.pipeline import _PreparedBuild, _preflight_api_check

        config = MagicMock()
        config.tts.backend = "elevenlabs"

        tts = MagicMock()
        tts.name.return_value = "elevenlabs"
        tts.cache_key.return_value = "key123"

        entry = MagicMock()
        entry.module_type = ModuleType.VIDEO
        entry.path = Path("video.mp4")

        prep = _PreparedBuild(
            playlist_path=Path("/fake/lecture.yaml"),
            playlist_dir=Path("/fake"),
            build_dir=Path("/fake/cache"),
            config=config,
            entries=[entry],
            tts=tts,
            output_path=Path("/fake/lecture.mp4"),
            pdf_output_path=Path("/fake/lecture.pdf"),
        )

        # Should not raise — video entries are skipped
        _preflight_api_check(prep)


class TestGenerateSrtFile:
    """Tests for generate_srt_file()."""

    def test_generates_srt(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import generate_srt_file

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Hello\n<!-- say: Welcome. -->\n")

        with (
            patch("slidesonnet.subtitles.get_duration", return_value=2.0),
            patch("slidesonnet.subtitles._find_audio_path") as mock_find,
        ):
            # Create a fake audio file for _find_audio_path
            fake_audio = tmp_path / "fake.wav"
            fake_audio.write_bytes(b"\x00" * 100)
            mock_find.return_value = fake_audio

            srt_path = generate_srt_file(playlist)

        assert srt_path.exists()
        content = srt_path.read_text()
        assert "Welcome." in content

    def test_custom_output(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import generate_srt_file

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Hello\n<!-- say: Hi there. -->\n")
        custom = tmp_path / "custom.srt"

        with (
            patch("slidesonnet.subtitles.get_duration", return_value=1.0),
            patch("slidesonnet.subtitles._find_audio_path") as mock_find,
        ):
            fake_audio = tmp_path / "fake.wav"
            fake_audio.write_bytes(b"\x00" * 100)
            mock_find.return_value = fake_audio

            result = generate_srt_file(playlist, output=custom)

        assert result == custom
        assert custom.exists()


class TestGenerateSrtFailure:
    """Tests for _generate_srt failure path."""

    @patch("slidesonnet.pipeline.create_tts")
    @patch("slidesonnet.parsers.marp.export_pdf", side_effect=_fake_export_pdf)
    @patch("slidesonnet.parsers.marp.extract_images", side_effect=_fake_extract)
    @patch("slidesonnet.video.composer.concatenate_segments_xfade", side_effect=_fake_concat_xfade)
    @patch("slidesonnet.video.composer.concatenate_segments", side_effect=_fake_concat)
    @patch("slidesonnet.video.composer.compose_silent_segment", side_effect=_fake_compose_silent)
    @patch("slidesonnet.video.composer.compose_segment", side_effect=_fake_compose_segment)
    @patch("slidesonnet.video.composer.get_duration", return_value=1.0)
    @patch("slidesonnet.tasks.action_concat_pdfs", return_value=None)
    def test_srt_failure_returns_none_in_result(
        self,
        mock_concat_pdfs,
        mock_duration,
        mock_compose,
        mock_silent,
        mock_concat,
        mock_concat_xfade,
        mock_extract,
        mock_export_pdf,
        mock_create_tts,
        tmp_path,
    ):
        """If SRT generation raises, build still succeeds with srt_path=None."""
        playlist = _setup_project(tmp_path)
        mock_tts = MockTTS()
        mock_create_tts.return_value = mock_tts

        with patch("slidesonnet.pipeline._generate_srt", side_effect=Exception("srt boom")):
            # _generate_srt catches exceptions internally, so let's patch at lower level
            pass

        # Actually test the internal catch by patching generate_subtitles
        with patch(
            "slidesonnet.subtitles.generate_subtitles",
            side_effect=RuntimeError("audio not found"),
        ):
            result = build(playlist)

        assert result.srt_path is None


class TestListSlides:
    """Tests for list_slides()."""

    def test_basic_listing(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import list_slides

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Slide One

            <!-- say: Hello world. -->

            ---

            # Silent

            <!-- nonarration -->

            ---

            # No annotation
        """)
        )

        result = list_slides(playlist)

        assert result.tts_backend == "piper"
        assert len(result.slides) >= 2
        narrated = [s for s in result.slides if s.cached is not None]
        assert len(narrated) >= 1
        assert narrated[0].text == "Hello world."
        silent = [s for s in result.slides if s.text == "[silent]"]
        assert len(silent) == 1

    def test_unannotated_shows_no_annotation(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import list_slides

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Bare Slide\n")

        result = list_slides(playlist)

        assert len(result.slides) == 1
        assert result.slides[0].text == "[no annotation]"
        assert result.slides[0].cached is None


class TestExportUtterances:
    """Tests for export_utterances()."""

    def test_basic_utterances(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import export_utterances

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Hello

            <!-- say: Welcome to the lecture. -->

            ---

            # Silent

            <!-- nonarration -->

            ---

            # Skipped

            <!-- skip -->
        """)
        )

        modules = export_utterances(playlist)

        assert len(modules) == 1
        mod = modules[0]
        assert mod.module_path == "slides.md"
        # Skip slides are excluded, but narrated + silent are included
        narrated = [s for s in mod.slides if s.text and s.text != "[silent]"]
        assert len(narrated) == 1
        assert narrated[0].text == "Welcome to the lecture."
        silent = [s for s in mod.slides if s.text == "[silent]"]
        assert len(silent) == 1

    def test_video_entries_skipped(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import export_utterances

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - intro.mp4
              - slides.md
        """)
        )
        (tmp_path / "intro.mp4").touch()
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Hello\n<!-- say: Hi. -->\n")

        modules = export_utterances(playlist)

        assert len(modules) == 1
        assert modules[0].module_path == "slides.md"


class TestExportPdfs:
    """Tests for export_pdfs()."""

    def test_marp_module(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import export_pdfs

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Hello\n<!-- say: Hi. -->\n")

        def _fake_marp_export(source: Path, output: Path) -> None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"%PDF-1.4 fake")

        def _fake_concat(pdfs: list[Path], output: Path) -> None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"%PDF-1.4 concatenated")

        with (
            patch("slidesonnet.parsers.marp.export_pdf", side_effect=_fake_marp_export),
            patch("slidesonnet.actions.action_concat_pdfs", side_effect=_fake_concat),
        ):
            result = export_pdfs(playlist)

        assert result.exists()
        assert result.suffix == ".pdf"

    def test_no_slide_modules_raises(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import export_pdfs

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - intro.mp4
        """)
        )
        (tmp_path / "intro.mp4").touch()

        with pytest.raises(SlideSonnetError, match="No slide modules"):
            export_pdfs(playlist)


class TestResolveOutputName:
    """Tests for _resolve_output_name()."""

    def test_default_uses_directory_name(self, tmp_path: Path) -> None:
        playlist_dir = tmp_path / "my-lecture"
        playlist_dir.mkdir()
        result = _resolve_output_name(playlist_dir, "")
        assert result == (playlist_dir / "my-lecture.mp4").resolve()

    def test_config_output_relative(self, tmp_path: Path) -> None:
        playlist_dir = tmp_path / "proj"
        playlist_dir.mkdir()
        result = _resolve_output_name(playlist_dir, "output.mp4")
        assert result == (playlist_dir / "output.mp4").resolve()

    def test_config_output_appends_mp4(self, tmp_path: Path) -> None:
        playlist_dir = tmp_path / "proj"
        playlist_dir.mkdir()
        result = _resolve_output_name(playlist_dir, "lecture")
        assert result.suffix == ".mp4"

    def test_override_takes_precedence(self, tmp_path: Path) -> None:
        playlist_dir = tmp_path / "proj"
        playlist_dir.mkdir()
        override = tmp_path / "custom.mp4"
        result = _resolve_output_name(playlist_dir, "config-name.mp4", override)
        assert result.name == "custom.mp4"

    def test_override_appends_mp4(self, tmp_path: Path) -> None:
        playlist_dir = tmp_path / "proj"
        playlist_dir.mkdir()
        override = tmp_path / "custom"
        result = _resolve_output_name(playlist_dir, "", override)
        assert result.suffix == ".mp4"

    def test_relative_override_resolved_to_cwd(self, tmp_path: Path) -> None:
        playlist_dir = tmp_path / "proj"
        playlist_dir.mkdir()
        override = Path("relative/output.mp4")
        result = _resolve_output_name(playlist_dir, "", override)
        assert result.is_absolute()
        assert result.name == "output.mp4"
        # Should be relative to cwd, not playlist_dir
        assert str(Path.cwd()) in str(result)


class TestDryRun:
    """Tests for dry_run()."""

    def test_basic_dry_run(self, tmp_path: Path) -> None:
        """dry_run returns correct counts for narrated/silent/unannotated slides."""
        from slidesonnet.pipeline import dry_run

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Narrated

            <!-- say: Hello world. -->

            ---

            # Silent

            <!-- nonarration -->

            ---

            # Bare slide
        """)
        )

        result = dry_run(playlist)

        assert result.tts_backend == "piper"
        assert result.total_narrated == 1
        assert result.needs_tts == 1  # no cache exists
        assert result.cached == 0
        assert result.uncached_chars == len("Hello world.")

    def test_video_entries_skipped(self, tmp_path: Path) -> None:
        """dry_run skips video entries."""
        from slidesonnet.pipeline import dry_run

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - intro.mp4
              - slides.md
        """)
        )
        (tmp_path / "intro.mp4").touch()
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Hello\n<!-- say: Hi. -->\n")

        result = dry_run(playlist)

        assert result.total_narrated == 1
        assert result.needs_tts == 1

    def test_multi_part_slides(self, tmp_path: Path) -> None:
        """dry_run handles multi-part slides correctly."""
        from slidesonnet.pipeline import dry_run

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Multi-say

            <!-- say(1): Part one. -->
            <!-- say(1): Part two. -->
        """)
        )

        result = dry_run(playlist)

        assert result.total_narrated == 1
        assert result.needs_tts == 1
        assert result.uncached_chars == len("Part one.") + len("Part two.")

    def test_tts_override(self, tmp_path: Path) -> None:
        """dry_run respects tts_override parameter."""
        from slidesonnet.pipeline import dry_run

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: elevenlabs
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Hello\n<!-- say: Hi. -->\n")

        # Override to piper so we don't need API key
        result = dry_run(playlist, tts_override="piper")

        assert result.tts_backend == "piper"


class TestBuildOptions:
    """Tests for build() flag handling."""

    def _make_prep(self, tmp_path: Path) -> _PreparedBuild:
        from slidesonnet.models import VideoConfig

        config = ProjectConfig(
            tts=TTSConfig(backend="piper"),
            video=VideoConfig(),
        )
        tts = MagicMock()
        return _PreparedBuild(
            playlist_path=tmp_path / "lecture.yaml",
            playlist_dir=tmp_path,
            build_dir=tmp_path / "cache",
            config=config,
            entries=[],
            tts=tts,
            output_path=tmp_path / "lecture.mp4",
            pdf_output_path=tmp_path / "lecture.pdf",
        )

    @patch("slidesonnet.pipeline._generate_srt", return_value=None)
    @patch("slidesonnet.pipeline._run_doit", return_value=1.0)
    @patch("slidesonnet.pipeline._preflight_api_check")
    @patch("slidesonnet.pipeline.generate_tasks", return_value=[])
    @patch("slidesonnet.pipeline._prepare")
    def test_preview_modifies_config(
        self, mock_prepare, mock_gen, mock_preflight, mock_doit, mock_srt, tmp_path
    ):
        """preview=True applies quarter resolution, half fps, ultrafast preset."""
        prep = self._make_prep(tmp_path)
        mock_prepare.return_value = prep

        build(tmp_path / "lecture.yaml", preview=True)

        assert prep.config.video.resolution == "480x270"
        assert prep.config.video.fps == 12
        assert prep.config.video.preset == "ultrafast"
        assert prep.config.video.crf == 32
        assert prep.config.video.crossfade == 0.0
        assert "_preview" in str(prep.output_path)

    @patch("slidesonnet.pipeline._generate_srt", return_value=None)
    @patch("slidesonnet.pipeline._run_doit", return_value=0.5)
    @patch("slidesonnet.pipeline._preflight_api_check")
    @patch("slidesonnet.pipeline.generate_tasks", return_value=[])
    @patch("slidesonnet.pipeline._prepare")
    def test_until_slides_skips_preflight_and_srt(
        self, mock_prepare, mock_gen, mock_preflight, mock_doit, mock_srt, tmp_path
    ):
        """until='slides' skips both preflight API check and SRT generation."""
        prep = self._make_prep(tmp_path)
        mock_prepare.return_value = prep

        result = build(tmp_path / "lecture.yaml", until="slides")

        mock_preflight.assert_not_called()
        mock_srt.assert_not_called()
        assert result.until == "slides"
        assert result.srt_path is None

    @patch("slidesonnet.pipeline._generate_srt")
    @patch("slidesonnet.pipeline._run_doit", return_value=0.5)
    @patch("slidesonnet.pipeline._preflight_api_check")
    @patch("slidesonnet.pipeline.generate_tasks", return_value=[])
    @patch("slidesonnet.pipeline._prepare")
    def test_no_srt_skips_srt_generation(
        self, mock_prepare, mock_gen, mock_preflight, mock_doit, mock_srt, tmp_path
    ):
        """no_srt=True skips SRT generation entirely."""
        prep = self._make_prep(tmp_path)
        mock_prepare.return_value = prep

        result = build(tmp_path / "lecture.yaml", no_srt=True)

        mock_srt.assert_not_called()
        assert result.srt_path is None

    @patch("slidesonnet.pipeline._generate_srt", return_value=None)
    @patch("slidesonnet.pipeline._run_doit", return_value=0.5)
    @patch("slidesonnet.pipeline._preflight_api_check")
    @patch("slidesonnet.pipeline.generate_tasks", return_value=[])
    @patch("slidesonnet.pipeline._prepare")
    def test_allow_api_skips_preflight(
        self, mock_prepare, mock_gen, mock_preflight, mock_doit, mock_srt, tmp_path
    ):
        """allow_api=True skips preflight API check."""
        prep = self._make_prep(tmp_path)
        mock_prepare.return_value = prep

        build(tmp_path / "lecture.yaml", allow_api=True)

        mock_preflight.assert_not_called()


class TestPreflightPiperSkips:
    """Tests for _preflight_api_check with non-API backends."""

    def test_piper_backend_returns_immediately(self) -> None:
        from slidesonnet.pipeline import _preflight_api_check

        config = MagicMock()
        config.tts.backend = "piper"

        prep = _PreparedBuild(
            playlist_path=Path("/fake/lecture.yaml"),
            playlist_dir=Path("/fake"),
            build_dir=Path("/fake/cache"),
            config=config,
            entries=[MagicMock()],  # Would fail if not returned early
            tts=MagicMock(),
            output_path=Path("/fake/lecture.mp4"),
            pdf_output_path=Path("/fake/lecture.pdf"),
        )

        # Should return immediately without parsing entries
        _preflight_api_check(prep)


class TestPreflightSinglePart:
    """Tests for _preflight_api_check with single-part slides."""

    def test_single_part_uncached_raises(self) -> None:
        from slidesonnet.exceptions import APINotAllowedError
        from slidesonnet.models import SlideAnnotation, SlideNarration
        from slidesonnet.pipeline import _preflight_api_check

        config = MagicMock()
        config.tts.backend = "elevenlabs"
        config.pronunciation_for.return_value = {}
        config.voices = {}

        tts = MagicMock()
        tts.name.return_value = "elevenlabs"
        tts.cache_key.return_value = "key123"

        entry = MagicMock()
        entry.module_type = MagicMock()
        entry.path = Path("slides.md")

        prep = _PreparedBuild(
            playlist_path=Path("/fake/lecture.yaml"),
            playlist_dir=Path("/fake"),
            build_dir=Path("/fake/cache"),
            config=config,
            entries=[entry],
            tts=tts,
            output_path=Path("/fake/lecture.mp4"),
            pdf_output_path=Path("/fake/lecture.pdf"),
        )

        # Single-part slide (only narration_raw, no multi-part)
        slide = SlideNarration(
            index=1,
            annotation=SlideAnnotation.SAY,
            narration_raw="Hello from a single part slide.",
            narration_parts=["Hello from a single part slide."],
        )

        with (
            patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.pipeline._audio_cache_exists", return_value=False),
            patch("slidesonnet.pipeline.apply_pronunciation", side_effect=lambda t, _: t),
        ):
            parser = MagicMock()
            parser.parse.return_value = [slide]
            mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())

            with pytest.raises(APINotAllowedError) as exc_info:
                _preflight_api_check(prep)

            msg = str(exc_info.value)
            assert "1 uncached slide" in msg
            assert "Hello from a single part slide" in msg

    def test_plural_message_for_multiple_uncached(self) -> None:
        from slidesonnet.exceptions import APINotAllowedError
        from slidesonnet.models import SlideAnnotation, SlideNarration
        from slidesonnet.pipeline import _preflight_api_check

        config = MagicMock()
        config.tts.backend = "elevenlabs"
        config.pronunciation_for.return_value = {}
        config.voices = {}

        tts = MagicMock()
        tts.name.return_value = "elevenlabs"
        tts.cache_key.return_value = "key123"

        entry = MagicMock()
        entry.module_type = MagicMock()
        entry.path = Path("slides.md")

        prep = _PreparedBuild(
            playlist_path=Path("/fake/lecture.yaml"),
            playlist_dir=Path("/fake"),
            build_dir=Path("/fake/cache"),
            config=config,
            entries=[entry],
            tts=tts,
            output_path=Path("/fake/lecture.mp4"),
            pdf_output_path=Path("/fake/lecture.pdf"),
        )

        slides = [
            SlideNarration(
                index=i,
                annotation=SlideAnnotation.SAY,
                narration_raw=f"Slide {i} text.",
                narration_parts=[f"Slide {i} text."],
            )
            for i in range(1, 4)
        ]

        with (
            patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.pipeline._audio_cache_exists", return_value=False),
            patch("slidesonnet.pipeline.apply_pronunciation", side_effect=lambda t, _: t),
        ):
            parser = MagicMock()
            parser.parse.return_value = slides
            mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())

            with pytest.raises(APINotAllowedError) as exc_info:
                _preflight_api_check(prep)

            msg = str(exc_info.value)
            assert "3 uncached slides" in msg  # plural

    def test_non_narrated_slides_skipped(self) -> None:
        from slidesonnet.models import SlideAnnotation, SlideNarration
        from slidesonnet.pipeline import _preflight_api_check

        config = MagicMock()
        config.tts.backend = "elevenlabs"
        config.pronunciation_for.return_value = {}
        config.voices = {}

        tts = MagicMock()
        tts.name.return_value = "elevenlabs"
        tts.cache_key.return_value = "key123"

        entry = MagicMock()
        entry.module_type = MagicMock()
        entry.path = Path("slides.md")

        prep = _PreparedBuild(
            playlist_path=Path("/fake/lecture.yaml"),
            playlist_dir=Path("/fake"),
            build_dir=Path("/fake/cache"),
            config=config,
            entries=[entry],
            tts=tts,
            output_path=Path("/fake/lecture.mp4"),
            pdf_output_path=Path("/fake/lecture.pdf"),
        )

        # Silent and unannotated slides — no narration
        slides = [
            SlideNarration(index=1, annotation=SlideAnnotation.SILENT),
            SlideNarration(index=2, annotation=SlideAnnotation.NONE),
            SlideNarration(index=3, annotation=SlideAnnotation.SKIP),
        ]

        with (
            patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
        ):
            parser = MagicMock()
            parser.parse.return_value = slides
            mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())

            # Should not raise — no narrated slides
            _preflight_api_check(prep)


def _setup_project_with_voice(tmp_path: Path) -> Path:
    """Create a project with voice annotations (modeled on showcase)."""
    playlist = tmp_path / "lecture.yaml"
    playlist.write_text(
        textwrap.dedent("""\
        title: Test
        tts:
          backend: piper
        voices:
          alex:
            piper: en_US-joe-medium
            elevenlabs: yr43K8H5LoTp6S1QFSGg
        modules:
          - slides.md
    """)
    )
    slides = tmp_path / "slides.md"
    slides.write_text(
        textwrap.dedent("""\
        ---
        marp: true
        ---

        # Default voice

        <!-- say: The default voice narrates. -->

        ---

        # Alex voice

        <!-- say(voice=alex): Alex chimes in. -->
    """)
    )
    return playlist


class TestDryRunWithVoice:
    """Tests for dry_run() with voice annotations."""

    def test_voice_resolution(self, tmp_path: Path) -> None:
        """dry_run resolves voice presets when checking cache."""
        from slidesonnet.pipeline import dry_run

        playlist = _setup_project_with_voice(tmp_path)
        result = dry_run(playlist)

        assert result.total_narrated == 2
        assert result.needs_tts == 2


class TestListSlidesWithVoice:
    """Tests for list_slides() with voice annotations."""

    def test_voice_shown_in_listing(self, tmp_path: Path) -> None:
        """list_slides shows resolved voice for annotated slides."""
        from slidesonnet.pipeline import list_slides

        playlist = _setup_project_with_voice(tmp_path)
        result = list_slides(playlist)

        voices = {s.text: s.voice for s in result.slides if s.cached is not None}
        assert voices["The default voice narrates."] == "default"
        assert voices["Alex chimes in."] == "alex"


class TestExportUtterancesWithVoice:
    """Tests for export_utterances() with voice annotations."""

    def test_voice_included_in_utterance(self, tmp_path: Path) -> None:
        """export_utterances includes voice name for non-default voices."""
        from slidesonnet.pipeline import export_utterances

        playlist = _setup_project_with_voice(tmp_path)
        modules = export_utterances(playlist)

        assert len(modules) == 1
        slides = modules[0].slides
        default_slide = [s for s in slides if s.text == "The default voice narrates."][0]
        alex_slide = [s for s in slides if s.text == "Alex chimes in."][0]
        assert default_slide.voice is None
        assert alex_slide.voice == "alex"


class TestPreflightWithVoice:
    """Tests for _preflight_api_check() with voice annotations."""

    def test_voice_resolved_during_preflight(self) -> None:
        from slidesonnet.exceptions import APINotAllowedError
        from slidesonnet.models import SlideAnnotation, SlideNarration, VoiceConfig
        from slidesonnet.pipeline import _preflight_api_check

        config = MagicMock()
        config.tts.backend = "elevenlabs"
        config.pronunciation_for.return_value = {}
        config.voices = {
            "alex": VoiceConfig(name="alex", backend_voices={"elevenlabs": "yr43K8H5LoTp6S1QFSGg"}),
        }

        tts = MagicMock()
        tts.name.return_value = "elevenlabs"
        tts.cache_key.return_value = "key123"

        entry = MagicMock()
        entry.module_type = MagicMock()
        entry.path = Path("slides.md")

        prep = _PreparedBuild(
            playlist_path=Path("/fake/lecture.yaml"),
            playlist_dir=Path("/fake"),
            build_dir=Path("/fake/cache"),
            config=config,
            entries=[entry],
            tts=tts,
            output_path=Path("/fake/lecture.mp4"),
            pdf_output_path=Path("/fake/lecture.pdf"),
        )

        slide = SlideNarration(
            index=1,
            annotation=SlideAnnotation.SAY,
            narration_raw="Alex chimes in.",
            narration_parts=["Alex chimes in."],
            voice="alex",
        )

        with (
            patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.pipeline._audio_cache_exists", return_value=False),
            patch("slidesonnet.pipeline.apply_pronunciation", side_effect=lambda t, _: t),
        ):
            parser = MagicMock()
            parser.parse.return_value = [slide]
            mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())

            with pytest.raises(APINotAllowedError):
                _preflight_api_check(prep)

            # Voice should have been resolved to the elevenlabs ID
            assert slide.voice == "yr43K8H5LoTp6S1QFSGg"


class TestPreflightUnknownVoice:
    """Tests for _preflight_api_check with unknown voice preset."""

    def test_unknown_voice_cleared_to_none(self) -> None:
        from slidesonnet.exceptions import APINotAllowedError
        from slidesonnet.models import SlideAnnotation, SlideNarration
        from slidesonnet.pipeline import _preflight_api_check

        config = MagicMock()
        config.tts.backend = "elevenlabs"
        config.pronunciation_for.return_value = {}
        config.voices = {}  # no voice presets defined

        tts = MagicMock()
        tts.name.return_value = "elevenlabs"
        tts.cache_key.return_value = "key123"

        entry = MagicMock()
        entry.module_type = MagicMock()
        entry.path = Path("slides.md")

        prep = _PreparedBuild(
            playlist_path=Path("/fake/lecture.yaml"),
            playlist_dir=Path("/fake"),
            build_dir=Path("/fake/cache"),
            config=config,
            entries=[entry],
            tts=tts,
            output_path=Path("/fake/lecture.mp4"),
            pdf_output_path=Path("/fake/lecture.pdf"),
        )

        slide = SlideNarration(
            index=1,
            annotation=SlideAnnotation.SAY,
            narration_raw="Hello.",
            narration_parts=["Hello."],
            voice="nonexistent_voice",
        )

        with (
            patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.pipeline._audio_cache_exists", return_value=False),
            patch("slidesonnet.pipeline.apply_pronunciation", side_effect=lambda t, _: t),
        ):
            parser = MagicMock()
            parser.parse.return_value = [slide]
            mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())

            with pytest.raises(APINotAllowedError):
                _preflight_api_check(prep)

            assert slide.voice is None


class TestDryRunUnknownVoice:
    """Tests for dry_run() with unknown voice preset."""

    def test_unknown_voice_cleared(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import dry_run

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Hello

            <!-- say(voice=nonexistent): Hello there. -->
        """)
        )

        result = dry_run(playlist)
        assert result.needs_tts == 1


class TestPreflightLongText:
    """Tests for preflight error message truncation with long narration."""

    def test_long_text_truncated_in_message(self) -> None:
        from slidesonnet.exceptions import APINotAllowedError
        from slidesonnet.models import SlideAnnotation, SlideNarration
        from slidesonnet.pipeline import _preflight_api_check

        config = MagicMock()
        config.tts.backend = "elevenlabs"
        config.pronunciation_for.return_value = {}
        config.voices = {}

        tts = MagicMock()
        tts.name.return_value = "elevenlabs"
        tts.cache_key.return_value = "key123"

        entry = MagicMock()
        entry.module_type = MagicMock()
        entry.path = Path("slides.md")

        prep = _PreparedBuild(
            playlist_path=Path("/fake/lecture.yaml"),
            playlist_dir=Path("/fake"),
            build_dir=Path("/fake/cache"),
            config=config,
            entries=[entry],
            tts=tts,
            output_path=Path("/fake/lecture.mp4"),
            pdf_output_path=Path("/fake/lecture.pdf"),
        )

        long_text = "A" * 120  # well over 80 chars
        slide = SlideNarration(
            index=1,
            annotation=SlideAnnotation.SAY,
            narration_raw=long_text,
            narration_parts=[long_text],
        )

        with (
            patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.pipeline._audio_cache_exists", return_value=False),
            patch("slidesonnet.pipeline.apply_pronunciation", side_effect=lambda t, _: t),
        ):
            parser = MagicMock()
            parser.parse.return_value = [slide]
            mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())

            with pytest.raises(APINotAllowedError) as exc_info:
                _preflight_api_check(prep)

            msg = str(exc_info.value)
            assert "..." in msg
            # Full text should NOT appear — truncated to 77 + "..."
            assert long_text not in msg


class TestListSlidesVideoAndSkip:
    """Tests for list_slides() with video and skip slides."""

    def test_video_entry_skipped(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import list_slides

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - intro.mp4
              - slides.md
        """)
        )
        (tmp_path / "intro.mp4").touch()
        slides = tmp_path / "slides.md"
        slides.write_text("---\nmarp: true\n---\n# Hello\n<!-- say: Hi. -->\n")

        result = list_slides(playlist)

        assert len(result.slides) == 1
        assert result.slides[0].text == "Hi."

    def test_skip_slide_excluded(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import list_slides

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.md
        """)
        )
        slides = tmp_path / "slides.md"
        slides.write_text(
            textwrap.dedent("""\
            ---
            marp: true
            ---

            # Visible

            <!-- say: Hello. -->

            ---

            # Skipped

            <!-- skip -->
        """)
        )

        result = list_slides(playlist)

        assert len(result.slides) == 1
        assert result.slides[0].text == "Hello."


class TestExportPdfsBeamer:
    """Tests for export_pdfs() with Beamer modules."""

    def test_beamer_module(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import export_pdfs

        playlist = tmp_path / "lecture.yaml"
        playlist.write_text(
            textwrap.dedent("""\
            title: Test
            tts:
              backend: piper
            modules:
              - slides.tex
        """)
        )
        slides = tmp_path / "slides.tex"
        slides.write_text("\\documentclass{beamer}\n\\begin{document}\n\\end{document}\n")

        def _fake_compile(source, slides_dir, compiled_pdf):
            compiled_pdf.parent.mkdir(parents=True, exist_ok=True)
            compiled_pdf.write_bytes(b"%PDF-1.4 compiled")

        def _fake_export_beamer(compiled_pdf, cache_pdf):
            cache_pdf.parent.mkdir(parents=True, exist_ok=True)
            cache_pdf.write_bytes(b"%PDF-1.4 exported")

        def _fake_concat(pdfs, output):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"%PDF-1.4 concat")

        with (
            patch("slidesonnet.actions.action_compile_beamer", side_effect=_fake_compile),
            patch("slidesonnet.actions.action_export_pdf_beamer", side_effect=_fake_export_beamer),
            patch("slidesonnet.actions.action_concat_pdfs", side_effect=_fake_concat),
        ):
            result = export_pdfs(playlist)

        assert result.exists()
        assert result.suffix == ".pdf"


class TestGenerateSrtInternal:
    """Tests for _generate_srt() internal behavior."""

    def test_empty_entries_returns_none(self, tmp_path: Path) -> None:
        from slidesonnet.pipeline import _generate_srt

        prep = _PreparedBuild(
            playlist_path=tmp_path / "lecture.yaml",
            playlist_dir=tmp_path,
            build_dir=tmp_path / "cache",
            config=MagicMock(),
            entries=[],
            tts=MagicMock(),
            output_path=tmp_path / "lecture.mp4",
            pdf_output_path=tmp_path / "lecture.pdf",
        )

        with patch("slidesonnet.subtitles.generate_subtitles", return_value=[]):
            result = _generate_srt(prep)

        assert result is None
