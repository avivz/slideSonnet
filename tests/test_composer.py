"""Tests for video composer — integration (require ffmpeg) and mocked unit tests."""

import json
import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.video.composer import (
    _run_ffmpeg,
    compose_segment,
    compose_silent_segment,
    concatenate_segments,
    concatenate_segments_xfade,
    get_duration,
)


def _make_wav(path: Path, duration_seconds: float = 1.0) -> None:
    """Create a simple WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * int(44100 * duration_seconds))


def _make_png(path: Path, width: int = 200, height: int = 100) -> None:
    """Create a minimal valid PNG file."""
    import struct
    import zlib

    path.parent.mkdir(parents=True, exist_ok=True)

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # Create a minimal image: blue pixels
    raw_data = b""
    for _ in range(height):
        raw_data += b"\x00" + (b"\x00\x00\xff") * width  # filter byte + RGB
    idat = zlib.compress(raw_data)

    with open(path, "wb") as f:
        f.write(signature)
        f.write(_chunk(b"IHDR", ihdr))
        f.write(_chunk(b"IDAT", idat))
        f.write(_chunk(b"IEND", b""))


@pytest.fixture
def work_dir(tmp_path):
    return tmp_path / "composer_test"


def test_compose_segment(work_dir):
    image = work_dir / "slide.png"
    audio = work_dir / "audio.wav"
    output = work_dir / "segment.mp4"

    _make_png(image)
    _make_wav(audio, duration_seconds=2.0)

    compose_segment(
        image=image,
        audio=audio,
        output=output,
        duration=2.0,
        pad_seconds=0.5,
        resolution="640x480",
        fps=24,
        crf=28,
    )

    assert output.exists()
    dur = get_duration(output)
    assert 2.0 <= dur <= 3.0  # 2s audio + 0.5s pad, with tolerance


def test_compose_silent_segment(work_dir):
    image = work_dir / "slide.png"
    output = work_dir / "silent.mp4"

    _make_png(image)

    compose_silent_segment(
        image=image,
        output=output,
        duration=3.0,
        resolution="640x480",
        fps=24,
        crf=28,
    )

    assert output.exists()
    dur = get_duration(output)
    assert 2.5 <= dur <= 3.5


def test_concatenate_segments(work_dir):
    segments = []
    for i in range(3):
        image = work_dir / f"slide_{i}.png"
        audio = work_dir / f"audio_{i}.wav"
        seg = work_dir / f"seg_{i}.mp4"
        _make_png(image)
        _make_wav(audio, duration_seconds=1.0)
        compose_segment(
            image=image,
            audio=audio,
            output=seg,
            duration=1.0,
            pad_seconds=0.0,
            pre_silence=0.0,
            resolution="640x480",
            fps=24,
            crf=28,
        )
        segments.append(seg)

    output = work_dir / "final.mp4"
    concatenate_segments(segments, output)

    assert output.exists()
    dur = get_duration(output)
    assert 2.5 <= dur <= 4.0  # ~3s total with tolerance


def test_get_duration_nonexistent():
    assert get_duration(Path("/nonexistent.mp4")) == 0.0


# ---- Mocked unit tests (no ffmpeg required) ----


class TestComposeSegmentMocked:
    """Mocked tests for compose_segment()."""

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_command_structure(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        image = tmp_path / "slide.png"
        audio = tmp_path / "audio.wav"
        output = tmp_path / "out" / "segment.mp4"
        image.touch()
        audio.touch()

        compose_segment(
            image=image,
            audio=audio,
            output=output,
            duration=3.0,
            pad_seconds=0.5,
            resolution="1920x1080",
            fps=24,
            crf=23,
        )

        mock_ffmpeg.assert_called_once()
        cmd = mock_ffmpeg.call_args[0][0]

        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        assert str(image) in cmd
        assert str(audio) in cmd
        assert str(output) in cmd

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_scale_filter(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        compose_segment(
            image=tmp_path / "s.png",
            audio=tmp_path / "a.wav",
            output=tmp_path / "o.mp4",
            duration=1.0,
            resolution="1280x720",
        )
        cmd = mock_ffmpeg.call_args[0][0]
        vf_idx = cmd.index("-vf")
        scale_filter = cmd[vf_idx + 1]
        assert "scale=1280:720" in scale_filter
        assert "pad=1280:720" in scale_filter
        assert "yuv420p" in scale_filter

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_duration_includes_padding(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        compose_segment(
            image=tmp_path / "s.png",
            audio=tmp_path / "a.wav",
            output=tmp_path / "o.mp4",
            duration=2.0,
            pad_seconds=0.7,
            pre_silence=0.5,
        )
        cmd = mock_ffmpeg.call_args[0][0]
        t_idx = cmd.index("-t")
        assert cmd[t_idx + 1] == str(3.2)  # pre_silence + duration + pad

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_codec_flags(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        compose_segment(
            image=tmp_path / "s.png",
            audio=tmp_path / "a.wav",
            output=tmp_path / "o.mp4",
            duration=1.0,
            fps=30,
            crf=18,
        )
        cmd = mock_ffmpeg.call_args[0][0]
        assert "libx264" in cmd
        assert "aac" in cmd
        r_idx = cmd.index("-r")
        assert cmd[r_idx + 1] == "30"
        crf_idx = cmd.index("-crf")
        assert cmd[crf_idx + 1] == "18"

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_creates_output_dir(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        output = tmp_path / "deep" / "dir" / "out.mp4"
        compose_segment(
            image=tmp_path / "s.png",
            audio=tmp_path / "a.wav",
            output=output,
            duration=1.0,
        )
        assert output.parent.exists()


class TestComposeSilentSegmentMocked:
    """Mocked tests for compose_silent_segment()."""

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_command_has_anullsrc(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        compose_silent_segment(
            image=tmp_path / "s.png",
            output=tmp_path / "o.mp4",
            duration=3.0,
            resolution="1920x1080",
        )
        cmd = mock_ffmpeg.call_args[0][0]
        assert "anullsrc=r=44100:cl=stereo" in cmd
        assert "-f" in cmd

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_duration_flag(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        compose_silent_segment(
            image=tmp_path / "s.png",
            output=tmp_path / "o.mp4",
            duration=5.0,
        )
        cmd = mock_ffmpeg.call_args[0][0]
        t_idx = cmd.index("-t")
        assert cmd[t_idx + 1] == "5.0"

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_no_shortest_flag(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        compose_silent_segment(
            image=tmp_path / "s.png",
            output=tmp_path / "o.mp4",
            duration=1.0,
        )
        cmd = mock_ffmpeg.call_args[0][0]
        assert "-shortest" not in cmd


class TestConcatenateSegmentsMocked:
    """Mocked tests for concatenate_segments()."""

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_writes_concat_file_and_cleans_up(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        output = tmp_path / "out.mp4"

        concatenate_segments(segs, output)

        mock_ffmpeg.assert_called_once()
        cmd = mock_ffmpeg.call_args[0][0]
        assert "concat" in cmd
        assert "-safe" in cmd
        assert "copy" in cmd

        # Concat file should be cleaned up after run
        concat_file = tmp_path / "concat_list.txt"
        assert not concat_file.exists()

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_concat_file_contents(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        output = tmp_path / "out.mp4"
        concat_file = tmp_path / "concat_list.txt"

        # Capture concat file contents before cleanup
        written_content: list[str] = []

        def capture_and_run(cmd: list[str]) -> None:
            if concat_file.exists():
                written_content.append(concat_file.read_text())

        mock_ffmpeg.side_effect = capture_and_run

        concatenate_segments(segs, output)

        assert len(written_content) == 1
        for seg in segs:
            assert str(seg.resolve()) in written_content[0]


class TestGetDurationMocked:
    """Mocked tests for get_duration()."""

    @patch("slidesonnet.video.composer.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=json.dumps({"format": {"duration": "12.345"}}))
        assert get_duration(Path("test.mp4")) == pytest.approx(12.345)

    @patch("slidesonnet.video.composer.subprocess.run", side_effect=FileNotFoundError)
    def test_ffprobe_not_found(self, mock_run: MagicMock) -> None:
        assert get_duration(Path("test.mp4")) == 0.0

    @patch(
        "slidesonnet.video.composer.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "ffprobe"),
    )
    def test_ffprobe_error(self, mock_run: MagicMock) -> None:
        assert get_duration(Path("test.mp4")) == 0.0

    @patch("slidesonnet.video.composer.subprocess.run")
    def test_bad_json(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="not json")
        assert get_duration(Path("test.mp4")) == 0.0

    @patch("slidesonnet.video.composer.subprocess.run")
    def test_missing_key(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=json.dumps({"format": {}}))
        assert get_duration(Path("test.mp4")) == 0.0

    @patch("slidesonnet.video.composer.subprocess.run")
    def test_non_numeric_duration(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=json.dumps({"format": {"duration": "N/A"}}))
        assert get_duration(Path("test.mp4")) == 0.0


class TestConcatenateSegmentsXfadeMocked:
    """Mocked tests for concatenate_segments_xfade()."""

    @patch("slidesonnet.video.composer.get_duration", return_value=5.0)
    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_filter_chain_structure(
        self, mock_ffmpeg: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
        output = tmp_path / "out.mp4"

        concatenate_segments_xfade(segs, output, crossfade=0.5, crf=20)

        mock_ffmpeg.assert_called_once()
        cmd = mock_ffmpeg.call_args[0][0]
        fc_idx = cmd.index("-filter_complex")
        fc = cmd[fc_idx + 1]

        # Should have 2 xfade + 2 acrossfade for 3 segments
        assert fc.count("xfade") == 2
        assert fc.count("acrossfade") == 2

    @patch("slidesonnet.video.composer.get_duration", return_value=5.0)
    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_offsets(self, mock_ffmpeg: MagicMock, mock_dur: MagicMock, tmp_path: Path) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
        output = tmp_path / "out.mp4"

        concatenate_segments_xfade(segs, output, crossfade=0.5, crf=23)

        cmd = mock_ffmpeg.call_args[0][0]
        fc_idx = cmd.index("-filter_complex")
        fc = cmd[fc_idx + 1]

        # First offset: D0(5.0) - 0.5 = 4.5
        assert "offset=4.500000" in fc
        # Second offset: 4.5 + D1(5.0) - 0.5 = 9.0
        assert "offset=9.000000" in fc

    @patch("slidesonnet.video.composer.get_duration", return_value=5.0)
    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_codecs(self, mock_ffmpeg: MagicMock, mock_dur: MagicMock, tmp_path: Path) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        output = tmp_path / "out.mp4"

        concatenate_segments_xfade(segs, output, crossfade=0.5, crf=18)

        cmd = mock_ffmpeg.call_args[0][0]
        assert "libx264" in cmd
        assert "aac" in cmd
        crf_idx = cmd.index("-crf")
        assert cmd[crf_idx + 1] == "18"

    @patch("slidesonnet.video.composer.get_duration", return_value=5.0)
    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_creates_output_dir(
        self, mock_ffmpeg: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        output = tmp_path / "deep" / "dir" / "out.mp4"

        concatenate_segments_xfade(segs, output, crossfade=0.5)

        assert output.parent.exists()

    @patch("slidesonnet.video.composer.get_duration", return_value=0.3)
    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_offset_clamped_to_zero(
        self, mock_ffmpeg: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        """When duration < crossfade, offset should be clamped to 0."""
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        output = tmp_path / "out.mp4"

        concatenate_segments_xfade(segs, output, crossfade=0.5)

        cmd = mock_ffmpeg.call_args[0][0]
        fc_idx = cmd.index("-filter_complex")
        fc = cmd[fc_idx + 1]
        assert "offset=0.000000" in fc

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_single_segment_copies(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        seg = tmp_path / "only.mp4"
        seg.write_bytes(b"video-data")
        output = tmp_path / "out.mp4"

        concatenate_segments_xfade([seg], output, crossfade=0.5)

        mock_ffmpeg.assert_not_called()
        assert output.read_bytes() == b"video-data"

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_empty_segments_noop(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        output = tmp_path / "out.mp4"

        concatenate_segments_xfade([], output, crossfade=0.5)

        mock_ffmpeg.assert_not_called()
        assert not output.exists()

    @patch("slidesonnet.video.composer.get_duration", return_value=5.0)
    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_maps_final_labels(
        self, mock_ffmpeg: MagicMock, mock_dur: MagicMock, tmp_path: Path
    ) -> None:
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        output = tmp_path / "out.mp4"

        concatenate_segments_xfade(segs, output, crossfade=0.5)

        cmd = mock_ffmpeg.call_args[0][0]
        # Final map labels should be [v1] and [a1]
        map_indices = [i for i, v in enumerate(cmd) if v == "-map"]
        assert len(map_indices) == 2
        assert cmd[map_indices[0] + 1] == "[v1]"
        assert cmd[map_indices[1] + 1] == "[a1]"


class TestRunFfmpeg:
    """Mocked tests for _run_ffmpeg()."""

    @patch("slidesonnet.video.composer.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        _run_ffmpeg(["ffmpeg", "-version"])
        mock_run.assert_called_once_with(
            ["ffmpeg", "-version"], check=True, capture_output=True, text=True
        )

    @patch("slidesonnet.video.composer.subprocess.run", side_effect=FileNotFoundError)
    def test_ffmpeg_not_found(self, mock_run: MagicMock) -> None:
        with pytest.raises(SystemExit, match="1"):
            _run_ffmpeg(["ffmpeg", "-version"])

    @patch(
        "slidesonnet.video.composer.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr="encode failed"),
    )
    def test_ffmpeg_error(self, mock_run: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit, match="1"):
            _run_ffmpeg(["ffmpeg", "-i", "in.mp4"])
        captured = capsys.readouterr()
        assert "encode failed" in captured.err
