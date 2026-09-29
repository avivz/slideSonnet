"""FFmpeg-based video composition: per-slide segments and final assembly."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import secrets
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

from slidesonnet.exceptions import FFmpegError
from slidesonnet.proc import run_tool, run_tool_with_progress

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def partial_output(output: Path) -> Iterator[Path]:
    """Yield a hidden sibling of *output* to write, renamed over *output* on success.

    A reader — the editor's preview, the next export's cache check, the user's
    player — sees the old file or the whole new one, never half of one, and a
    failure or cancel inside the block leaves the old file untouched and no temp
    behind. The sibling keeps *output*'s extension (ffmpeg picks the format from
    it) and is not made by ``mkstemp``: the writer creates it, so it gets the
    permissions a direct write would (``mkstemp`` makes it owner-only).
    """
    tag = f"{os.getpid()}-{secrets.token_hex(4)}"
    partial = output.with_name(f".{output.stem}.{tag}.partial{output.suffix}")
    try:
        yield partial
        os.replace(partial, output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _scale_pad_filter(resolution: str) -> str:
    """Return an ffmpeg -vf filter: scale to fit + pad to exact size with black bars."""
    w, h = resolution.split("x")
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"format=yuv420p"
    )


def compose_silent_segment(
    image: Path,
    output: Path,
    duration: float,
    resolution: str = "1920x1080",
    fps: int = 24,
    crf: int = 23,
    preset: str = "medium",
) -> None:
    """Create a silent, video-only segment from a static slide image.

    The segment holds exactly ``round(duration * fps)`` frames and carries no
    audio stream: the deck track is muxed over the concatenated video at the
    end, and a silent AAC stream here would pad each segment to whole AAC frames
    that the stream-copy concat then offsets every later segment by. Callers
    that splice segments pass frame-exact durations (see
    :func:`slidesonnet.render.frame_plan`), so no rounding error accumulates.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("compose_silent: %s duration=%.3fs", output.name, duration)

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-an",
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-vf",
        _scale_pad_filter(resolution),
        "-r",
        str(fps),
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-frames:v",
        str(_frame_count(duration, fps)),
        str(output),
    ]
    _run_ffmpeg(cmd)


def _frame_count(duration: float, fps: int) -> int:
    """Whole frames for *duration* seconds at *fps* (at least one)."""
    return max(1, round(duration * fps))


def compose_transition_clip(
    image_from: Path,
    image_to: Path,
    output: Path,
    duration: float,
    transition: str,
    resolution: str = "1920x1080",
    fps: int = 24,
    crf: int = 23,
    preset: str = "medium",
) -> None:
    """Render a *duration*-second video-only clip that xfades *image_from*→*image_to*.

    ``transition`` is an FFmpeg xfade name (``wipeleft``, ``slideup``, ``fade``,
    …). The clip holds ``round(duration * fps)`` frames and no audio, so it can
    be spliced between two per-slide segments (see :func:`render.compose_video`): it replaces an equal slice of
    the outgoing slide's trailing hold, so the deck's total duration and audio
    waveform are unchanged — the morph just plays over otherwise-static hold
    time.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("transition: %s %.3fs %s→%s", transition, duration, image_from.name, image_to.name)
    pad = _scale_pad_filter(resolution)
    # Loop each still a hair longer than the xfade so offset+duration stays
    # inside the input length — xfade is strict about that boundary.
    src_len = duration + 0.3
    # xfade renegotiates the graph format and emits yuv444p unless pinned; the
    # slide segments are yuv420p, so an unpinned transition makes the concatenated
    # stream non-uniform and Windows' 4:2:0-only H.264 decoder rejects it
    # ("unsupported codec settings") at the first transition. Force yuv420p so
    # every segment matches.
    filter_complex = (
        f"[0:v]{pad},setsar=1[a];"
        f"[1:v]{pad},setsar=1[b];"
        f"[a][b]xfade=transition={transition}:duration={duration}:offset=0,"
        f"fps={fps},format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-t",
        str(src_len),
        "-i",
        str(image_from),
        "-loop",
        "1",
        "-t",
        str(src_len),
        "-i",
        str(image_to),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-an",
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-r",
        str(fps),
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-frames:v",
        str(_frame_count(duration, fps)),
        str(output),
    ]
    _run_ffmpeg(cmd)


def concatenate_segments(
    segments: list[Path], output: Path, *, on_time: Callable[[float], None] | None = None
) -> None:
    """Concatenate video segments into a single video using ffmpeg concat demuxer.

    The demuxer's list file is a uniquely named temp file beside the segments
    (render scratch), never in the output's folder: a fixed name there would
    overwrite, then delete, a user's own file, and two exports into one folder
    would race on it. *on_time*, if given, is called with seconds of output
    written as ffmpeg runs.
    """
    logger.debug("concatenate: %d segments → %s", len(segments), output.name)
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch = segments[0].parent if segments else output.parent
    scratch.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=scratch, prefix=".concat-", suffix=".txt")
    concat_file = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(f"file {_concat_quote(seg.resolve())}\n" for seg in segments)
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(output),
        ]
        _run_ffmpeg(cmd, on_time=on_time)
    finally:
        concat_file.unlink(missing_ok=True)


def _concat_quote(path: Path) -> str:
    """Single-quote *path* for an ffmpeg concat list; an embedded ``'`` becomes ``'\\''``."""
    return "'" + str(path).replace("'", "'\\''") + "'"


def mux_audio(
    video: Path, audio: Path, output: Path, *, on_time: Callable[[float], None] | None = None
) -> None:
    """Replace *video*'s audio with *audio*, copying the video stream (no re-encode).

    Used by :func:`render.compose_video` for animated transitions: the video is
    assembled silent (still segments + centered morph clips) and the single
    continuous deck track is laid over it here, so a morph centered on a slide
    boundary plays over whatever audio is there (silence *or* speech) without
    changing the deck's total duration. The video is frame-planned to within a
    frame of the track, so nothing is cut to the shorter stream (``-shortest``
    would clip the track's last few milliseconds). *on_time*, if given, is
    called with seconds of output written as ffmpeg runs.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("mux: %s + %s → %s", video.name, audio.name, output.name)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output),
    ]
    _run_ffmpeg(cmd, on_time=on_time)


def compose_slideshow(
    images: list[Path],
    durations: list[float],
    output: Path,
    *,
    scratch: Path,
    resolution: str,
    crf: int,
    preset: str,
    max_frame_seconds: float = 1.0,
    on_time: Callable[[float], None] | None = None,
) -> None:
    """Encode *images* as one silent, variable-frame-rate video in a single pass.

    The quick export's video: each still is shown for its duration as a few long
    frames (none longer than *max_frame_seconds*, so seeking and players that
    expect a steady picture cope) rather than ``duration × fps`` identical ones,
    which is what makes the full-quality encode slow. The concat demuxer places
    every entry on its own clock, so the error stays under one of its ticks
    (1/25 s) however long the deck. Its list file goes in *scratch* under a
    unique name, as in :func:`concatenate_segments`.
    """
    logger.debug("slideshow: %d stills → %s", len(images), output.name)
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    shown: Path | None = None
    for image, seconds in zip(images, durations, strict=True):
        if seconds <= 0:
            continue
        chunks = max(1, math.ceil(seconds / max_frame_seconds - 1e-9))
        entry = f"file {_concat_quote(image.resolve())}\nduration {seconds / chunks:.6f}\n"
        lines.extend([entry] * chunks)
        shown = image
    if shown is not None:  # the demuxer ignores the last entry's duration: repeat it
        lines.append(f"file {_concat_quote(shown.resolve())}\n")
    fd, name = tempfile.mkstemp(dir=scratch, prefix=".slideshow-", suffix=".txt")
    listing = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-an",
            "-c:v",
            "libx264",
            "-tune",
            "stillimage",
            "-vf",
            _scale_pad_filter(resolution),
            "-fps_mode",
            "vfr",
            "-preset",
            preset,
            "-crf",
            str(crf),
            str(output),
        ]
        _run_ffmpeg(cmd, on_time=on_time)
    finally:
        listing.unlink(missing_ok=True)


def encode_aac(audio: Path, output: Path) -> None:
    """Encode *audio* to AAC with the settings :func:`mux_audio` uses (same sound)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(audio), "-vn", "-c:a", "aac", "-b:a", "192k", str(output)]
    _run_ffmpeg(cmd)


def mux_copy(
    video: Path, audio: Path, output: Path, *, on_time: Callable[[float], None] | None = None
) -> None:
    """Put *video*'s picture and *audio*'s (already encoded) sound in one file, copying both."""
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c",
        "copy",
        str(output),
    ]
    _run_ffmpeg(cmd, on_time=on_time)


def concatenate_audio(audio_paths: list[Path], output: Path) -> None:
    """Concatenate multiple audio files into one using ffmpeg concat filter.

    Handles any format (WAV/MP3) since it decodes and re-encodes. A single
    input already in the output's format is copied; one in another format (an
    MP3 clip for a ``.wav`` page) is converted, never copied under the wrong name. The output is published whole
    (:func:`partial_output`): page and track WAVs are reused by name.
    """
    output.parent.mkdir(parents=True, exist_ok=True)

    if len(audio_paths) == 1 and audio_paths[0].suffix.lower() == output.suffix.lower():
        with partial_output(output) as partial:
            shutil.copy2(audio_paths[0], partial)
        return

    inputs: list[str] = []
    filter_labels: list[str] = []
    for i, path in enumerate(audio_paths):
        inputs.extend(["-i", str(path)])
        filter_labels.append(f"[{i}:a]")

    concat_filter = f"{''.join(filter_labels)}concat=n={len(audio_paths)}:v=0:a=1[outa]"

    with partial_output(output) as partial:
        cmd = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            concat_filter,
            "-map",
            "[outa]",
            str(partial),
        ]
        _run_ffmpeg(cmd)


def get_duration(media_path: Path, *, stream: str | None = None) -> float:
    """Get duration of a media file in seconds using ffprobe.

    Args:
        media_path: Path to the media file.
        stream: If ``"video"`` or ``"audio"``, return that stream's duration
            instead of the container format duration (the two may differ).

    Raises FFmpegError if ffprobe is missing, the file cannot be probed,
    or the output doesn't contain a valid duration.
    """
    # One probe carries both the container duration and the stream list, so the
    # default path can tell a compressed audio clip (whose header over-reports)
    # from a sample-exact WAV without a second ffprobe.
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(media_path),
    ]
    result = run_tool(
        cmd,
        error_cls=FFmpegError,
        install_hint="ffmpeg",
        fail_message=f"ffprobe failed for '{media_path}'",
    )

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise FFmpegError(f"ffprobe returned invalid JSON for '{media_path}'") from e

    if stream:
        for s in info.get("streams", []):
            if s.get("codec_type") == stream and "duration" in s:
                return _parse_duration(s["duration"], media_path)
        # Fall back to format duration if the requested stream has none
        return get_duration(media_path)

    # A lossy audio clip's container duration includes encoder delay + end
    # padding the decoder strips, so it over-reports the true playable length.
    # concatenate_audio decodes, so summing such clips' header durations drifts
    # ahead of the assembled track (and the subtitle timeline with it). Measure
    # the decoded length instead — WAV/PCM and video keep the cheap header read.
    if _is_delay_padded_audio(info):
        return _decoded_audio_duration(media_path)

    try:
        duration_str = info["format"]["duration"]
    except KeyError:
        raise FFmpegError(f"ffprobe output missing 'format.duration' for '{media_path}'")

    return _parse_duration(duration_str, media_path)


#: Audio codecs that carry encoder delay + end padding, so a container's
#: ``format.duration`` over-reports the true *decoded* length (e.g. LAME priming
#: on MP3 ≈ 1152 samples; AAC encoder delay). Inworld returns MP3; the rest are
#: included so any future compressed-cache engine is correct by default. WAV/PCM
#: is sample-exact from the header and is deliberately absent.
_DELAY_PADDED_AUDIO_CODECS = frozenset({"mp3", "aac", "vorbis", "opus", "wmav1", "wmav2"})


def _is_delay_padded_audio(probe_info: dict[str, object]) -> bool:
    """True for an *audio-only* file whose codec carries encoder delay/padding.

    A file with a video stream (e.g. the muxed deck mp4) is excluded — only
    standalone compressed speech clips need the decode-accurate measurement.
    """
    raw_streams = probe_info.get("streams", [])
    streams = raw_streams if isinstance(raw_streams, list) else []
    if any(s.get("codec_type") == "video" for s in streams):
        return False
    return any(
        s.get("codec_type") == "audio" and s.get("codec_name") in _DELAY_PADDED_AUDIO_CODECS
        for s in streams
    )


def _decoded_audio_duration(media_path: Path) -> float:
    """True playable length of a compressed clip, by decoding it to PCM.

    Transcodes to PCM WAV — exactly what :func:`concatenate_audio` does — and
    reads the resulting padding-free duration, so summing per-clip durations
    matches the assembled track to the sample.
    """
    with tempfile.TemporaryDirectory() as td:
        decoded = Path(td) / "decoded.wav"
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(media_path),
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_s16le",
            str(decoded),
        ]
        run_tool(
            cmd,
            error_cls=FFmpegError,
            install_hint="ffmpeg",
            fail_message=f"ffmpeg failed decoding '{media_path}' to measure its length",
        )
        # decoded.wav is PCM (not delay-padded), so this reads its exact header.
        return get_duration(decoded)


def _parse_duration(value: str, media_path: Path) -> float:
    """Convert a duration string to float, raising on failure."""
    try:
        return float(value)
    except (ValueError, TypeError) as e:
        raise FFmpegError(
            f"ffprobe returned non-numeric duration '{value}' for '{media_path}'"
        ) from e


def _run_ffmpeg(cmd: list[str], *, on_time: Callable[[float], None] | None = None) -> None:
    """Run an ffmpeg command, handling errors; stream output time to *on_time* if given."""
    if on_time is None:
        run_tool(cmd, error_cls=FFmpegError, install_hint="ffmpeg", fail_message="ffmpeg failed")
    else:
        run_tool_with_progress(
            cmd,
            on_time=on_time,
            error_cls=FFmpegError,
            install_hint="ffmpeg",
            fail_message="ffmpeg failed",
        )
