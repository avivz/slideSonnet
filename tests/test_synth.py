"""Unit tests for cache-aware synthesis (mock TTS engine, no ffmpeg/piper)."""

from __future__ import annotations

from pathlib import Path

from slidesonnet.audio import synth as synth_mod
from slidesonnet.config import Config
from slidesonnet.narration.model import Deck, PageNarration, Segment
from slidesonnet.tts.base import TTSEngine


class FakeEngine(TTSEngine):
    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        self.calls += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFFfake")
        return 1.25

    def name(self) -> str:
        return "piper"

    def cache_key(self) -> str:
        return "fake"


def _deck() -> Deck:
    return Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b"],
        narration={
            "a": PageNarration("a", [Segment.speech("Hello there."), Segment.pause(1.0)]),
            "b": PageNarration("b", [Segment.pause(2.0)]),  # silent
        },
    )


def test_synthesize_writes_and_durations(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    engine = FakeEngine()
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: engine)
    results = synth_mod.synthesize(_deck(), Config(), audio_dir=tmp_path)
    assert ("a", 0) in results
    assert results[("a", 0)].duration == 1.25
    assert results[("a", 0)].from_cache is False
    assert engine.calls == 1  # only one speech segment across the deck


def test_page_speech_durations_alignment(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    deck = _deck()
    results = synth_mod.synthesize(deck, Config(), audio_dir=tmp_path)
    durations = synth_mod.page_speech_durations(deck, results)
    assert durations == [[1.25], []]  # page a has 1 speech clip, page b none


def test_only_ids_restricts(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    engine = FakeEngine()
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: engine)
    synth_mod.synthesize(_deck(), Config(), audio_dir=tmp_path, only_ids={"b"})
    assert engine.calls == 0  # page b has no speech, page a skipped
