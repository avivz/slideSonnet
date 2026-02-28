"""FFmpeg-based video composition: per-slide segments and final assembly."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from slidesonnet.exceptions import FFmpegError

logger = logging.getLogger(__name__)


def compose_segment(
    image: Path,
    audio: Path,
    output: Path,
    duration: float,
    pad_seconds: float = 0.5,
    pre_silence: float = 1.0,
    resolution: str = "1920x1080",
    fps: int = 24,
    crf: int = 23,
) -> None:
    """Create a video segment from a static slide image + audio.

    The slide is displayed for pre_silence + audio duration + pad_seconds.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    total_duration = pre_silence + duration + pad_seconds
    logger.debug(
        "compose: %s audio=%.3fs pre=%.3fs pad=%.3fs → total=%.3fs",
        output.name,
        duration,
        pre_silence,
        pad_seconds,
        total_duration,
    )

    # Scale filter: fit to resolution, pad to exact size with black bars
    w, h = resolution.split("x")
    scale_filter = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"format=yuv420p"
    )

    # Delay audio by pre_silence (adelay takes milliseconds, all channels)
    delay_ms = int(pre_silence * 1000)
    audio_filter = f"adelay={delay_ms}|{delay_ms},apad"

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-i",
        str(audio),
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-vf",
        scale_filter,
        "-af",
        audio_filter,
        "-r",
        str(fps),
        "-crf",
        str(crf),
        "-t",
        str(total_duration),
        str(output),
    ]
    _run_ffmpeg(cmd)

    # Check for stream duration mismatch
    try:
        vid_dur = get_duration(output, stream="video")
        aud_dur = get_duration(output, stream="audio")
        delta = vid_dur - aud_dur
        if abs(delta) > 0.05:
            logger.warning(
                "compose: %s stream mismatch video=%.3fs audio=%.3fs (Δ=%.3fs)",
                output.name,
                vid_dur,
                aud_dur,
                delta,
            )
    except RuntimeError:
        pass  # probing may fail in mocked tests


def compose_silent_segment(
    image: Path,
    output: Path,
    duration: float,
    resolution: str = "1920x1080",
    fps: int = 24,
    crf: int = 23,
) -> None:
    """Create a silent video segment from a static slide image."""
    output.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("compose_silent: %s duration=%.3fs", output.name, duration)

    w, h = resolution.split("x")
    scale_filter = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"format=yuv420p"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-vf",
        scale_filter,
        "-r",
        str(fps),
        "-crf",
        str(crf),
        "-t",
        str(duration),
        str(output),
    ]
    _run_ffmpeg(cmd)


def concatenate_segments(segments: list[Path], output: Path) -> None:
    """Concatenate video segments into a single video using ffmpeg concat demuxer."""
    logger.debug("concatenate: %d segments → %s", len(segments), output.name)
    output.parent.mkdir(parents=True, exist_ok=True)
    concat_file = output.parent / "concat_list.txt"

    with open(concat_file, "w") as f:
        for seg in segments:
            f.write(f"file '{seg.resolve()}'\n")

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
    _run_ffmpeg(cmd)
    concat_file.unlink(missing_ok=True)


def concatenate_segments_xfade(
    segments: list[Path],
    output: Path,
    crossfade: float = 0.5,
    crf: int = 23,
) -> None:
    """Concatenate video segments with crossfade transitions using xfade/acrossfade filters."""
    output.parent.mkdir(parents=True, exist_ok=True)

    if len(segments) < 2:
        # Fallback: single segment, just copy
        if segments:
            shutil.copy2(segments[0], output)
        return

    # Use VIDEO stream durations for xfade offset calculation — the video
    # stream is often shorter than the container/audio duration, and xfade
    # offsets must not exceed the video stream length.
    durations = [get_duration(seg, stream="video") for seg in segments]
    logger.debug(
        "xfade: %d segments, durations=%s, requested crossfade=%.3f",
        len(segments),
        [f"{d:.3f}" for d in durations],
        crossfade,
    )

    # A segment in a chain loses crossfade time from both sides (the
    # preceding and following transitions), so it needs at least
    # 2 * crossfade of content.  Clamp if necessary.
    min_dur = min(durations) if durations else 0.0
    if min_dur > 0 and 2 * crossfade >= min_dur:
        clamped = min_dur * 0.25
        logger.warning(
            "crossfade (%.2fs) too long for shortest segment (%.2fs); clamping to %.2fs",
            crossfade,
            min_dur,
            clamped,
        )
        crossfade = clamped

    # Build filter_complex string with pairwise xfade + acrossfade
    inputs: list[str] = []
    for i, seg in enumerate(segments):
        inputs.extend(["-i", str(seg)])

    # Track cumulative offset: first offset = D0 - crossfade
    # Each subsequent: prev_offset + D_i - crossfade
    #
    # The xfade filter requires offset + duration <= first_input_duration.
    # In a chain, each transition hits this boundary exactly (mathematically
    # offset + CF == input_duration), so floating-point imprecision or
    # codec-level duration rounding can push it over, producing broken
    # output.  We subtract a small margin from each offset to guarantee
    # headroom.
    _OFFSET_MARGIN = 0.02  # 20ms safety margin per transition

    # Normalize all audio inputs to a common format so acrossfade works
    # even when segments have different sample rates or channel layouts
    # (e.g. passthrough videos vs TTS-generated audio).
    _AUDIO_FMT = "aformat=sample_rates=44100:channel_layouts=stereo"

    video_label = "[0:v]"
    # Normalize first audio stream
    filter_parts: list[str] = [f"[0:a]{_AUDIO_FMT}[a0n]"]
    audio_label = "[a0n]"
    offset = durations[0] - crossfade - _OFFSET_MARGIN

    for i in range(1, len(segments)):
        safe_offset = max(0.0, offset)
        out_v = f"[v{i}]"
        out_a = f"[a{i}]"
        norm_a = f"[a{i}n]"

        filter_parts.append(
            f"{video_label}[{i}:v]xfade=transition=fade:duration={crossfade}"
            f":offset={safe_offset:.6f}{out_v}"
        )
        # Normalize this input's audio before crossfading
        filter_parts.append(f"[{i}:a]{_AUDIO_FMT}{norm_a}")
        filter_parts.append(f"{audio_label}{norm_a}acrossfade=d={crossfade}:c1=tri:c2=tri{out_a}")

        video_label = out_v
        audio_label = out_a

        if i < len(segments) - 1:
            # Next offset: current safe_offset + next duration - crossfade
            offset = safe_offset + durations[i] - crossfade - _OFFSET_MARGIN

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        video_label,
        "-map",
        audio_label,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        str(crf),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output),
    ]
    _run_ffmpeg(cmd)


def get_duration(media_path: Path, *, stream: str | None = None) -> float:
    """Get duration of a media file in seconds using ffprobe.

    Args:
        media_path: Path to the media file.
        stream: If ``"video"`` or ``"audio"``, return that stream's duration
            instead of the container format duration.  This matters for xfade
            offset calculation where video and audio durations may differ.

    Raises RuntimeError if ffprobe is missing, the file cannot be probed,
    or the output doesn't contain a valid duration.
    """
    show_flag = "-show_streams" if stream else "-show_format"
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        show_flag,
        str(media_path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("'ffprobe' not found. Install ffmpeg.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe failed for '{media_path}': {e.stderr}") from e

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe returned invalid JSON for '{media_path}'") from e

    if stream:
        for s in info.get("streams", []):
            if s.get("codec_type") == stream and "duration" in s:
                return _parse_duration(s["duration"], media_path)
        # Fall back to format duration if the requested stream has none
        return get_duration(media_path)

    try:
        duration_str = info["format"]["duration"]
    except KeyError:
        raise RuntimeError(f"ffprobe output missing 'format.duration' for '{media_path}'")

    return _parse_duration(duration_str, media_path)


def _parse_duration(value: str, media_path: Path) -> float:
    """Convert a duration string to float, raising on failure."""
    try:
        return float(value)
    except (ValueError, TypeError) as e:
        raise RuntimeError(
            f"ffprobe returned non-numeric duration '{value}' for '{media_path}'"
        ) from e


def _run_ffmpeg(cmd: list[str]) -> None:
    """Run an ffmpeg command, handling errors."""
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise FFmpegError("'ffmpeg' not found. Install ffmpeg.")
    except subprocess.CalledProcessError as e:
        raise FFmpegError(f"ffmpeg failed:\n{e.stderr}")
