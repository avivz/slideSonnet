"""Integration test: build the showcase example end-to-end (no mocking)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from slidesonnet.pipeline import build

SHOWCASE_DIR = Path(__file__).resolve().parent.parent / "examples" / "showcase"


def _generate_placeholder_mp4(path: Path) -> None:
    """Generate a minimal valid MP4 using ffmpeg (1 s black, silent)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1920x1080:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            path.as_posix(),
        ],
        check=True,
        capture_output=True,
    )


def _ffprobe_json(path: Path) -> dict[str, object]:
    """Return ffprobe output as a dict."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-show_streams",
            "-show_format",
            "-print_format",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)  # type: ignore[no-any-return]


@pytest.mark.integration
def test_showcase_builds(tmp_path: Path) -> None:
    """Full showcase project builds with all external tools."""
    # Copy showcase to tmp_path so .build/ doesn't pollute the repo
    project = tmp_path / "showcase"
    shutil.copytree(SHOWCASE_DIR, project)

    # Replace 0-byte placeholder with a real MP4 for video passthrough
    _generate_placeholder_mp4(project / "animations" / "transition.mp4")

    output = build(project / "lecture.md", tts_override="piper")

    # --- Final output exists and is a valid video ---
    expected = project / "lecture.mp4"
    assert output == expected
    assert expected.exists()
    assert expected.stat().st_size > 0

    info = _ffprobe_json(expected)
    streams = info["streams"]
    assert isinstance(streams, list)

    codec_types = {s["codec_type"] for s in streams}  # type: ignore[index]
    assert "video" in codec_types, "output has no video stream"
    assert "audio" in codec_types, "output has no audio stream"

    duration = float(info["format"]["duration"])  # type: ignore[index]
    assert duration > 10, f"output too short ({duration:.1f}s) — likely incomplete"

    # --- Per-module segment counts (narrated + silent slides, excluding skip) ---
    build_dir = project / "cache"
    # 01_part1 (MARP): 19 sub-slides (1 skip excluded) = 19 segments
    # 02_part2 (Beamer): 5 narrated + 1 silent = 6 segments
    # 03_transition (video passthrough, no segments)
    # 04_part3 (MARP): 9 narrated = 9 segments
    segments = sorted(build_dir.rglob("segments/*.mp4"))
    assert len(segments) == 34, f"expected 34 segments, got {len(segments)}"

    # --- TTS audio files were generated for narrated slides ---
    audio_files = sorted(build_dir.rglob("audio/*.wav"))
    assert len(audio_files) >= 33, f"expected at least 33 audio files, got {len(audio_files)}"
