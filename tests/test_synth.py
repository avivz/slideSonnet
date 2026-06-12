"""Unit tests for cache-aware synthesis (mock TTS engine, no ffmpeg/kokoro)."""

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
        return "kokoro"

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


def test_uncached_targets_lists_missing_then_shrinks(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    deck = _deck()
    targets = synth_mod.uncached_targets(deck, Config(), tmp_path)
    assert len(targets) == 1  # one speech segment across the deck, nothing cached
    targets[0].parent.mkdir(parents=True, exist_ok=True)
    targets[0].write_bytes(b"RIFFfake")
    assert synth_mod.uncached_targets(deck, Config(), tmp_path) == []


def test_uncached_targets_only_ids(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    deck = _deck()
    assert synth_mod.uncached_targets(deck, Config(), tmp_path, only_ids={"b"}) == []
    assert len(synth_mod.uncached_targets(deck, Config(), tmp_path, only_ids={"a"})) == 1


def test_synthesize_second_run_hits_cache(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    engine = FakeEngine()
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: engine)
    deck = _deck()
    synth_mod.synthesize(deck, Config(), audio_dir=tmp_path)
    monkeypatch.setattr(synth_mod, "get_duration", lambda path: 1.25)
    results = synth_mod.synthesize(deck, Config(), audio_dir=tmp_path)
    assert results[("a", 0)].from_cache is True
    assert engine.calls == 1  # second run did not re-synthesize


def test_force_resynthesizes_cached_segments(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """force=True overwrites a cached clip — the 'regenerate' affordance."""
    engine = FakeEngine()
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: engine)
    deck = _deck()
    synth_mod.synthesize(deck, Config(), audio_dir=tmp_path)
    assert engine.calls == 1
    results = synth_mod.synthesize(deck, Config(), audio_dir=tmp_path, force=True)
    assert engine.calls == 2  # re-synthesized despite the cache hit
    assert results[("a", 0)].from_cache is False


def test_page_speech_clips_alignment(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    deck = _deck()
    results = synth_mod.synthesize(deck, Config(), audio_dir=tmp_path)
    clips = synth_mod.page_speech_clips(deck, results)
    assert clips == [[results[("a", 0)].path], []]  # page a has one clip, page b none
    assert clips[0][0].exists()
    # Un-synthesized segments are skipped (no placeholder paths).
    assert synth_mod.page_speech_clips(deck, {}) == [[], []]


def test_synthesize_reports_progress(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    calls: list[tuple[str, int, int]] = []
    synth_mod.synthesize(
        _deck(),
        Config(),
        audio_dir=tmp_path,
        progress=lambda sid, done, total: calls.append((sid, done, total)),
    )
    assert calls == [("a", 1, 1)]  # one speech segment in the whole deck


def test_cached_durations_estimates_when_uncached(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    # Nothing cached: "Hello there." is 2 words -> 2.0 s at 60 wpm; page b has no speech.
    durations = synth_mod.cached_durations(_deck(), Config(), tmp_path, fallback_wpm=60.0)
    assert durations == [[2.0], []]


def test_cached_durations_probes_cached_audio(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    deck = _deck()
    synth_mod.synthesize(deck, Config(), audio_dir=tmp_path)  # populate the cache
    monkeypatch.setattr(synth_mod, "get_duration", lambda path: 9.9)
    durations = synth_mod.cached_durations(deck, Config(), tmp_path, fallback_wpm=60.0)
    assert durations == [[9.9], []]  # real (probed) duration, not the wpm estimate
