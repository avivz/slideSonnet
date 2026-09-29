"""The quick export (``--fast``): one slideshow pass at 720p, cuts, the same audio.

The full-quality path is pinned elsewhere (the composer argv tests and the
strict fakes in ``test_render.py``); these tests cover what ``fast`` switches.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from slidesonnet import api
from slidesonnet.cli import main
from slidesonnet.config import Config
from slidesonnet.models import VideoConfig
from slidesonnet.narration.model import Deck, PageNarration, Segment, Transition
from slidesonnet.render import (
    build_timeline,
    compose_video,
    fast_video,
    track_aac,
    wav_seconds,
)
from slidesonnet.timing import TimingMode
from slidesonnet.video.composer import compose_slideshow
from tests.conftest import prep_marked_deck, write_pdf
from tests.test_api_export import pipeline  # noqa: F401  (fixture)


@pytest.mark.parametrize(
    ("resolution", "expected"),
    [("1920x1080", "1280x720"), ("1440x1080", "960x720"), ("3840x2160", "1280x720"),
     ("854x480", "854x480")],
)  # fmt: skip
def test_fast_video_is_720p_at_most_with_a_quick_encoder(resolution: str, expected: str) -> None:
    v = VideoConfig(resolution=resolution, fps=30, crf=18, preset="slow", pre_silence=0.2)
    fast = fast_video(v)
    assert fast.resolution == expected
    assert (fast.preset, fast.crf) == ("veryfast", 26)
    # the timing knobs stay, so the audio track and subtitles don't move
    assert (fast.fps, fast.pre_silence, fast.tail_seconds) == (30, 0.2, v.tail_seconds)


@pytest.mark.parametrize(
    ("given", "expected"),
    [("out/deck.mp4", "out/deck.fast.mp4"), ("deck.fast.mp4", "deck.fast.mp4"),
     ("deck.draft.mp4", "deck.draft.fast.mp4")],
)  # fmt: skip
def test_fast_output_name(given: str, expected: str) -> None:
    assert api.fast_output(Path(given)) == Path(expected)


@patch("slidesonnet.video.composer._run_ffmpeg")
def test_compose_slideshow_argv_and_list(mock_ffmpeg: MagicMock, tmp_path: Path) -> None:
    """One frame per still (split so no frame outlasts a second), exact durations,
    the last entry repeated (the concat demuxer drops the last duration), VFR out."""
    seen: list[tuple[list[str], str]] = []
    mock_ffmpeg.side_effect = lambda cmd, **kw: seen.append(
        (cmd, Path(cmd[cmd.index("-i") + 1]).read_text())
    )
    a, b, out = tmp_path / "a.png", tmp_path / "b.png", tmp_path / "v.mp4"
    compose_slideshow(
        [a, b], [2.5, 0.75], out, scratch=tmp_path / "r", resolution="1280x720", crf=26,
        preset="veryfast",
    )  # fmt: skip

    [(cmd, text)] = seen
    listing = Path(cmd[cmd.index("-i") + 1])
    assert listing.parent == tmp_path / "r" and not listing.exists()
    pad = (
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p"
    )
    assert cmd == [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-an",
        "-c:v", "libx264", "-tune", "stillimage", "-vf", pad,
        "-fps_mode", "vfr", "-preset", "veryfast", "-crf", "26", str(out),
    ]  # fmt: skip
    a_entry = f"file '{a.resolve()}'\nduration 0.833333\n"
    assert text == a_entry * 3 + f"file '{b.resolve()}'\nduration 0.750000\nfile '{b.resolve()}'\n"


def _two_slides() -> Deck:
    return Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b"],
        narration={
            "a": PageNarration("a", [Segment.speech("x")]),
            "b": PageNarration("b", [Segment.speech("y")]),
        },
    )


def test_compose_video_fast_is_one_slideshow_pass_with_cuts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No per-slide clips and no morphs: one encode of the stills at the fast
    settings, the track's AAC made alongside it, then a stream copy."""
    tl = build_timeline(
        _two_slides(), TimingMode("fixed", fixed_seconds=4), video=VideoConfig(pre_silence=0)
    )
    unexpected = MagicMock(side_effect=AssertionError("full-quality path used"))
    monkeypatch.setattr("slidesonnet.render.compose_silent_segment", unexpected)
    monkeypatch.setattr("slidesonnet.video.composer.compose_transition_clip", unexpected)
    monkeypatch.setattr("slidesonnet.video.composer.get_duration", lambda path: 4.0)
    shows: list[dict[str, Any]] = []

    def fake_show(images: list[Path], durations: list[float], out: Path, **kw: Any) -> None:
        shows.append({"images": images, "durations": durations, **kw})
        out.touch()

    monkeypatch.setattr("slidesonnet.video.composer.compose_slideshow", fake_show)
    monkeypatch.setattr("slidesonnet.render.track_aac", lambda track, rdir: tmp_path / "t.m4a")
    muxed: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        "slidesonnet.video.composer.mux_copy",
        lambda v, a, out, **kw: muxed.append((v, a)) or out.touch(),
    )

    images = [tmp_path / "a.png", tmp_path / "b.png"]
    out = compose_video(
        tl,
        images,
        tmp_path / "deck.fast.mp4",
        config=Config(),
        page_audios=[tmp_path / "a.wav", tmp_path / "b.wav"],
        render_dir=tmp_path / "r",
        transitions=[Transition("wipeleft", 1.0)],
        audio_track=tmp_path / "track.wav",
        fast=True,
    )

    [show] = shows
    assert show["images"] == images and show["durations"] == [4.0, 4.0]  # a cut: no trim
    assert (show["resolution"], show["preset"], show["crf"]) == ("1280x720", "veryfast", 26)
    assert muxed == [(tmp_path / "r" / "silent.mp4", tmp_path / "t.m4a")]
    assert out.exists() and not (tmp_path / "r" / "segments").exists()


@patch("slidesonnet.video.composer._run_ffmpeg")
def test_track_aac_is_reused_while_the_track_is_unchanged(
    mock_ffmpeg: MagicMock, tmp_path: Path
) -> None:
    mock_ffmpeg.side_effect = lambda cmd, **kw: Path(cmd[-1]).write_bytes(b"aac")
    track = tmp_path / "track.wav"
    track.write_bytes(b"one")
    first = track_aac(track, tmp_path)
    assert first == tmp_path / "track.m4a" and first.read_bytes() == b"aac"
    # the encoder settings of the full export's mux, so the audio is the same
    assert mock_ffmpeg.call_args.args[0][:-1] == [
        "ffmpeg", "-y", "-i", str(track), "-vn", "-c:a", "aac", "-b:a", "192k",
    ]  # fmt: skip
    assert track_aac(track, tmp_path) == first
    assert mock_ffmpeg.call_count == 1
    track.write_bytes(b"two")  # new narration: a new track, so a new encode
    track_aac(track, tmp_path)
    assert mock_ffmpeg.call_count == 2


def test_fast_export_keeps_the_audio_and_writes_a_separate_file(
    tmp_path: Path,
    pipeline: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pruned: list[Path] = []
    monkeypatch.setattr("slidesonnet.render.prune_render_scratch", lambda d: pruned.append(d) or 0)
    pdf = prep_marked_deck(tmp_path, "@intro-title\nHello there.\n")

    full = api.export(pdf, tmp_path / "deck.mp4")
    fast = api.export(pdf, tmp_path / "deck.mp4", fast=True)

    assert (full.video.name, fast.video.name) == ("deck.mp4", "deck.fast.mp4")
    assert [c["fast"] for c in pipeline["compose"]] == [False, True]
    # the same clips, the same track, the same subtitles
    assert pipeline["synth"][0] == pipeline["synth"][1]
    assert [t.page_durations for t in pipeline["track"]] == [
        pipeline["track"][0].page_durations
    ] * 2
    assert full.subtitles[0].read_text() == fast.subtitles[0].read_text()
    # a quick export keeps the assembled audio for the next one
    assert len(pruned) == 1


def test_cli_fast_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_export(pdf: Path, output: Path, **kwargs: Any) -> api.ExportResult:
        seen.update(kwargs)
        return api.ExportResult(video=api.fast_output(output), duration=1.0)

    monkeypatch.setattr("slidesonnet.api.export", fake_export)
    pdf = write_pdf(tmp_path / "deck.pdf", ["a"])
    result = CliRunner().invoke(
        main, ["--no-log-file", "export", str(pdf), "-o", str(tmp_path / "deck.mp4"), "--fast"]
    )
    assert result.exit_code == 0, result.output
    assert seen["fast"] is True
    assert "deck.fast.mp4" in result.output


def test_wav_seconds_reads_the_header_and_falls_back_to_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import wave

    page = tmp_path / "page.wav"
    with wave.open(str(page), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 36000)
    monkeypatch.setattr("slidesonnet.video.composer.get_duration", lambda path: 9.0)
    assert wav_seconds(page) == 1.5
    assert wav_seconds(tmp_path / "not-a-wav.mp3") == 9.0
