"""Tests for video composer — integration (require ffmpeg) and mocked unit tests."""

import json
import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import FFmpegError
from slidesonnet.video.composer import (
    _run_ffmpeg,
    compose_silent_segment,
    compose_transition_clip,
    concatenate_audio,
    concatenate_segments,
    get_duration,
    mux_copy,
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


@pytest.mark.integration
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
    # expected: 3.0s
    assert 2.9 <= dur <= 3.1


@pytest.mark.integration
def test_concatenate_segments_path_with_apostrophe(tmp_path):
    """A deck under a folder like O'Brien's must still concatenate."""
    work = tmp_path / "O'Brien's talk"
    segs = []
    for i in range(2):
        _gray_png(work / f"s{i}.png", 60 + 60 * i)
        segs.append(work / "segments" / f"seg-{i}.mp4")
        compose_silent_segment(
            work / f"s{i}.png", segs[-1], duration=0.5, resolution="16x16", preset="ultrafast"
        )
    out = work / "deck.mp4"
    concatenate_segments(segs, out)
    assert get_duration(out) == pytest.approx(1.0, abs=1 / 24)


def _pix_fmt(path: Path) -> str:
    """Probe a video file's pixel format via ffprobe."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=pix_fmt",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


@pytest.mark.integration
def test_compose_transition_clip_duration(work_dir):
    a = work_dir / "a.png"
    b = work_dir / "b.png"
    _make_png(a)
    _make_png(b)
    out = work_dir / "trans.mp4"
    compose_transition_clip(
        a, b, out, duration=0.5, transition="wipeleft", resolution="640x480", crf=30
    )
    assert out.exists()
    assert 0.4 <= get_duration(out) <= 0.7


@pytest.mark.integration
def test_compose_transition_clip_is_yuv420p(work_dir):
    """Transition clips must encode as yuv420p, matching the slide segments.

    xfade renegotiates the filter-graph format and, left unpinned, emits a
    yuv444p (High 4:4:4 Predictive) stream. Concatenated by stream-copy with the
    yuv420p slide segments, that yields a non-uniform H.264 stream that Windows'
    H.264 decoder (4:2:0 only) rejects mid-playback with "unsupported codec
    settings" — even though ffmpeg/VLC tolerate it. Pin yuv420p so every segment
    is uniform and the muxed deck plays everywhere.
    """
    a = work_dir / "a.png"
    b = work_dir / "b.png"
    _make_png(a)
    _make_png(b)
    seg = work_dir / "seg.mp4"
    trans = work_dir / "trans.mp4"
    compose_silent_segment(a, seg, duration=0.5, resolution="640x480", crf=30)
    compose_transition_clip(
        a, b, trans, duration=0.5, transition="wipeleft", resolution="640x480", crf=30
    )
    assert _pix_fmt(trans) == "yuv420p"
    # …and it matches the slide segments it gets concatenated with.
    assert _pix_fmt(trans) == _pix_fmt(seg)


@pytest.mark.integration
def test_compose_video_absorbs_transition_into_hold(work_dir):
    """A transition is absorbed into the slide's tail hold, so the deck's total
    length is unchanged vs an all-cut render — and a morph clip is produced."""
    from slidesonnet.config import Config
    from slidesonnet.models import VideoConfig
    from slidesonnet.narration.model import Transition
    from slidesonnet.render import DeckTimeline, compose_video
    from slidesonnet.timing import PageTiming

    images = []
    audios = []
    for i in range(2):
        img = work_dir / f"img{i}.png"
        aud = work_dir / f"a{i}.wav"
        _make_png(img)
        _make_wav(aud, duration_seconds=2.0)
        images.append(img)
        audios.append(aud)
    tl = DeckTimeline(
        pages=[
            PageTiming(slide_id="a", duration=2.0, lead=0.3, tail=0.5),
            PageTiming(slide_id="b", duration=2.0, lead=0.3, tail=0.5),
        ]
    )
    config = Config(video=VideoConfig(resolution="640x480", crf=30))
    rdir = work_dir / "r"

    cut_out = work_dir / "cut.mp4"
    compose_video(tl, images, cut_out, config=config, page_audios=audios, render_dir=rdir / "cut")
    wipe_out = work_dir / "wipe.mp4"
    compose_video(
        tl,
        images,
        wipe_out,
        config=config,
        page_audios=audios,
        render_dir=rdir / "wipe",
        transitions=[Transition("wipeleft", 0.5)],
    )

    assert abs(get_duration(cut_out) - get_duration(wipe_out)) <= 0.25
    clips = [len(list((rdir / d / "clips").glob("*.mp4"))) for d in ("cut", "wipe")]
    assert clips == [1, 2]  # the two (identical) stills share a clip; the wipe adds its morph


@pytest.mark.integration
def test_get_duration_nonexistent():
    with pytest.raises(FFmpegError, match="ffprobe failed"):
        get_duration(Path("/nonexistent.mp4"))


def _gray_png(path: Path, level: int) -> None:
    """A 16x16 still of one gray *level*, so decoded frames say which slide they show."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{level:02x}{level:02x}{level:02x}:s=16x16",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
    )


def _frame_levels(video: Path) -> list[int]:
    """The mean luma of every decoded frame of *video*, in order."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    return list(raw)


@pytest.mark.integration
def test_compose_video_slide_boundaries_never_drift(work_dir):
    """Each slide starts on the frame nearest its true start, however late in the deck.

    Non-frame-aligned page lengths are the case that drifted: every segment was
    rounded to whole frames on its own and carried a silent AAC stream that the
    concat stretched it by, so the slides fell ~20 ms a page behind the audio.
    """
    from slidesonnet.config import Config
    from slidesonnet.models import VideoConfig
    from slidesonnet.render import DeckTimeline, compose_video
    from slidesonnet.timing import PageTiming

    fps = 24
    lengths = [0.37 + 0.13 * i for i in range(12)]  # none a whole number of frames
    levels = [30 + 16 * i for i in range(12)]
    images, audios = [], []
    for i, (secs, level) in enumerate(zip(lengths, levels, strict=True)):
        images.append(work_dir / f"s{i}.png")
        _gray_png(images[-1], level)
        audios.append(work_dir / f"a{i}.wav")
        _make_wav(audios[-1], duration_seconds=secs)
    track = work_dir / "track.wav"
    concatenate_audio(audios, track)
    tl = DeckTimeline(
        pages=[
            PageTiming(slide_id=f"s{i}", duration=d, lead=0, tail=0) for i, d in enumerate(lengths)
        ]
    )
    config = Config(video=VideoConfig(resolution="16x16", fps=fps, crf=30, preset="ultrafast"))
    out = work_dir / "deck.mp4"
    compose_video(
        tl,
        images,
        out,
        config=config,
        page_audios=audios,
        render_dir=work_dir / "r",
        audio_track=track,
    )

    frames = _frame_levels(out)
    shown = [min(range(12), key=lambda k: abs(levels[k] - f)) for f in frames]
    for i in range(1, 12):
        true_start = round(sum(lengths[:i]) * fps)
        assert abs(shown.index(i) - true_start) <= 1, f"slide {i} starts off its frame"
    assert abs(len(frames) - round(sum(lengths) * fps)) <= 1
    assert abs(get_duration(out, stream="video") - get_duration(track)) <= 1 / fps


def _ffprobe_json(path: Path) -> dict:
    """Run ffprobe and return parsed JSON with stream/format info."""
    import json
    import subprocess

    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


@pytest.mark.integration
def test_preview_vs_production_size(work_dir):
    """Preview (ultrafast, half-res, high CRF) should produce smaller files than production."""
    image = work_dir / "slide.png"
    _make_png(image, width=1920, height=1080)

    prod = work_dir / "prod.mp4"
    compose_silent_segment(
        image=image,
        output=prod,
        duration=3.0,
        resolution="1920x1080",
        fps=24,
        crf=23,
        preset="medium",
    )

    prev = work_dir / "preview.mp4"
    compose_silent_segment(
        image=image,
        output=prev,
        duration=3.0,
        resolution="960x540",
        fps=24,
        crf=32,
        preset="ultrafast",
    )

    assert prod.exists() and prev.exists()
    assert prev.stat().st_size < prod.stat().st_size

    # Verify resolution via ffprobe
    prev_info = _ffprobe_json(prev)
    video_stream = next(s for s in prev_info["streams"] if s["codec_type"] == "video")
    assert video_stream["width"] == 960
    assert video_stream["height"] == 540


# ---- Mocked unit tests (no ffmpeg required) ----

_PAD_1280 = (
    "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black"
)


@patch("slidesonnet.video.composer._run_ffmpeg")
def test_compose_silent_segment_argv(mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
    """Video only (a silent AAC stream would pad the concat) and a frame count
    rather than ``-t``, so the length is exactly what the caller planned."""
    out = tmp_path / "deep" / "o.mp4"
    compose_silent_segment(
        tmp_path / "s.png", out, duration=5.0, resolution="1280x720", fps=24, crf=18, preset="fast"
    )
    assert out.parent.is_dir()
    assert mock_ffmpeg.call_args.args[0] == [
        "ffmpeg", "-y", "-loop", "1", "-i", str(tmp_path / "s.png"), "-an",
        "-c:v", "libx264", "-tune", "stillimage", "-vf", f"{_PAD_1280},format=yuv420p",
        "-r", "24", "-preset", "fast", "-crf", "18", "-frames:v", "120", str(out),
    ]  # fmt: skip


@patch("slidesonnet.video.composer._run_ffmpeg")
def test_compose_transition_clip_argv(mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
    """xfade emits yuv444p unless pinned, which Windows' 4:2:0-only decoder rejects
    once concatenated with the yuv420p slide segments: the output is pinned."""
    a, b, out = tmp_path / "a.png", tmp_path / "b.png", tmp_path / "t.mp4"
    compose_transition_clip(
        a, b, out, duration=0.5, transition="wipeleft", resolution="1280x720", fps=24
    )
    pad = f"{_PAD_1280},format=yuv420p,setsar=1"
    assert mock_ffmpeg.call_args.args[0] == [
        "ffmpeg", "-y",
        "-loop", "1", "-t", "0.8", "-i", str(a),
        "-loop", "1", "-t", "0.8", "-i", str(b),
        "-filter_complex",
        (
            f"[0:v]{pad}[a];[1:v]{pad}[b];"
            "[a][b]xfade=transition=wipeleft:duration=0.5:offset=0,fps=24,format=yuv420p[v]"
        ),
        "-map", "[v]", "-an", "-c:v", "libx264", "-tune", "stillimage",
        "-r", "24", "-preset", "medium", "-crf", "23", "-frames:v", "12", str(out),
    ]  # fmt: skip


@patch("slidesonnet.video.composer._run_ffmpeg")
def test_concatenate_segments_argv_and_private_list_file(
    mock_ffmpeg: MagicMock, tmp_path: Path
) -> None:
    """The list lives in the segments' scratch dir under a unique name: a user's
    own concat_list.txt beside the output survives, and parallel exports can't
    share one. Output-time reports are forwarded."""
    scratch = tmp_path / "segments"
    segs = [scratch / "a.mp4", scratch / "b.mp4"]
    user_file = tmp_path / "concat_list.txt"
    user_file.write_text("mine")
    seen: list[tuple[list[str], str]] = []

    def capture(cmd: list[str], **kw: object) -> None:
        seen.append((cmd, Path(cmd[cmd.index("-i") + 1]).read_text()))

    mock_ffmpeg.side_effect = capture
    progress: list[float] = []
    out = tmp_path / "out.mp4"
    concatenate_segments(segs, out, on_time=progress.append)

    [(cmd, text)] = seen
    listing = Path(cmd[cmd.index("-i") + 1])
    assert cmd == [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out),
    ]  # fmt: skip
    assert listing.parent == scratch and listing.name != "concat_list.txt"
    assert not listing.exists()
    assert user_file.read_text() == "mine"
    assert text == "".join(f"file '{seg.resolve()}'\n" for seg in segs)
    assert mock_ffmpeg.call_args.kwargs["on_time"] == progress.append


@patch("slidesonnet.video.composer.run_tool_with_progress")
@patch("slidesonnet.video.composer.run_tool")
def test_run_ffmpeg_streams_progress_only_to_a_listener(
    plain: MagicMock, streaming: MagicMock
) -> None:
    _run_ffmpeg(["ffmpeg", "-i", "x"])
    plain.assert_called_once()
    streaming.assert_not_called()
    plain.reset_mock()
    seen: list[float] = []
    _run_ffmpeg(["ffmpeg", "-i", "x"], on_time=seen.append)
    plain.assert_not_called()
    assert streaming.call_args.kwargs["on_time"] == seen.append


@patch("slidesonnet.video.composer._run_ffmpeg")
def test_mux_copy_argv(mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
    """The deck track's AAC (encoded aside, see ``render.track_aac``) is copied in
    beside the picture: neither stream is re-encoded."""
    seen: list[float] = []
    v, aac, out = tmp_path / "v.mp4", tmp_path / "a.m4a", tmp_path / "o.mp4"
    mux_copy(v, aac, out, on_time=seen.append)
    assert mock_ffmpeg.call_args.args[0] == [
        "ffmpeg", "-y", "-i", str(v), "-i", str(aac), "-map", "0:v:0", "-map", "1:a:0",
        "-c", "copy", str(out),
    ]  # fmt: skip
    assert mock_ffmpeg.call_args.kwargs["on_time"] == seen.append


_TWO_STREAMS = {
    "format": {"duration": "12.345"},
    "streams": [
        {"codec_type": "video", "duration": "10.5"},
        {"codec_type": "audio", "codec_name": "pcm_s16le", "duration": "10.7"},
    ],
}


@pytest.mark.parametrize(
    ("probes", "stream", "expected"),
    [
        ([_TWO_STREAMS], None, 12.345),
        ([_TWO_STREAMS], "video", 10.5),
        ([_TWO_STREAMS], "audio", 10.7),
        # the requested stream has no duration: fall back to the container's
        ([{"streams": [{"codec_type": "video"}]}, {"format": {"duration": "12.0"}}], "video", 12.0),
    ],
)
@patch("slidesonnet.proc.subprocess.run")
def test_get_duration(
    mock_run: MagicMock, probes: list[dict[str, object]], stream: str | None, expected: float
) -> None:
    mock_run.side_effect = [MagicMock(stdout=json.dumps(p)) for p in probes]
    assert get_duration(Path("test.mp4"), stream=stream) == pytest.approx(expected)


_BAD_VIDEO_STREAM = json.dumps({"streams": [{"codec_type": "video", "duration": "N/A"}]})


@pytest.mark.parametrize(
    ("run", "stream", "match"),
    [
        (FileNotFoundError(), None, "ffprobe.*not found"),
        (subprocess.CalledProcessError(1, "ffprobe"), None, "ffprobe failed"),
        (MagicMock(stdout="not json"), None, "invalid JSON"),
        (MagicMock(stdout=json.dumps({"format": {}})), None, "missing.*format.duration"),
        (MagicMock(stdout=json.dumps({"format": {"duration": "N/A"}})), None, "non-numeric"),
        (MagicMock(stdout=_BAD_VIDEO_STREAM), "video", "non-numeric"),
    ],
)
def test_get_duration_errors(run: object, stream: str | None, match: str) -> None:
    kw = {"side_effect": run} if isinstance(run, BaseException) else {"return_value": run}
    with patch("slidesonnet.proc.subprocess.run", **kw), pytest.raises(FFmpegError, match=match):
        get_duration(Path("test.mp4"), stream=stream)


def _ffmpeg_writes_output(cmd: list[str], **kw: object) -> None:
    Path(cmd[-1]).write_bytes(b"out")


class TestConcatenateAudioMocked:
    """Mocked tests for concatenate_audio()."""

    @patch("slidesonnet.video.composer._run_ffmpeg", side_effect=_ffmpeg_writes_output)
    def test_argv(self, mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
        paths = [tmp_path / f"{i}.wav" for i in range(3)]
        output = tmp_path / "deep" / "out.wav"

        concatenate_audio(paths, output)

        cmd = mock_ffmpeg.call_args.args[0]
        assert cmd == [
            "ffmpeg", "-y", *[a for p in paths for a in ("-i", str(p))],
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[outa]",
            "-map", "[outa]", cmd[-1],
        ]  # fmt: skip
        assert output.read_bytes() == b"out"  # the partial was published over the output

    @patch("slidesonnet.video.composer._run_ffmpeg")
    def test_interrupted_write_keeps_the_previous_file(
        self, mock_ffmpeg: MagicMock, tmp_path: Path
    ) -> None:
        """ffmpeg writes a sibling temp file, renamed over the output only when whole."""
        output = tmp_path / "track.wav"
        output.write_bytes(b"previous")

        def die_midway(cmd: list[str], **kw: object) -> None:
            Path(cmd[-1]).write_bytes(b"half")
            raise KeyboardInterrupt

        mock_ffmpeg.side_effect = die_midway
        with pytest.raises(KeyboardInterrupt):
            concatenate_audio([tmp_path / "a.wav", tmp_path / "b.wav"], output)
        assert output.read_bytes() == b"previous"
        assert [p.name for p in tmp_path.iterdir()] == ["track.wav"]

    @patch("slidesonnet.video.composer._run_ffmpeg", side_effect=_ffmpeg_writes_output)
    def test_single_file_copies_same_format_and_converts_another(
        self, mock_ffmpeg: MagicMock, tmp_path: Path
    ) -> None:
        """One WAV is copied as is; one MP3 is decoded, never copied into a .wav name."""
        wav = tmp_path / "only.wav"
        wav.write_bytes(b"audio-data")
        concatenate_audio([wav], tmp_path / "out.wav")
        assert (tmp_path / "out.wav").read_bytes() == b"audio-data"
        mock_ffmpeg.assert_not_called()

        mp3 = tmp_path / "only.mp3"
        mp3.write_bytes(b"mp3-data")
        concatenate_audio([mp3], tmp_path / "out2.wav")
        cmd = mock_ffmpeg.call_args[0][0]
        assert cmd[cmd.index("-i") + 1] == str(mp3)
        assert (tmp_path / "out2.wav").read_bytes() == b"out"
