"""Unit tests for api.export / api.build_preview branching (mocked pipeline).

The heavy stages (TTS, ffmpeg) are stubbed at source; the timeline math,
mode coercion, and subtitle wiring run for real. The full pipeline is covered
by the export integration tier.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from slidesonnet import api
from slidesonnet.audio.synth import SynthResult
from slidesonnet.narration.model import Transition
from tests.conftest import prep_marked_deck as _prep


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Stub synthesis/compose/rasterize; record what the api orchestrates."""
    calls: dict[str, Any] = {"synth": [], "compose": [], "track": [], "track_progress": []}

    def fake_synth(deck: Any, config: Any, *, audio_dir: Path, **kwargs: Any) -> dict[Any, Any]:
        calls["synth"].append(kwargs)
        clip = tmp_path / "clip.wav"
        results = {}
        for slide_id in deck.pages:
            block = deck.page_narration(slide_id)
            for i in range(len(block.speech_segments)):
                results[(slide_id, i)] = SynthResult(path=clip, duration=2.0, from_cache=True)
        return results

    def fake_track(
        timeline: Any, clips: Any, *, render_dir: Path, progress: Any = None
    ) -> tuple[Path, list[Path]]:
        calls["track"].append(timeline)
        calls["track_progress"].append(progress)
        return tmp_path / "track.wav", [tmp_path / "p.wav" for _ in timeline.pages]

    def fake_compose(
        timeline: Any,
        images: Any,
        output: Path,
        *,
        config: Any,
        page_audios: Any,
        render_dir: Path,
        transitions: Any = None,
        audio_track: Any = None,
        progress: Any = None,
    ) -> Path:
        calls["compose"].append(
            {
                "progress": progress,
                "output": output,
                "page_audios": page_audios,
                "transitions": transitions,
                "audio_track": audio_track,
            }
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        return output

    monkeypatch.setattr("slidesonnet.audio.synth.synthesize", fake_synth)
    monkeypatch.setattr("slidesonnet.render.render_audio_track", fake_track)
    monkeypatch.setattr("slidesonnet.render.compose_video", fake_compose)
    monkeypatch.setattr("slidesonnet.api._images", lambda pdf, rdir: [tmp_path / "p.png"])
    return calls


def test_export_audible_synthesizes_and_passes_page_audio(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello there.\n")
    result = api.export(pdf, tmp_path / "out.mp4")
    assert len(pipeline["synth"]) == 1
    assert pipeline["compose"][0]["page_audios"] is not None
    # The continuous deck track is handed to compose so the morph can play over it.
    assert pipeline["compose"][0]["audio_track"] is not None
    assert result.silent is False
    assert result.duration > 0  # real timeline math ran
    assert result.video.exists()


def test_export_silent_coerces_tts_timing_to_estimate(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello there friends of mathematics.\n")
    result = api.export(pdf, tmp_path / "out.mp4", silent=True, timing="tts")
    assert pipeline["synth"] == []  # silent export must not synthesize
    assert pipeline["compose"][0]["page_audios"] is None
    assert result.silent is True
    assert result.duration > 0  # estimate mode produced durations without audio


def test_export_writes_requested_subtitle_formats(tmp_path: Path, pipeline: dict[str, Any]) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello.\n")

    result = api.export(pdf, tmp_path / "a.mp4")  # default: srt
    assert [p.suffix for p in result.subtitles] == [".srt"]

    result = api.export(pdf, tmp_path / "b.mp4", subtitles="both")
    assert [p.suffix for p in result.subtitles] == [".srt", ".vtt"]
    assert all(p.exists() for p in result.subtitles)

    result = api.export(pdf, tmp_path / "c.mp4", subtitles="none")
    assert result.subtitles == []


def test_export_passes_boundary_transitions_to_compose(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    # Two narrated slides with a wipe leaving the first: export hands compose the
    # per-boundary transitions instead of dropping them (or warning).
    pdf = _prep(tmp_path, "@intro-title\nHi.\n")
    sidecar = tmp_path / "marked.narration"
    text = sidecar.read_text(encoding="utf-8")
    sidecar.write_text(text + "  transition-out: wipeleft 0.5\n", encoding="utf-8")

    api.export(pdf, tmp_path / "out.mp4")
    transitions = pipeline["compose"][0]["transitions"]
    assert transitions is not None
    assert transitions[0] == Transition("wipeleft", 0.5)
    assert all(t.kind == "cut" for t in transitions[1:])


def test_build_preview_whole_deck(tmp_path: Path, pipeline: dict[str, Any]) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello.\n\n@euler-setup\nMore.\n")
    preview = api.build_preview(pdf)
    assert pipeline["synth"][0].get("only_ids") is None
    cue_ids = [sid for _, sid in preview.cues]
    assert "intro-title" in cue_ids and "euler-setup" in cue_ids
    assert preview.total_duration > 0
    assert preview.track == tmp_path / "track.wav"


def test_build_preview_only_id_restricts_synthesis_and_cues(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello.\n\n@euler-setup\nMore.\n")
    preview = api.build_preview(pdf, only_id="euler-setup")
    assert pipeline["synth"][0]["only_ids"] == {"euler-setup"}
    assert [sid for _, sid in preview.cues] == ["euler-setup"]


def test_export_leaves_an_unchanged_subtitle_file_untouched(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    """A re-render whose narration didn't move must not rewrite the .srt/.vtt.

    Downstream build graphs (make, watchers, rsync) key freshness on mtime; an
    unconditional rewrite marks every derived artifact stale after a slide-only
    re-render even though the subtitles are byte-identical.
    """
    import os

    pdf = _prep(tmp_path, "@intro-title\nHello.\n")
    first = api.export(pdf, tmp_path / "a.mp4", subtitles="both")
    old_stamp = 1_000_000_000  # well in the past, so a rewrite is unmistakable
    for p in first.subtitles:
        os.utime(p, (old_stamp, old_stamp))

    again = api.export(pdf, tmp_path / "a.mp4", subtitles="both")
    assert again.subtitles == first.subtitles  # still reported as outputs
    for p in again.subtitles:
        assert p.stat().st_mtime == old_stamp, f"{p.name} was rewritten with identical content"


def test_export_rewrites_a_subtitle_file_whose_content_changed(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello.\n")
    result = api.export(pdf, tmp_path / "a.mp4")
    srt = result.subtitles[0]
    srt.write_text("stale\n", encoding="utf-8")
    api.export(pdf, tmp_path / "a.mp4")
    assert srt.read_text(encoding="utf-8") != "stale\n"


def _seed_scratch(pdf: Path) -> dict[str, Path]:
    """Lay down every kind of render scratch an export leaves behind."""
    from slidesonnet.cache import render_dir

    rd = render_dir(pdf)
    files = {
        "page_wav": rd / "page-0001.wav",
        "track": rd / "track.wav",
        "manifest": rd / "track.cache.json",
        "silence": rd / "silence" / "2.0000s.wav",
        "segment": rd / "segments" / "seg-0001.mp4",
        "silent_video": rd / "silent.mp4",
        "page_png": rd / "pages" / "page-1.png",
    }
    for p in files.values():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return files


def test_export_prunes_render_scratch_but_keeps_page_images(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    """PCM page audio, the assembled track, silences, and per-slide clips exist
    only to feed ffmpeg once; a successful export drops them (~10× the size of
    the audio they came from). Page images stay — the editor filmstrip and the
    next export reuse them."""
    pdf = _prep(tmp_path, "@intro-title\nHello.\n")
    files = _seed_scratch(pdf)
    api.export(pdf, tmp_path / "out.mp4")
    assert files["page_png"].exists()
    gone = {k for k, p in files.items() if not p.exists()}
    assert gone == {"page_wav", "track", "manifest", "silence", "segment", "silent_video"}


def test_export_keep_scratch_argument_preserves_everything(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello.\n")
    files = _seed_scratch(pdf)
    api.export(pdf, tmp_path / "out.mp4", keep_scratch=True)
    assert all(p.exists() for p in files.values())


def test_export_keep_scratch_config_key_preserves_everything(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello.\n")
    (pdf.parent / "slidesonnet.toml").write_text("[video]\nkeep_scratch = true\n", encoding="utf-8")
    files = _seed_scratch(pdf)
    api.export(pdf, tmp_path / "out.mp4")
    assert all(p.exists() for p in files.values())


def test_export_leaves_scratch_when_compose_fails(
    tmp_path: Path, pipeline: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed render keeps its intermediates for debugging."""
    pdf = _prep(tmp_path, "@intro-title\nHello.\n")
    files = _seed_scratch(pdf)

    def boom(*args: Any, **kwargs: Any) -> Path:
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr("slidesonnet.render.compose_video", boom)
    with pytest.raises(RuntimeError):
        api.export(pdf, tmp_path / "out.mp4")
    assert all(p.exists() for p in files.values())


def test_export_threads_progress_through_every_phase(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    """TTS, audio assembly and the video render all report to the same callback."""
    pdf = _prep(tmp_path, "@intro-title\nHello there.\n")

    def cb(phase: str, done: int, total: int, label: str) -> None:
        return None

    api.export(pdf, tmp_path / "out.mp4", progress=cb)
    assert pipeline["synth"][0]["progress"] is cb
    assert pipeline["track_progress"] == [cb]
    assert pipeline["compose"][0]["progress"] is cb


def test_export_phases_follow_the_audio_mode() -> None:
    assert api.export_phases() == ("tts", "assemble", "video", "concat", "mux")
    assert api.export_phases(silent=True) == ("video", "concat")
    assert api.export_phases(timing="fixed:3") == ("video", "concat")
