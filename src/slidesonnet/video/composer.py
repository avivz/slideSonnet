"""FFmpeg-based video composition: per-slide segments and final assembly."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


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

    # Scale filter: fit to resolution, pad to exact size with black bars
    w, h = resolution.split("x")
    scale_filter = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"format=yuv420p"
    )

    # Delay audio by pre_silence (adelay takes milliseconds, all channels)
    delay_ms = int(pre_silence * 1000)
    audio_filter = f"adelay={delay_ms}|{delay_ms}"

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
        "-shortest",
        str(output),
    ]
    _run_ffmpeg(cmd)


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

    # Get durations for offset calculation
    durations = [get_duration(seg) for seg in segments]

    # Build filter_complex string with pairwise xfade + acrossfade
    inputs: list[str] = []
    for i, seg in enumerate(segments):
        inputs.extend(["-i", str(seg)])

    # Track cumulative offset: first offset = D0 - crossfade
    # Each subsequent: prev_offset + D_i - crossfade
    video_label = "[0:v]"
    audio_label = "[0:a]"
    filter_parts: list[str] = []
    offset = durations[0] - crossfade

    for i in range(1, len(segments)):
        safe_offset = max(0.0, offset)
        out_v = f"[v{i}]"
        out_a = f"[a{i}]"

        filter_parts.append(
            f"{video_label}[{i}:v]xfade=transition=fade:duration={crossfade}"
            f":offset={safe_offset:.6f}{out_v}"
        )
        filter_parts.append(f"{audio_label}[{i}:a]acrossfade=d={crossfade}:c1=tri:c2=tri{out_a}")

        video_label = out_v
        audio_label = out_a

        if i < len(segments) - 1:
            # Next offset: current safe_offset + next duration - crossfade
            offset = safe_offset + durations[i] - crossfade

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


def get_duration(media_path: Path) -> float:
    """Get duration of a media file in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        str(media_path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except (FileNotFoundError, subprocess.CalledProcessError, KeyError, ValueError):
        return 0.0


def _run_ffmpeg(cmd: list[str]) -> None:
    """Run an ffmpeg command, handling errors."""
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        print("ERROR: 'ffmpeg' not found. Install ffmpeg.", file=sys.stderr)
        raise SystemExit(1)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: ffmpeg failed:\n{e.stderr}", file=sys.stderr)
        raise SystemExit(1)
