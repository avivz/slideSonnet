"""Tests for the preflight API check in the build pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import APINotAllowedError
from slidesonnet.models import SlideAnnotation, SlideNarration
from slidesonnet.pipeline import _PreparedBuild, _preflight_api_check


def _make_prep(
    backend: str = "elevenlabs",
    slides: list[SlideNarration] | None = None,
    cached_paths: set[str] | None = None,
) -> _PreparedBuild:
    """Build a minimal _PreparedBuild with mocked components."""
    config = MagicMock()
    config.tts.backend = backend
    config.pronunciation_for.return_value = {}
    config.voices = {}

    tts = MagicMock()
    tts.name.return_value = backend
    tts.cache_key.return_value = "key123"

    entry = MagicMock()
    entry.module_type = MagicMock()
    entry.module_type.value = "marp"
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
    return prep


def _patch_preflight(
    slides: list[SlideNarration],
    cached_paths: set[str] | None = None,
):
    """Return a context manager that patches parser and cache for preflight tests."""
    from contextlib import contextmanager
    from unittest.mock import patch

    @contextmanager
    def _ctx():
        # Patch ModuleType.VIDEO to never match our mock entry
        with (
            patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.pipeline._audio_cache_exists") as mock_cache,
            patch("slidesonnet.pipeline.apply_pronunciation", side_effect=lambda t, _: t),
        ):
            parser = MagicMock()
            parser.parse.return_value = slides
            mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())

            # Make ModuleType.VIDEO check pass — our mock entry should NOT be VIDEO
            if cached_paths is not None:
                mock_cache.side_effect = lambda p: str(p) in cached_paths
            else:
                mock_cache.return_value = False

            yield

    return _ctx()


class TestPreflightAPICheck:
    """Tests for _preflight_api_check()."""

    def test_piper_always_passes(self):
        """Piper backend never raises, even with uncached slides."""
        prep = _make_prep(backend="piper")
        slides = [
            SlideNarration(index=1, annotation=SlideAnnotation.SAY, narration_raw="Hello world"),
        ]
        with _patch_preflight(slides):
            # Should not raise
            _preflight_api_check(prep)

    def test_elevenlabs_all_cached_passes(self):
        """ElevenLabs with all slides cached does not raise."""
        prep = _make_prep(backend="elevenlabs")
        slides = [
            SlideNarration(index=1, annotation=SlideAnnotation.SAY, narration_raw="Hello world"),
        ]
        with _patch_preflight(slides, cached_paths={"dummy"}):
            with patch("slidesonnet.pipeline._audio_cache_exists", return_value=True):
                with (
                    patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
                    patch("slidesonnet.pipeline.apply_pronunciation", side_effect=lambda t, _: t),
                ):
                    parser = MagicMock()
                    parser.parse.return_value = slides
                    mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())
                    _preflight_api_check(prep)

    def test_elevenlabs_uncached_raises(self):
        """ElevenLabs with uncached slides raises APINotAllowedError."""
        prep = _make_prep(backend="elevenlabs")
        slides = [
            SlideNarration(index=1, annotation=SlideAnnotation.SAY, narration_raw="Hello world"),
            SlideNarration(
                index=2, annotation=SlideAnnotation.SAY, narration_raw="Second slide text"
            ),
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
            assert "2 uncached slides" in msg
            assert "ElevenLabs API calls" in msg
            assert "--allow-api" in msg
            assert "--tts piper" in msg

    def test_error_message_contains_slide_details(self):
        """Error message includes module path, slide index, text preview, char count."""
        prep = _make_prep(backend="elevenlabs")
        slides = [
            SlideNarration(
                index=3,
                annotation=SlideAnnotation.SAY,
                narration_raw="This is a narration for slide three",
            ),
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
            assert "01-intro/slides.md" in msg
            assert "slide 3" in msg
            assert "This is a narration" in msg
            assert "35 characters" in msg or "35" in msg

    def test_silent_slides_ignored(self):
        """Silent and unannotated slides don't trigger the check."""
        prep = _make_prep(backend="elevenlabs")
        slides = [
            SlideNarration(index=1, annotation=SlideAnnotation.SILENT),
            SlideNarration(index=2, annotation=SlideAnnotation.SKIP),
            SlideNarration(index=3, annotation=SlideAnnotation.NONE),
        ]
        with (
            patch("slidesonnet.pipeline.get_parser_and_extractor") as mock_gpe,
            patch("slidesonnet.pipeline._audio_cache_exists", return_value=False),
            patch("slidesonnet.pipeline.apply_pronunciation", side_effect=lambda t, _: t),
        ):
            parser = MagicMock()
            parser.parse.return_value = slides
            mock_gpe.return_value = (MagicMock(return_value=parser), MagicMock())

            # Should not raise — no narrated slides
            _preflight_api_check(prep)
