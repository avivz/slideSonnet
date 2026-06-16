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
    calls: dict[str, Any] = {"synth": [], "compose": [], "track": []}

    def fake_synth(deck: Any, config: Any, *, audio_dir: Path, **kwargs: Any) -> dict[Any, Any]:
        calls["synth"].append(kwargs)
        clip = tmp_path / "clip.wav"
        results = {}
        for slide_id in deck.pages:
            block = deck.page_narration(slide_id)
            for i in range(len(block.speech_segments)):
                results[(slide_id, i)] = SynthResult(path=clip, duration=2.0, from_cache=True)
        return results

    def fake_track(timeline: Any, clips: Any, *, render_dir: Path) -> tuple[Path, list[Path]]:
        calls["track"].append(timeline)
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
    ) -> Path:
        calls["compose"].append(
            {"output": output, "page_audios": page_audios, "transitions": transitions}
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
