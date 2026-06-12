"""Unit tests for audio track assembly (mocked ffmpeg).

audio/track.py owns the silence-chunking and concatenation math that
determines A/V sync — these tests pin the assembly logic without external
tools. Real ffmpeg behaviour is covered by the export integration tier.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.audio.track import (
    AudioPiece,
    assemble_track,
    build_page_audio,
    cue_sheet,
    make_silence,
    page_pieces,
)
from slidesonnet.exceptions import FFmpegError, RenderError
from slidesonnet.narration.model import PageNarration, Segment
from slidesonnet.timing import TimingMode, compute_page_timing


def _timing(
    segments: list[Segment],
    *,
    durations: list[float] | None = None,
    lead: float = 0.0,
    tail: float = 0.0,
):
    block = PageNarration("slide-1", segments)
    return compute_page_timing(
        block, TimingMode("tts"), speech_durations=durations or [], lead=lead, tail=tail
    )


class TestMakeSilence:
    @patch("slidesonnet.proc.subprocess.run")
    def test_command_shape(self, mock_run: MagicMock, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "sil.wav"
        result = make_silence(1.5, out)
        assert result == out
        assert out.parent.is_dir()  # created on demand
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "anullsrc=r=44100:cl=stereo" in cmd
        assert cmd[cmd.index("-t") + 1] == "1.5000"
        assert str(out) in cmd

    @patch("slidesonnet.proc.subprocess.run")
    def test_duration_clamped_to_minimum(self, mock_run: MagicMock, tmp_path: Path) -> None:
        make_silence(0.0, tmp_path / "sil.wav")
        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("-t") + 1] == "0.0010"  # never a zero-length stream

    @patch("slidesonnet.proc.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_ffmpeg_raises_ffmpeg_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        with pytest.raises(FFmpegError, match="not found"):
            make_silence(1.0, tmp_path / "sil.wav")

    @patch(
        "slidesonnet.proc.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr="boom"),
    )
    def test_ffmpeg_failure_raises_ffmpeg_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        with pytest.raises(FFmpegError, match="boom"):
            make_silence(1.0, tmp_path / "sil.wav")


class TestPagePieces:
    def test_lead_speech_pause_tail_order(self, tmp_path: Path) -> None:
        clip = tmp_path / "clip.wav"
        timing = _timing(
            [Segment.speech("Hi."), Segment.pause(2.0)],
            durations=[1.0],
            lead=0.3,
            tail=0.5,
        )
        pieces = page_pieces(timing, [clip])
        assert [p.kind for p in pieces] == ["silence", "speech", "silence", "silence"]
        assert pieces[0].seconds == 0.3  # lead
        assert pieces[1].path == clip
        assert pieces[2].seconds == 2.0  # explicit pause
        assert pieces[3].seconds == 0.5  # tail

    def test_zero_lead_and_tail_are_omitted(self, tmp_path: Path) -> None:
        timing = _timing([Segment.speech("Hi.")], durations=[1.0])
        pieces = page_pieces(timing, [tmp_path / "clip.wav"])
        assert [p.kind for p in pieces] == ["speech"]

    def test_missing_clip_raises_render_error(self) -> None:
        timing = _timing([Segment.speech("Hi.")], durations=[1.0])
        with pytest.raises(RenderError, match="synthesize its narration"):
            page_pieces(timing, [])


class TestBuildPageAudio:
    def test_concatenates_silences_and_clips_in_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clip = tmp_path / "clip.wav"
        silences: list[tuple[float, Path]] = []
        concatenated: list[list[Path]] = []

        def fake_silence(seconds: float, path: Path) -> Path:
            silences.append((seconds, path))
            return path

        monkeypatch.setattr("slidesonnet.audio.track.make_silence", fake_silence)
        monkeypatch.setattr(
            "slidesonnet.audio.track.concatenate_audio",
            lambda paths, out: concatenated.append(list(paths)),
        )
        monkeypatch.setattr("slidesonnet.audio.track.get_duration", lambda p: 3.8)

        timing = _timing(
            [Segment.speech("Hi."), Segment.pause(2.0)],
            durations=[1.0],
            lead=0.3,
            tail=0.5,
        )
        dur = build_page_audio(
            timing, [clip], tmp_path / "page-0001.wav", silence_dir=tmp_path / "sil"
        )

        assert dur == 3.8  # whatever the probe of the result says
        assert [s[0] for s in silences] == [0.3, 2.0, 0.5]
        (paths,) = concatenated
        assert paths[1] == clip  # lead silence, clip, pause, tail
        assert len(paths) == 4

    def test_empty_page_emits_minimal_silence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        silences: list[float] = []
        concatenated: list[list[Path]] = []
        monkeypatch.setattr(
            "slidesonnet.audio.track.make_silence",
            lambda seconds, path: silences.append(seconds) or path,
        )
        monkeypatch.setattr(
            "slidesonnet.audio.track.concatenate_audio",
            lambda paths, out: concatenated.append(list(paths)),
        )
        monkeypatch.setattr("slidesonnet.audio.track.get_duration", lambda p: 0.05)

        timing = _timing([])  # no narration at all
        build_page_audio(timing, [], tmp_path / "page.wav", silence_dir=tmp_path / "sil")

        assert silences == [0.05]  # the stream must exist for concat
        assert len(concatenated[0]) == 1


class TestAssembleTrack:
    def test_concatenates_and_probes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[list[Path], Path]] = []
        monkeypatch.setattr(
            "slidesonnet.audio.track.concatenate_audio",
            lambda paths, out: calls.append((list(paths), out)),
        )
        monkeypatch.setattr("slidesonnet.audio.track.get_duration", lambda p: 12.5)

        pages = [tmp_path / "p1.wav", tmp_path / "p2.wav"]
        out = tmp_path / "track.wav"
        assert assemble_track(pages, out) == 12.5
        assert calls == [(pages, out)]


def test_cue_sheet_zips_starts_and_ids() -> None:
    assert cue_sheet([0.0, 2.5], ["a", "b"]) == [(0.0, "a"), (2.5, "b")]
    with pytest.raises(ValueError):
        cue_sheet([0.0], ["a", "b"])  # misaligned inputs must not zip silently


def test_audio_piece_defaults() -> None:
    piece = AudioPiece(kind="silence", seconds=1.0)
    assert piece.path is None and piece.seconds == 1.0
