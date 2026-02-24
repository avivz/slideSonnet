"""Integration tests for video composer (require ffmpeg)."""

import shutil
import wave
from pathlib import Path

import pytest

from slidesonnet.video.composer import (
    compose_segment,
    compose_silent_segment,
    concatenate_segments,
    get_duration,
)

pytestmark = pytest.mark.integration


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
            image=image, audio=audio, output=seg,
            duration=1.0, pad_seconds=0.0,
            resolution="640x480", fps=24, crf=28,
        )
        segments.append(seg)

    output = work_dir / "final.mp4"
    concatenate_segments(segments, output)

    assert output.exists()
    dur = get_duration(output)
    assert 2.5 <= dur <= 4.0  # ~3s total with tolerance


def test_get_duration_nonexistent():
    assert get_duration(Path("/nonexistent.mp4")) == 0.0
