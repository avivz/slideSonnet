"""Unit tests for cache-aware synthesis (mock TTS engine, no ffmpeg/kokoro)."""

from __future__ import annotations

from pathlib import Path

from slidesonnet.audio import synth as synth_mod
from slidesonnet.config import Config
from slidesonnet.models import TTSConfig
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


def _two_line_deck() -> Deck:
    return Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b"],
        narration={
            "a": PageNarration("a", [Segment.speech("One."), Segment.speech("Two.")]),
            "b": PageNarration("b", [Segment.speech("Three.")]),
        },
    )


def test_only_segments_targets_one_utterance(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The editor's per-utterance generate synthesizes exactly the targeted pair."""
    engine = FakeEngine()
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: engine)
    deck = _two_line_deck()
    results = synth_mod.synthesize(deck, Config(), audio_dir=tmp_path, only_segments={("a", 1)})
    assert engine.calls == 1
    assert set(results) == {("a", 1)}


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
    calls: list[tuple[str, int, int, str]] = []
    synth_mod.synthesize(
        _deck(),
        Config(),
        audio_dir=tmp_path,
        progress=lambda phase, done, total, label: calls.append((phase, done, total, label)),
    )
    assert calls == [("tts", 1, 1, "a")]  # one speech segment in the whole deck


def test_cached_durations_estimates_when_uncached(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    # Nothing cached: "Hello there." is 2 words -> 2.0 s at 60 wpm; page b has no speech.
    cached = synth_mod.cached_durations(_deck(), Config(), tmp_path, fallback_wpm=60.0)
    assert cached.per_page == [[2.0], []]
    # ...and it says so, instead of passing the guess off as the real timeline.
    assert [r.slide_id for r in cached.estimated] == ["a"]
    assert cached.total == 1


def test_cached_durations_uses_real_clip_lengths(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    deck = _deck()
    synth_mod.synthesize(deck, Config(), audio_dir=tmp_path)  # populate the cache
    cached = synth_mod.cached_durations(deck, Config(), tmp_path, fallback_wpm=60.0)
    assert cached.per_page == [[1.25], []]  # the clip's real length, not the wpm estimate
    assert cached.estimated == []


def test_cached_durations_flags_a_partial_cache(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """One utterance cached, one not: the estimated one must be named."""
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    deck = Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b"],
        narration={
            "a": PageNarration("a", [Segment.speech("Hello there.")]),
            "b": PageNarration("b", [Segment.speech("Goodbye now.")]),
        },
    )
    synth_mod.synthesize(deck, Config(), audio_dir=tmp_path, only_ids={"a"})
    cached = synth_mod.cached_durations(deck, Config(), tmp_path, fallback_wpm=60.0)
    assert cached.per_page == [[1.25], [2.0]]  # real, then guessed
    assert [r.slide_id for r in cached.estimated] == ["b"]
    assert cached.total == 2


def test_a_clip_length_is_saved_when_made_and_reused(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Measuring an MP3 decodes it (~0.1 s each), so every play re-measured the
    whole deck. The engine reports a new clip's exact length; it is saved beside
    the clip in the pool and reused until the file itself changes."""
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    deck = _deck()
    synth_mod.synthesize(deck, Config(), audio_dir=tmp_path)  # FakeEngine: 1.25 s
    measured: list[Path] = []
    monkeypatch.setattr(synth_mod, "get_duration", lambda p: measured.append(p) or 2.5)
    for _ in range(2):
        assert synth_mod.synthesize(deck, Config(), audio_dir=tmp_path)[("a", 0)].duration == 1.25
        assert synth_mod.cached_durations(deck, Config(), tmp_path).per_page[0] == [1.25]
    assert measured == []

    (clip,) = tmp_path.glob("*.wav")
    clip.write_bytes(b"RIFFa longer take")  # changed on disk: measure it (once)
    for _ in range(2):
        assert synth_mod.synthesize(deck, Config(), audio_dir=tmp_path)[("a", 0)].duration == 2.5
    assert measured == [clip]


def _delivery_deck(*lines: Segment) -> Deck:
    return Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a"],
        narration={"a": PageNarration("a", list(lines))},
    )


# A deck as the AICODE course writes it — dictionary IPA and a respelling, a
# `direct:` note, no [tts.inworld] delivery settings — must keep every Inworld clip
# name it had before delivery controls existed (computed from that code; never
# regenerate: a failure here means paid clips would be re-bought).
_PRE_DELIVERY_NAMES = {
    "inworld": [
        "a1718851531e222c.inworld.a38b87e4.mp3",
        "81ca9c4dc40ba464.inworld.a38b87e4.mp3",
        "d5732b2764cd0930.inworld.10d7a799.mp3",
    ],
    "kokoro": [
        "a1718851531e222c.kokoro.8746f0a4.wav",
        "81ca9c4dc40ba464.kokoro.8746f0a4.wav",
        "d5732b2764cd0930.kokoro.f5fd2fc1.wav",
    ],
}


def _aicode_names(backend: str, pronunciation: dict[str, str], **tts: object) -> list[str]:
    deck = _delivery_deck(
        Segment.speech("Ask Claude to run npx."),
        Segment.speech("Now quietly.", direction="slowly, in a low voice"),
        Segment.speech("The interval (0, 1).", pace="slow"),
    )
    config = Config(
        tts=TTSConfig(backend=backend, **tts),  # type: ignore[arg-type]
        pronunciation=pronunciation,
    )
    return [p.name for _ref, p in synth_mod._ref_targets(deck, config, Path("/pool"))]


_AICODE_DICTIONARY = {"Claude": "/klɔːd/", "npx": "N-P-X"}


def test_existing_inworld_clips_keep_their_names() -> None:
    assert _aicode_names("inworld", _AICODE_DICTIONARY) == _PRE_DELIVERY_NAMES["inworld"]


def test_kokoro_says_the_plain_word_for_a_dictionary_ipa_value() -> None:
    """Only the line with a dictionary IPA word re-keys (free): it now sounds as if
    the IPA entry were absent."""
    names = _aicode_names("kokoro", _AICODE_DICTIONARY)
    assert names[1:] == _PRE_DELIVERY_NAMES["kokoro"][1:]
    assert names[0] == _aicode_names("kokoro", {"npx": "N-P-X"})[0]
    assert names[0] != _PRE_DELIVERY_NAMES["kokoro"][0]


def test_each_engine_is_sent_its_own_form_of_a_line() -> None:
    """Inline fixes resolve per engine; a note is sent only when the deck opts in."""
    deck = _delivery_deck(
        Segment.speech("Ask [Mengoli](/menˈɡoːli/) about [0, 1].", direction="warmly")
    )

    def sent(backend: str, **tts: object) -> str:
        config = Config(tts=TTSConfig(backend=backend, **tts))  # type: ignore[arg-type]
        (ref,) = synth_mod.speech_refs(deck, config)
        return ref.text

    assert sent("kokoro") == "Ask Mengoli about [0, 1]."
    assert sent("inworld") == "Ask /menˈɡoːli/ about (0, 1)."
    assert sent("inworld", inworld_send_direction=True) == "[warmly] Ask /menˈɡoːli/ about (0, 1)."
    assert sent("inworld", inworld_model="inworld-tts-1.5-max", inworld_send_direction=True) == (
        "Ask /menˈɡoːli/ about [0, 1]."
    )


def test_an_unreadable_saved_length_file_is_ignored(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: FakeEngine())
    synth_mod.synthesize(_deck(), Config(), audio_dir=tmp_path)
    (tmp_path / "durations.json").write_text("{not json")
    monkeypatch.setattr(synth_mod, "get_duration", lambda p: 3.0)
    assert synth_mod.synthesize(_deck(), Config(), audio_dir=tmp_path)[("a", 0)].duration == 3.0
