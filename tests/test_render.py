"""Unit tests for the render timeline and subtitle cue construction (no ffmpeg)."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.config import Config
from slidesonnet.models import VideoConfig
from slidesonnet.narration.model import Deck, PageNarration, Segment
from slidesonnet.render import build_timeline, compose_video, render_audio_track, subtitle_entries
from slidesonnet.timing import PageTiming, TimingMode


def _deck() -> Deck:
    narration = {
        "a": PageNarration("a", [Segment.speech("one two three")]),
        "b": PageNarration("b", [Segment.pause(2.0)]),
        "c": PageNarration("c", [Segment.speech("four"), Segment.pause(1.0)]),
    }
    return Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b", "c", "d"],  # 'd' un-narrated
        narration=narration,
    )


_VIDEO = VideoConfig(pre_silence=0.3, tail_seconds=0.5)
_MODE = TimingMode("estimate", wpm=60)  # 1 word/sec


def test_page_durations() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    # a: 0.3 + 3 + 0.5; b: 0.3 + 2 + 0.5; c: 0.3 + (1+1) + 0.5; d: 0.3 + 2.5 + 0.5
    assert tl.page_durations == pytest.approx([3.8, 2.8, 2.8, 3.3])


def test_page_starts_and_total() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    assert tl.page_starts == pytest.approx([0.0, 3.8, 6.6, 9.4])
    assert tl.total_duration == pytest.approx(12.7)


def test_cue_sheet() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    cues = tl.cue_sheet()
    assert [c[1] for c in cues] == ["a", "b", "c", "d"]
    assert cues[2][0] == pytest.approx(6.6)


def test_subtitles_segment_granularity() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    entries = subtitle_entries(_deck(), tl, granularity="segment")
    texts = [e.text for e in entries]
    assert texts == ["one two three", "four"]
    assert entries[0].start == pytest.approx(0.3)
    assert entries[1].start == pytest.approx(6.9)  # 6.6 + lead 0.3


def test_subtitles_slide_granularity() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    entries = subtitle_entries(_deck(), tl, granularity="slide")
    assert [e.text for e in entries] == ["one two three", "four"]


def test_subtitles_split_long_segment_proportionally() -> None:
    text = "First sentence is fairly long indeed. Second sentence is also fairly long indeed."
    deck = Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a"],
        narration={"a": PageNarration("a", [Segment.speech(text)])},
    )
    tl = build_timeline(deck, _MODE, video=_VIDEO)
    entries = subtitle_entries(deck, tl, granularity="segment", max_chars=40)
    assert len(entries) >= 2
    assert [e.index for e in entries] == list(range(1, len(entries) + 1))
    assert " ".join(e.text for e in entries) == text
    # Cues tile the speech segment exactly: contiguous, spanning start to end.
    seg = tl.pages[0].speech_timings[0]
    assert entries[0].start == pytest.approx(seg.start)
    assert entries[-1].end == pytest.approx(seg.end)
    for prev, nxt in zip(entries, entries[1:], strict=False):
        assert prev.end == pytest.approx(nxt.start)
    # Each cue's span is proportional to its share of the chunk characters.
    total_chars = sum(len(e.text) for e in entries)
    for e in entries:
        expected = seg.duration * len(e.text) / total_chars
        assert e.end - e.start == pytest.approx(expected)


def test_render_audio_track_orchestration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    page_calls: list[tuple[str, list[Path], Path, Path]] = []
    track_calls: list[tuple[list[Path], Path]] = []

    def fake_build_page_audio(
        timing: PageTiming, speech_clips: list[Path], out_path: Path, *, silence_dir: Path
    ) -> float:
        page_calls.append((timing.slide_id, speech_clips, out_path, silence_dir))
        return timing.duration

    def fake_assemble_track(page_audios: list[Path], out_path: Path) -> float:
        track_calls.append((page_audios, out_path))
        return sum(tl.page_durations)

    monkeypatch.setattr("slidesonnet.render.build_page_audio", fake_build_page_audio)
    monkeypatch.setattr("slidesonnet.render.assemble_track", fake_assemble_track)

    render_dir = tmp_path / "render"
    clips = [[tmp_path / "a.wav"], [], [tmp_path / "c.wav"], []]
    track, page_audios = render_audio_track(tl, clips, render_dir=render_dir)

    assert track == render_dir / "track.wav"
    assert (render_dir / "silence").is_dir()
    assert [p.name for p in page_audios] == [f"page-{i:04d}.wav" for i in range(1, 5)]
    # One build per page, in deck order, with that page's clips and shared silence dir.
    assert [(c[0], c[1]) for c in page_calls] == list(zip(tl.slide_ids, clips, strict=True))
    assert all(c[3] == render_dir / "silence" for c in page_calls)
    assert track_calls == [(page_audios, track)]


def test_compose_video_silent_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    silent_calls: list[tuple[Path, Path, float, str, int, int, str]] = []
    concat_calls: list[tuple[list[Path], Path]] = []

    def fake_silent(
        image: Path,
        output: Path,
        *,
        duration: float,
        resolution: str,
        fps: int,
        crf: int,
        preset: str,
    ) -> None:
        silent_calls.append((image, output, duration, resolution, fps, crf, preset))

    def fake_concat(segments: list[Path], output: Path) -> None:
        concat_calls.append((segments, output))

    monkeypatch.setattr("slidesonnet.render.compose_silent_segment", fake_silent)
    monkeypatch.setattr("slidesonnet.render.concatenate_segments", fake_concat)

    config = Config()
    images = [tmp_path / f"p{i}.png" for i in range(1, 5)]
    output = tmp_path / "out" / "deck.mp4"
    result = compose_video(
        tl, images, output, config=config, page_audios=None, render_dir=tmp_path / "r"
    )

    assert result == output
    assert output.parent.is_dir()
    # One silent segment per page, timed from the timeline, styled from config.
    assert [c[0] for c in silent_calls] == images
    assert [c[2] for c in silent_calls] == pytest.approx(tl.page_durations)
    v = config.video
    assert all(c[3:] == (v.resolution, v.fps, v.crf, v.preset) for c in silent_calls)
    expected_segs = [tmp_path / "r" / "segments" / f"seg-{i:04d}.mp4" for i in range(1, 5)]
    assert concat_calls == [(expected_segs, output)]


def test_compose_video_with_audio_uses_real_durations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    audio_durations = {f"page-{i:04d}.wav": float(i) for i in range(1, 5)}
    seg_calls: list[tuple[Path, Path, Path, float, float, float]] = []

    def fake_segment(
        image: Path,
        audio: Path,
        output: Path,
        *,
        duration: float,
        pre_silence: float,
        pad_seconds: float,
        resolution: str,
        fps: int,
        crf: int,
        preset: str,
    ) -> None:
        seg_calls.append((image, audio, output, duration, pre_silence, pad_seconds))

    monkeypatch.setattr("slidesonnet.render.compose_segment", fake_segment)
    monkeypatch.setattr("slidesonnet.render.concatenate_segments", lambda segments, output: None)
    # get_duration is imported lazily inside compose_video, so patch it at source.
    monkeypatch.setattr(
        "slidesonnet.video.composer.get_duration",
        lambda path: audio_durations[path.name],
    )

    images = [tmp_path / f"p{i}.png" for i in range(1, 5)]
    audios = [tmp_path / f"page-{i:04d}.wav" for i in range(1, 5)]
    output = tmp_path / "deck.mp4"
    compose_video(
        tl, images, output, config=Config(), page_audios=audios, render_dir=tmp_path / "r"
    )

    assert [(c[0], c[1]) for c in seg_calls] == list(zip(images, audios, strict=True))
    # Segment length comes from the audio file, with no extra padding or lead.
    assert [c[3] for c in seg_calls] == [1.0, 2.0, 3.0, 4.0]
    assert all(c[4] == 0.0 and c[5] == 0.0 for c in seg_calls)


def test_tts_timeline_uses_supplied_durations() -> None:
    deck = _deck()
    # one speech segment on page a, one on page c
    durations = [[1.5], [], [2.0], []]
    tl = build_timeline(
        deck, TimingMode("tts"), video=_VIDEO, speech_durations_by_page=durations, default_hold=2.5
    )
    assert tl.page_durations[0] == pytest.approx(0.3 + 1.5 + 0.5)
    assert tl.page_durations[2] == pytest.approx(0.3 + 2.0 + 1.0 + 0.5)


def test_page_pieces_clear_error_when_speech_clip_missing() -> None:
    import pytest

    from slidesonnet.audio.track import page_pieces
    from slidesonnet.exceptions import RenderError
    from slidesonnet.narration.model import Segment
    from slidesonnet.timing import PageTiming, SegmentTiming

    seg = Segment.speech("hello")
    timing = PageTiming(
        slide_id="lonely",
        duration=2.0,
        lead=0.5,
        tail=0.5,
        segments=[SegmentTiming(segment=seg, start=0.5, end=1.5)],
    )
    with pytest.raises(RenderError, match="lonely"):
        page_pieces(timing, [])
