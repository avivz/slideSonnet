"""Regression tests for the Inworld MP3 subtitle drift (KNOWN_ISSUES).

An MP3 carries encoder delay + end padding (LAME priming), so a container's
``format.duration`` over-reports the true decoded length by ~tens of ms. The
subtitle timeline is built from per-clip ``get_duration()`` while
``concatenate_audio`` decodes to the *true* (shorter) length — so on an MP3
(Inworld) render the timeline accumulates phantom length and the subtitles
slide progressively late, while WAV (Kokoro/Qwen3) stays exact.

The repro is **free** — synthesize tones to MP3 with libmp3lame, no Inworld
call. ``get_duration`` must report the decoded length for compressed clips, so
``sum(get_duration(clip_i)) == get_duration(concatenate_audio(clips))``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from slidesonnet.models import VideoConfig
from slidesonnet.narration.model import Deck, PageNarration, Segment
from slidesonnet.render import build_timeline, render_audio_track
from slidesonnet.timing import TimingMode
from slidesonnet.video.composer import concatenate_audio, get_duration

# Distinct lengths so a per-clip overcount accumulates visibly. Short clips make
# the fixed LAME padding a larger fraction, so the drift is unmistakable.
_CLIP_SECONDS = [0.7, 1.1, 0.5, 0.9, 0.6, 1.3]


def _make_tone_mp3(path: Path, seconds: float, *, rate: int = 24000) -> None:
    """Encode *seconds* of a sine tone to MP3 (libmp3lame) — an Inworld stand-in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:a",
            "libmp3lame",
            "-ar",
            str(rate),
            str(path),
        ],
        check=True,
    )


def _make_tone_wav(path: Path, seconds: float, *, rate: int = 44100) -> None:
    """Encode *seconds* of a sine tone to PCM WAV — a Kokoro/Qwen3 stand-in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:a",
            "pcm_s16le",
            "-ar",
            str(rate),
            str(path),
        ],
        check=True,
    )


@pytest.mark.integration
def test_mp3_clip_durations_sum_to_concatenated_length(tmp_path: Path) -> None:
    """The crux: per-clip MP3 durations must sum to what concat actually produces.

    Fails before the fix — ``format.duration`` over-reports each MP3 by its
    encoder delay/padding, so the sum runs ahead of the decoded concat length.
    """
    clips: list[Path] = []
    for i, secs in enumerate(_CLIP_SECONDS):
        p = tmp_path / f"clip{i}.mp3"
        _make_tone_mp3(p, secs)
        clips.append(p)

    summed = sum(get_duration(c) for c in clips)
    concat = tmp_path / "concat.wav"
    concatenate_audio(clips, concat)
    actual = get_duration(concat)

    assert summed == pytest.approx(actual, abs=0.01)


@pytest.mark.integration
def test_wav_clip_durations_sum_to_concatenated_length(tmp_path: Path) -> None:
    """Control: WAV is already exact and must stay byte-identical in behaviour."""
    clips: list[Path] = []
    for i, secs in enumerate(_CLIP_SECONDS):
        p = tmp_path / f"clip{i}.wav"
        _make_tone_wav(p, secs)
        clips.append(p)

    summed = sum(get_duration(c) for c in clips)
    concat = tmp_path / "concat.wav"
    concatenate_audio(clips, concat)
    actual = get_duration(concat)

    assert summed == pytest.approx(actual, abs=0.01)


@pytest.mark.integration
def test_timeline_total_matches_assembled_track_for_mp3_cache(tmp_path: Path) -> None:
    """End-to-end: the subtitle timeline must equal the assembled audio track.

    Mirrors the production path — synthesis records ``get_duration(clip)`` as
    each segment's duration, which feeds ``build_timeline`` (and thus the
    subtitles), while ``render_audio_track`` decodes the same clips into the
    real track. The two must agree, or the subtitles drift off the audio.
    """
    deck = Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b"],
        narration={
            "a": PageNarration("a", [Segment.speech("one"), Segment.speech("two")]),
            "b": PageNarration("b", [Segment.speech("three"), Segment.speech("four")]),
        },
    )
    clips: list[Path] = []
    for i, secs in enumerate(_CLIP_SECONDS[:4]):
        p = tmp_path / f"c{i}.mp3"
        _make_tone_mp3(p, secs)
        clips.append(p)
    page_clips = [[clips[0], clips[1]], [clips[2], clips[3]]]

    # Exactly what audio/synth records per segment (SynthResult.duration).
    speech_by_page = [[get_duration(c) for c in page] for page in page_clips]
    video = VideoConfig(pre_silence=0.3, tail_seconds=0.5)
    timeline = build_timeline(
        deck, TimingMode("tts"), video=video, speech_durations_by_page=speech_by_page
    )

    track, _ = render_audio_track(timeline, page_clips, render_dir=tmp_path / "render")

    assert timeline.total_duration == pytest.approx(get_duration(track), abs=0.02)
