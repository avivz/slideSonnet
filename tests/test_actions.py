"""Tests for action functions in actions.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.models import ModuleType, ProjectConfig, VideoConfig


class TestActionExtractImages:
    def test_writes_manifest_json(self, tmp_path: Path) -> None:
        from slidesonnet.actions import action_extract_images

        slides_dir = tmp_path / "slides"
        manifest = tmp_path / "manifest.json"
        fake_images = [tmp_path / "img1.png", tmp_path / "img2.png"]
        extract_fn = MagicMock(return_value=fake_images)

        action_extract_images(tmp_path / "src.md", slides_dir, extract_fn, manifest)

        assert manifest.exists()
        data = json.loads(manifest.read_text())
        assert data == [str(p) for p in fake_images]
        extract_fn.assert_called_once_with(tmp_path / "src.md", slides_dir)


class TestActionTts:
    def test_writes_utterance_and_calls_synthesize(self, tmp_path: Path) -> None:
        from slidesonnet.actions import action_tts

        output = tmp_path / "audio.mp3"
        utterance = tmp_path / "utterance.txt"
        tts = MagicMock()

        action_tts("Hello world", output, tts, utterance)

        assert utterance.read_text() == "Hello world"
        tts.synthesize.assert_called_once_with("Hello world", output, voice=None)

    def test_passes_voice_parameter(self, tmp_path: Path) -> None:
        from slidesonnet.actions import action_tts

        output = tmp_path / "audio.mp3"
        utterance = tmp_path / "utterance.txt"
        tts = MagicMock()

        action_tts("Hi", output, tts, utterance, voice="alice")

        tts.synthesize.assert_called_once_with("Hi", output, voice="alice")


class TestActionConcatAudio:
    @patch("slidesonnet.actions.composer")
    def test_delegates_to_composer(self, mock_composer: MagicMock, tmp_path: Path) -> None:
        from slidesonnet.actions import action_concat_audio

        paths = [tmp_path / "a.wav", tmp_path / "b.wav"]
        output = tmp_path / "out.wav"

        action_concat_audio(paths, output)

        mock_composer.concatenate_audio.assert_called_once_with(paths, output)


class TestActionComposeNarrated:
    @patch("slidesonnet.actions.composer")
    def test_reads_manifest_and_composes(self, mock_composer: MagicMock, tmp_path: Path) -> None:
        from slidesonnet.actions import action_compose_narrated

        img1 = tmp_path / "img1.png"
        img2 = tmp_path / "img2.png"
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps([str(img1), str(img2)]))
        audio = tmp_path / "audio.mp3"
        output = tmp_path / "segment.mp4"
        config = ProjectConfig(
            video=VideoConfig(
                pad_seconds=1.0,
                pre_silence=0.5,
                resolution="1280x720",
                fps=30,
                crf=20,
                preset="fast",
            )
        )
        mock_composer.get_duration.return_value = 5.0

        action_compose_narrated(
            manifest, slide_index=2, audio_path=audio, output=output, config=config
        )

        # slide_index=2 → images[1] (0-based)
        mock_composer.get_duration.assert_called_once_with(audio)
        call_kwargs = mock_composer.compose_segment.call_args
        assert call_kwargs.kwargs["image"] == img2
        assert call_kwargs.kwargs["duration"] == 5.0
        assert call_kwargs.kwargs["pad_seconds"] == 1.0
        assert call_kwargs.kwargs["pre_silence"] == 0.5
        assert call_kwargs.kwargs["resolution"] == "1280x720"
        assert call_kwargs.kwargs["fps"] == 30


class TestActionComposeSilent:
    @patch("slidesonnet.actions.composer")
    def test_uses_config_silence_duration(self, mock_composer: MagicMock, tmp_path: Path) -> None:
        from slidesonnet.actions import action_compose_silent

        img = tmp_path / "img.png"
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps([str(img)]))
        config = ProjectConfig(video=VideoConfig(silence_duration=4.0))

        action_compose_silent(
            manifest,
            slide_index=1,
            output=tmp_path / "out.mp4",
            config=config,
            silence_override=None,
        )

        assert mock_composer.compose_silent_segment.call_args.kwargs["duration"] == 4.0

    @patch("slidesonnet.actions.composer")
    def test_uses_silence_override(self, mock_composer: MagicMock, tmp_path: Path) -> None:
        from slidesonnet.actions import action_compose_silent

        img = tmp_path / "img.png"
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps([str(img)]))
        config = ProjectConfig(video=VideoConfig(silence_duration=4.0))

        action_compose_silent(
            manifest,
            slide_index=1,
            output=tmp_path / "out.mp4",
            config=config,
            silence_override=7.5,
        )

        assert mock_composer.compose_silent_segment.call_args.kwargs["duration"] == 7.5


class TestActionAssemble:
    def test_empty_segments_raises(self, tmp_path: Path) -> None:
        from slidesonnet.actions import action_assemble

        config = ProjectConfig()
        with pytest.raises(RuntimeError, match="No segments to assemble"):
            action_assemble([], tmp_path / "out.mp4", config)


class TestMergeVideos:
    @patch("slidesonnet.actions.shutil")
    def test_single_segment_copies(self, mock_shutil: MagicMock, tmp_path: Path) -> None:
        from slidesonnet.actions import _merge_videos

        seg = tmp_path / "seg.mp4"
        output = tmp_path / "output" / "out.mp4"
        config = ProjectConfig()

        _merge_videos([seg], output, config)

        mock_shutil.copy2.assert_called_once_with(seg, output)

    @patch("slidesonnet.actions.composer")
    def test_multiple_with_crossfade(self, mock_composer: MagicMock, tmp_path: Path) -> None:
        from slidesonnet.actions import _merge_videos

        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        output = tmp_path / "out.mp4"
        config = ProjectConfig(video=VideoConfig(crossfade=0.5))

        _merge_videos(segs, output, config)

        mock_composer.concatenate_segments_xfade.assert_called_once()
        mock_composer.concatenate_segments.assert_not_called()

    @patch("slidesonnet.actions.composer")
    def test_multiple_without_crossfade(self, mock_composer: MagicMock, tmp_path: Path) -> None:
        from slidesonnet.actions import _merge_videos

        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        output = tmp_path / "out.mp4"
        config = ProjectConfig(video=VideoConfig(crossfade=0))

        _merge_videos(segs, output, config)

        mock_composer.concatenate_segments.assert_called_once()
        mock_composer.concatenate_segments_xfade.assert_not_called()


class TestGetParserAndExtractor:
    def test_marp(self) -> None:
        from slidesonnet.actions import get_parser_and_extractor
        from slidesonnet.parsers.marp import MarpParser

        parser_cls, _ = get_parser_and_extractor(ModuleType.MARP)
        assert parser_cls is MarpParser

    def test_beamer(self) -> None:
        from slidesonnet.actions import get_parser_and_extractor
        from slidesonnet.parsers.beamer import BeamerParser

        parser_cls, _ = get_parser_and_extractor(ModuleType.BEAMER)
        assert parser_cls is BeamerParser

    def test_video_raises(self) -> None:
        from slidesonnet.actions import get_parser_and_extractor

        with pytest.raises(ValueError, match="No parser for module type"):
            get_parser_and_extractor(ModuleType.VIDEO)
