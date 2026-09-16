"""Assemble synthesized speech and silences into per-page and whole-deck tracks.

The same assembled track drives both the export and the GUI's whole-deck
preview, so what you preview is sample-accurate to what you export. A *cue
sheet* — ``[(start_seconds, slide_id), ...]`` — lets the frontend flip the page
image as the single ``<audio>`` element plays.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from slidesonnet.exceptions import FFmpegError, RenderError
from slidesonnet.proc import run_tool
from slidesonnet.timing import PageTiming
from slidesonnet.video.composer import concatenate_audio, get_duration

_SAMPLE_RATE = 44100


@dataclass(frozen=True)
class AudioPiece:
    """One element of a page's audio: a speech clip or a silence."""

    kind: str  # "speech" | "silence"
    path: Path | None = None  # speech clip
    seconds: float = 0.0  # silence duration


def make_silence(duration: float, path: Path, *, sample_rate: int = _SAMPLE_RATE) -> Path:
    """Write *duration* seconds of stereo silence to *path* (WAV)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dur = max(duration, 0.001)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl=stereo",
        "-t",
        f"{dur:.4f}",
        "-c:a",
        "pcm_s16le",
        str(path),
    ]
    run_tool(
        cmd,
        error_cls=FFmpegError,
        install_hint="ffmpeg",
        fail_message="ffmpeg failed making silence",
    )
    return path


def page_pieces(timing: PageTiming, speech_clips: list[Path]) -> list[AudioPiece]:
    """Ordered audio pieces for one page: lead silence, segments, tail silence.

    *speech_clips* aligns to the page's speech segments in order.
    """
    pieces: list[AudioPiece] = []
    if timing.lead > 0:
        pieces.append(AudioPiece(kind="silence", seconds=timing.lead))
    speech_idx = 0
    for st in timing.segments:
        if st.segment.is_speech:
            if speech_idx >= len(speech_clips):
                raise RenderError(
                    f"slide '{timing.slide_id}' has {len(timing.speech_timings)} speech "
                    f"segment(s) but only {len(speech_clips)} audio clip(s) — "
                    "synthesize its narration before rendering"
                )
            pieces.append(AudioPiece(kind="speech", path=speech_clips[speech_idx]))
            speech_idx += 1
        else:
            pieces.append(AudioPiece(kind="silence", seconds=st.segment.seconds))
    if timing.tail > 0:
        pieces.append(AudioPiece(kind="silence", seconds=timing.tail))
    return pieces


def build_page_audio(
    timing: PageTiming,
    speech_clips: list[Path],
    out_path: Path,
    *,
    silence_dir: Path,
) -> float:
    """Render one page's full audio (lead + segments + tail). Returns its duration."""
    pieces = page_pieces(timing, speech_clips)
    paths: list[Path] = []
    for piece in pieces:
        if piece.kind == "speech":
            assert piece.path is not None
            paths.append(piece.path)
        else:
            paths.append(_shared_silence(piece.seconds, silence_dir))
    if not paths:  # empty page — emit a hair of silence so the stream exists
        paths.append(_shared_silence(0.05, silence_dir))
    concatenate_audio(paths, out_path)
    return get_duration(out_path)


def _shared_silence(seconds: float, silence_dir: Path) -> Path:
    """The one silence file for *seconds*, made on first use and reused after.

    Named by duration rather than by page: a deck has only a handful of distinct
    gap lengths, so one file per length replaces one per pause per page. The name
    carries the same 4-decimal precision :func:`make_silence` hands ffmpeg, so
    two durations that would render identically map to the same file.
    """
    path = silence_dir / f"{max(seconds, 0.001):.4f}s.wav"
    if not path.exists():
        make_silence(seconds, path)
    return path


def assemble_track(page_audios: list[Path], out_path: Path) -> float:
    """Concatenate per-page audio into one deck track. Returns total duration."""
    concatenate_audio(page_audios, out_path)
    return get_duration(out_path)


class Cue(NamedTuple):
    """One preview cue: flip to *slide_id* when playback reaches *start*."""

    start: float
    slide_id: str


def cue_sheet(page_starts: list[float], slide_ids: list[str]) -> list[Cue]:
    """Build the preview cue sheet: one :class:`Cue` per page."""
    return [Cue(start, sid) for start, sid in zip(page_starts, slide_ids, strict=True)]
