"""Integration test: build the showcase example end-to-end (no mocking)."""

from __future__ import annotations

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
            "color=c=black:s=1920x1080:d=1",
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


@pytest.mark.integration
def test_showcase_builds(tmp_path: Path) -> None:
    """Full showcase project builds with all external tools."""
    # Copy showcase to tmp_path so .build/ doesn't pollute the repo
    project = tmp_path / "showcase"
    shutil.copytree(SHOWCASE_DIR, project)

    # Replace 0-byte placeholder with a real MP4 for video passthrough
    _generate_placeholder_mp4(project / "animations" / "transition.mp4")

    output = build(project / "lecture01.md")

    expected = project / ".build" / "lecture01.mp4"
    assert output == expected
    assert expected.exists()
    assert expected.stat().st_size > 0
