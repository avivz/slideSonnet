"""Tests for the headless api layer (sty/init/check)."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet import api
from slidesonnet.tts.base import TTSEngine
from tests.conftest import simple_narration

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def test_sty_text_has_macro() -> None:
    assert "\\ssid" in api.sty_text()


def test_packaged_sty_matches_repo_root() -> None:
    root = (Path(__file__).parent.parent / "slidesonnet.sty").read_text(encoding="utf-8")
    assert api.sty_text() == root  # guard against drift


def test_write_sty_to_dir(tmp_path: Path) -> None:
    written = api.write_sty(tmp_path)
    assert written == tmp_path / "slidesonnet.sty"
    assert written.exists()


def test_init_then_check(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    sidecar = api.init_sidecar(pdf)
    assert sidecar.exists()
    diags = api.check_deck(pdf)
    # blank scaffold -> no errors (all ids present), warnings for empty narration? No: blocks exist
    assert not any(d.severity == "error" for d in diags)


def test_init_force_overwrites(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    sidecar = api.init_sidecar(pdf)
    sidecar.write_text("@intro-title\nEdited.\n", encoding="utf-8")
    api.init_sidecar(pdf, force=True)
    assert "Edited." not in sidecar.read_text(encoding="utf-8")


def test_init_no_overwrite_raises(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    api.init_sidecar(pdf)
    with pytest.raises(FileExistsError):
        api.init_sidecar(pdf)


class _FakeEngine(TTSEngine):
    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        raise AssertionError("write_subs must never synthesize")

    def name(self) -> str:
        return "kokoro"

    def cache_key(self) -> str:
        return "fake"


class _WritingEngine(_FakeEngine):
    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        self.calls += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFFfake")
        return 1.0


def _narrated_deck(tmp_path: Path) -> Path:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    (tmp_path / "marked.narration").write_text(
        simple_narration("@intro-title\nHello world from the deck.\n"), encoding="utf-8"
    )
    return pdf


def test_synthesize_deck_counts_new_clips_and_overrides_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _WritingEngine()
    seen: dict[str, str] = {}

    def factory(cfg: object) -> _WritingEngine:
        seen["backend"] = cfg.backend  # type: ignore[attr-defined]
        return engine

    monkeypatch.setattr("slidesonnet.audio.synth.create_tts", factory)
    pdf = _narrated_deck(tmp_path)
    n = api.synthesize_deck(pdf, engine="inworld")
    assert n == 1  # one speech segment, newly synthesized
    assert engine.calls == 1
    assert seen["backend"] == "inworld"  # engine override reached the factory
    # Second run is fully cached (duration probed, not synthesized).
    monkeypatch.setattr("slidesonnet.audio.synth.get_duration", lambda path: 1.0)
    assert api.synthesize_deck(pdf, engine="inworld") == 0
    assert engine.calls == 1


def test_write_subs_estimate_mode(tmp_path: Path) -> None:
    pdf = _narrated_deck(tmp_path)
    out = tmp_path / "marked.vtt"
    assert api.write_subs(pdf, out, fmt="vtt", timing="estimate") == out
    text = out.read_text(encoding="utf-8")
    assert text.startswith("WEBVTT")
    assert "Hello world from the deck." in text


def test_write_subs_tts_mode_estimates_uncached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("slidesonnet.audio.synth.create_tts", lambda cfg: _FakeEngine())
    pdf = _narrated_deck(tmp_path)
    out = tmp_path / "marked.srt"
    assert api.write_subs(pdf, out, timing="tts") == out
    text = out.read_text(encoding="utf-8")
    assert "Hello world from the deck." in text
    assert "-->" in text


def _timeline_for(pdf: Path) -> tuple[object, object]:
    from slidesonnet.deck import load_deck
    from slidesonnet.models import VideoConfig
    from slidesonnet.render import build_timeline
    from slidesonnet.timing import parse_timing

    deck, _ = load_deck(pdf)
    return deck, build_timeline(deck, parse_timing("estimate"), video=VideoConfig())


def test_write_subtitle_files_none(tmp_path: Path) -> None:
    deck, timeline = _timeline_for(_narrated_deck(tmp_path))
    paths = api._write_subtitle_files(deck, timeline, tmp_path / "v.mp4", "none", "segment")  # type: ignore[arg-type]
    assert paths == []
    assert not (tmp_path / "v.srt").exists()
    assert not (tmp_path / "v.vtt").exists()


def test_write_subtitle_files_both(tmp_path: Path) -> None:
    deck, timeline = _timeline_for(_narrated_deck(tmp_path))
    paths = api._write_subtitle_files(deck, timeline, tmp_path / "v.mp4", "both", "segment")  # type: ignore[arg-type]
    assert [p.name for p in paths] == ["v.srt", "v.vtt"]
    assert all(p.exists() for p in paths)
    assert paths[1].read_text(encoding="utf-8").startswith("WEBVTT")
    assert "Hello world from the deck." in paths[0].read_text(encoding="utf-8")


def test_write_subtitle_files_single_format(tmp_path: Path) -> None:
    deck, timeline = _timeline_for(_narrated_deck(tmp_path))
    srt = api._write_subtitle_files(deck, timeline, tmp_path / "v.mp4", "srt", "slide")  # type: ignore[arg-type]
    assert [p.suffix for p in srt] == [".srt"]
    vtt = api._write_subtitle_files(deck, timeline, tmp_path / "w.mp4", "vtt", "segment")  # type: ignore[arg-type]
    assert [p.suffix for p in vtt] == [".vtt"]
    assert not (tmp_path / "w.srt").exists()
