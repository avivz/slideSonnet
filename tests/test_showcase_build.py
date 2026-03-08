"""Integration test: build the showcase example end-to-end (no mocking)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from slidesonnet.pipeline import build

SHOWCASE_DIR = Path(__file__).resolve().parent.parent / "examples" / "showcase"


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

    result = build(project / "slidesonnet.yaml", tts_override="piper")

    # --- Final output exists and is a valid video ---
    expected = project / "showcase.mp4"
    assert result.output_path == expected
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
    # 01_slides (MARP): 30 sub-slides (1 skip excluded) = 30 segments
    segments = sorted(build_dir.rglob("segments/*.mp4"))
    assert len(segments) == 30, f"expected 30 segments, got {len(segments)}"

    # --- TTS audio files were generated for narrated slides ---
    audio_files = sorted(build_dir.rglob("audio/*.wav"))
    assert len(audio_files) >= 30, f"expected at least 30 audio files, got {len(audio_files)}"
