"""Unit tests for the render timeline and subtitle cue construction (no ffmpeg)."""

from __future__ import annotations

import itertools
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
    # An explicit edge pause IS the slide's silence (replaces the default lead/tail):
    # a (speech only): 0.3 + 3 + 0.5; b (lone pause): 2.0 (no default lead/tail);
    # c (speech + trailing pause): 0.3 + 1 + 1 (pause is the end hold, no extra tail);
    # d (un-narrated -> lone default-hold pause): 2.5.
    assert tl.page_durations == pytest.approx([3.8, 2.0, 2.3, 2.5])


def test_page_starts_and_total() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    assert tl.page_starts == pytest.approx([0.0, 3.8, 5.8, 8.1])
    assert tl.total_duration == pytest.approx(10.6)


def test_cue_sheet() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    cues = tl.cue_sheet()
    assert [c[1] for c in cues] == ["a", "b", "c", "d"]
    assert cues[2][0] == pytest.approx(5.8)


def test_edge_pause_replaces_default_lead_and_tail() -> None:
    # A leading pause sets the start hold (no extra pre_silence); a trailing pause
    # sets the end hold (no extra tail_seconds). pause:0 means no hold at all.
    deck = Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["lead", "trail", "zero", "both"],
        narration={
            "lead": PageNarration("lead", [Segment.pause(1.0), Segment.speech("hi")]),
            "trail": PageNarration("trail", [Segment.speech("hi"), Segment.pause(1.0)]),
            "zero": PageNarration(
                "zero", [Segment.pause(0.0), Segment.speech("hi"), Segment.pause(0.0)]
            ),
            "both": PageNarration(
                "both", [Segment.pause(2.0), Segment.speech("hi"), Segment.pause(3.0)]
            ),
        },
    )
    tl = build_timeline(deck, _MODE, video=_VIDEO)  # 1 word = 1s
    durs = dict(zip(tl.slide_ids, tl.page_durations, strict=True))
    assert durs["lead"] == pytest.approx(1.0 + 1.0 + 0.5)  # explicit lead, default tail
    assert durs["trail"] == pytest.approx(0.3 + 1.0 + 1.0)  # default lead, explicit tail
    assert durs["zero"] == pytest.approx(1.0)  # both holds zeroed
    assert durs["both"] == pytest.approx(2.0 + 1.0 + 3.0)  # both explicit


def test_leading_and_trailing_silence_helpers() -> None:
    speech_only = PageNarration("a", [Segment.speech("hi")])
    assert speech_only.leading_silence(0.3) == pytest.approx(0.3)
    assert speech_only.trailing_silence(0.5) == pytest.approx(0.5)
    bracketed = PageNarration("b", [Segment.pause(1.0), Segment.speech("hi"), Segment.pause(2.0)])
    assert bracketed.leading_silence(0.3) == pytest.approx(1.0)
    assert bracketed.trailing_silence(0.5) == pytest.approx(2.0)


def test_subtitles_segment_granularity() -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    entries = subtitle_entries(_deck(), tl, granularity="segment")
    texts = [e.text for e in entries]
    assert texts == ["one two three", "four"]
    assert entries[0].start == pytest.approx(0.3)
    assert entries[1].start == pytest.approx(6.1)  # page c starts 5.8 + lead 0.3


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
    for prev, nxt in itertools.pairwise(entries):
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


def test_render_audio_track_reports_assembly_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assembly emits ('assemble', done, total) per page plus the final concat,
    so the editor can show a progress bar instead of a blind spinner."""
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    monkeypatch.setattr(
        "slidesonnet.render.build_page_audio",
        lambda timing, clips, out, *, silence_dir: out.write_bytes(b"p") or timing.duration,
    )
    monkeypatch.setattr(
        "slidesonnet.render.assemble_track",
        lambda audios, out: out.write_bytes(b"t") or 0.0,
    )

    ticks: list[tuple[str, int, int]] = []
    render_dir = tmp_path / "render"
    clips = [[tmp_path / "a.wav"], [], [tmp_path / "c.wav"], []]
    render_audio_track(
        tl,
        clips,
        render_dir=render_dir,
        progress=lambda label, done, total: ticks.append((label, done, total)),
    )

    total = len(tl.pages) + 1  # one tick per page, plus the final concat
    assert ticks, "no progress reported"
    assert all(label == "assemble" for label, _, _ in ticks)
    assert all(t == total for _, _, t in ticks)
    dones = [d for _, d, _ in ticks]
    assert dones == sorted(dones)  # monotonic
    assert dones[0] == 1 and dones[-1] == total  # starts at page 1, ends complete
    assert len(ticks) == total  # 4 pages + concat


def test_render_audio_track_caches_unchanged_pages_and_track(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    page_calls: list[str] = []
    track_calls: list[Path] = []

    def fake_build_page_audio(
        timing: PageTiming, speech_clips: list[Path], out_path: Path, *, silence_dir: Path
    ) -> float:
        page_calls.append(timing.slide_id)
        out_path.write_bytes(b"wav")  # the cache only reuses a page whose file exists
        return timing.duration

    def fake_assemble_track(page_audios: list[Path], out_path: Path) -> float:
        track_calls.append(out_path)
        out_path.write_bytes(b"track")
        return sum(tl.page_durations)

    monkeypatch.setattr("slidesonnet.render.build_page_audio", fake_build_page_audio)
    monkeypatch.setattr("slidesonnet.render.assemble_track", fake_assemble_track)

    render_dir = tmp_path / "render"
    a, c = tmp_path / "a.wav", tmp_path / "c.wav"
    a.write_bytes(b"a")
    c.write_bytes(b"c")
    clips = [[a], [], [c], []]

    render_audio_track(tl, clips, render_dir=render_dir)
    assert len(page_calls) == 4 and len(track_calls) == 1  # cold build: every page + track

    page_calls.clear()
    track_calls.clear()
    render_audio_track(tl, clips, render_dir=render_dir)
    assert page_calls == [] and track_calls == []  # nothing changed: no ffmpeg at all

    page_calls.clear()
    track_calls.clear()
    a.write_bytes(b"a-regenerated")  # slide 'a' clip changed (new size/mtime)
    render_audio_track(tl, clips, render_dir=render_dir)
    assert page_calls == ["a"]  # only the touched page rebuilds
    assert len(track_calls) == 1  # and the deck track re-assembles because a page changed


def test_render_audio_track_rebuilds_when_output_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    page_calls: list[str] = []

    def fake_build_page_audio(
        timing: PageTiming, speech_clips: list[Path], out_path: Path, *, silence_dir: Path
    ) -> float:
        page_calls.append(timing.slide_id)
        out_path.write_bytes(b"wav")
        return timing.duration

    monkeypatch.setattr("slidesonnet.render.build_page_audio", fake_build_page_audio)
    monkeypatch.setattr(
        "slidesonnet.render.assemble_track", lambda audios, out: out.write_bytes(b"t") or 0.0
    )

    render_dir = tmp_path / "render"
    a, c = tmp_path / "a.wav", tmp_path / "c.wav"
    a.write_bytes(b"a")
    c.write_bytes(b"c")
    clips = [[a], [], [c], []]
    render_audio_track(tl, clips, render_dir=render_dir)
    page_calls.clear()
    (render_dir / "page-0002.wav").unlink()  # a stale/missing file must not be trusted
    render_audio_track(tl, clips, render_dir=render_dir)
    assert page_calls == ["b"]  # only the deleted page is rebuilt


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


def _fake_silent_recorder(
    sink: list[tuple[Path, Path, float]],
) -> object:
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
        sink.append((image, output, duration))

    return fake_silent


def test_compose_video_with_audio_sizes_silent_segments_and_muxes_track(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tl = build_timeline(_deck(), _MODE, video=_VIDEO, default_hold=2.5)
    audio_durations = {f"page-{i:04d}.wav": float(i) for i in range(1, 5)}
    silent_calls: list[tuple[Path, Path, float]] = []
    concat_calls: list[tuple[list[Path], Path]] = []
    mux_calls: list[tuple[Path, Path, Path]] = []

    monkeypatch.setattr(
        "slidesonnet.render.compose_silent_segment", _fake_silent_recorder(silent_calls)
    )
    monkeypatch.setattr(
        "slidesonnet.render.concatenate_segments",
        lambda segments, output: concat_calls.append((segments, output)),
    )
    monkeypatch.setattr(
        "slidesonnet.video.composer.mux_audio",
        lambda video, audio, output: mux_calls.append((video, audio, output)),
    )
    monkeypatch.setattr(
        "slidesonnet.video.composer.get_duration",
        lambda path: audio_durations[path.name],
    )

    images = [tmp_path / f"p{i}.png" for i in range(1, 5)]
    audios = [tmp_path / f"page-{i:04d}.wav" for i in range(1, 5)]
    track = tmp_path / "track.wav"
    output = tmp_path / "deck.mp4"
    rdir = tmp_path / "r"
    compose_video(
        tl,
        images,
        output,
        config=Config(),
        page_audios=audios,
        render_dir=rdir,
        audio_track=track,
    )

    # Every page is a silent segment sized from the real audio length (no cuts).
    assert [c[0] for c in silent_calls] == images
    assert [c[2] for c in silent_calls] == pytest.approx([1.0, 2.0, 3.0, 4.0])
    # The silent video is assembled to an intermediate, then the continuous deck
    # track is muxed over it into the final output.
    silent_video = rdir / "silent.mp4"
    assert concat_calls == [
        ([rdir / "segments" / f"seg-{i:04d}.mp4" for i in range(1, 5)], silent_video)
    ]
    assert mux_calls == [(silent_video, track, output)]


def test_compose_video_centers_transition_and_preserves_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two slides, 4s each, with a 1s wipe between them.
    deck = Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b"],
        narration={
            "a": PageNarration("a", [Segment.speech("x")]),
            "b": PageNarration("b", [Segment.speech("y")]),
        },
    )
    tl = build_timeline(
        deck, TimingMode("fixed", fixed_seconds=4), video=VideoConfig(pre_silence=0, tail_seconds=0)
    )
    silent_calls: list[tuple[Path, Path, float]] = []
    trans_calls: list[tuple[Path, Path, float, str]] = []
    concat_calls: list[tuple[list[Path], Path]] = []

    monkeypatch.setattr(
        "slidesonnet.render.compose_silent_segment", _fake_silent_recorder(silent_calls)
    )
    monkeypatch.setattr(
        "slidesonnet.render.concatenate_segments",
        lambda segments, output: concat_calls.append((segments, output)),
    )

    def fake_trans(
        a: Path, b: Path, out: Path, *, duration: float, transition: str, **kw: object
    ) -> None:
        trans_calls.append((a, b, duration, transition))

    monkeypatch.setattr("slidesonnet.video.composer.compose_transition_clip", fake_trans)

    from slidesonnet.narration.model import Transition

    images = [tmp_path / "a.png", tmp_path / "b.png"]
    output = tmp_path / "deck.mp4"
    compose_video(
        tl,
        images,
        output,
        config=Config(),
        page_audios=None,
        render_dir=tmp_path / "r",
        transitions=[Transition("wipeleft", 1.0)],
    )

    # 1s wipe centered on the boundary: 0.5s trimmed off each slide's facing edge.
    assert [c[2] for c in silent_calls] == pytest.approx([3.5, 3.5])
    assert trans_calls and trans_calls[0][2] == pytest.approx(1.0)
    assert trans_calls[0][3] == "wipeleft"
    # Pieces interleave seg/morph/seg; total = 3.5 + 1.0 + 3.5 = 8.0 = sum of slides.
    pieces = concat_calls[0][0]
    assert len(pieces) == 3
    assert sum(c[2] for c in silent_calls) + 1.0 == pytest.approx(8.0)


def test_transition_morph_seconds_clamps_to_shorter_slide() -> None:
    from slidesonnet.narration.model import Transition
    from slidesonnet.render import transition_morph_seconds

    # boundary 0: 2s wipe but slide b is only 0.3s -> clamped to 0.3.
    # boundary 1: a cut contributes nothing.
    morph = transition_morph_seconds(
        [Transition("wipeleft", 2.0), Transition("cut", 0.0)],
        [5.0, 0.3, 5.0],
    )
    assert morph == pytest.approx([0.3, 0.0])


def test_tts_timeline_uses_supplied_durations() -> None:
    deck = _deck()
    # one speech segment on page a, one on page c
    durations = [[1.5], [], [2.0], []]
    tl = build_timeline(
        deck, TimingMode("tts"), video=_VIDEO, speech_durations_by_page=durations, default_hold=2.5
    )
    assert tl.page_durations[0] == pytest.approx(0.3 + 1.5 + 0.5)
    # page c ends with a pause -> that pause is the end hold, no extra tail.
    assert tl.page_durations[2] == pytest.approx(0.3 + 2.0 + 1.0)


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
