"""Cache-aware TTS synthesis of a deck's speech segments.

Each speech segment is synthesized into the content-addressed audio cache
(``hashing.audio_path``) so editing one block re-synthesizes only that block.
Per-block ``:pace`` maps to a TTS speed multiplier (which participates in the
cache key, so pace changes invalidate correctly).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from slidesonnet.config import Config
from slidesonnet.hashing import audio_cache_path_or_alt, audio_path
from slidesonnet.models import ProgressFn, TTSConfig, resolve_voice
from slidesonnet.narration.format import pace_to_speed
from slidesonnet.narration.model import Deck, Pace
from slidesonnet.tts import create_tts
from slidesonnet.tts.base import TTSEngine
from slidesonnet.video.composer import get_duration

__all__ = [
    "CachedDurations",
    "ProgressFn",
    "SpeechRef",
    "SynthResult",
]  # ProgressFn re-exported for callers


@dataclass(frozen=True)
class SpeechRef:
    """A speech segment to synthesize, with processed text and resolved voice."""

    page_index: int  # index into deck.pages
    slide_id: str
    speech_index: int  # index among the block's speech segments
    text: str  # pronunciation-applied
    voice: str | None  # backend voice id (already resolved), or None
    pace: Pace | None


@dataclass(frozen=True)
class SynthResult:
    path: Path
    duration: float
    from_cache: bool


def speech_refs(deck: Deck, config: Config) -> list[SpeechRef]:
    """All speech segments across the deck, in page order, with processed text.

    Voice and pace are read per utterance, so a single slide may mix voices and
    paces — each becomes its own synthesis call (and its own cache entry).
    """
    refs: list[SpeechRef] = []
    backend = config.tts.backend
    # The deck's portable voice layer (sidecar preamble) wins over the shared
    # toml library, and supplies the deck-wide default for an unset voice.
    voices = {**config.voices, **deck.voices}
    default_voice = deck.default_voice
    for page_index, slide_id in enumerate(deck.pages):
        block = deck.page_narration(slide_id)
        for speech_index, seg in enumerate(block.speech_segments):
            refs.append(
                SpeechRef(
                    page_index=page_index,
                    slide_id=slide_id,
                    speech_index=speech_index,
                    text=config.apply_pronunciation(seg.text),
                    voice=resolve_voice(seg.voice or default_voice, voices, backend),
                    pace=seg.pace,
                )
            )
    return refs


def engine_for_pace(tts: TTSConfig, pace: Pace | None, cache: dict[float, TTSEngine]) -> TTSEngine:
    speed = pace_to_speed(pace)
    if speed not in cache:
        cfg = replace(
            tts,
            kokoro_speed=tts.kokoro_speed * speed,
            inworld_speed=tts.inworld_speed * speed,
        )
        cache[speed] = create_tts(cfg)
    return cache[speed]


def synthesize(
    deck: Deck,
    config: Config,
    *,
    audio_dir: Path,
    only_ids: set[str] | None = None,
    only_segments: set[tuple[str, int]] | None = None,
    force: bool = False,
    progress: ProgressFn | None = None,
) -> dict[tuple[str, int], SynthResult]:
    """Synthesize (or reuse cached) audio for the deck's speech segments.

    Returns a map ``(slide_id, speech_index) -> SynthResult``. ``only_ids``
    restricts synthesis to those slide-ids (others are skipped entirely);
    ``only_segments`` narrows further to specific ``(slide_id, speech_index)``
    pairs (the editor's per-utterance generate). ``force`` re-synthesizes every
    targeted segment, overwriting cached clips (the editor's "regenerate"
    action — useful for a fresh take from a non-deterministic engine, or to
    refresh a stale cache entry).
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    refs = [
        r
        for r in speech_refs(deck, config)
        if (only_ids is None or r.slide_id in only_ids)
        and (only_segments is None or (r.slide_id, r.speech_index) in only_segments)
    ]
    engines: dict[float, TTSEngine] = {}
    results: dict[tuple[str, int], SynthResult] = {}

    for i, ref in enumerate(refs):
        engine = engine_for_pace(config.tts, ref.pace, engines)
        target = audio_path(audio_dir, ref.text, engine.name(), engine.cache_key(), ref.voice)
        cached = None if force else audio_cache_path_or_alt(target)
        if cached is not None:
            result = SynthResult(path=cached, duration=get_duration(cached), from_cache=True)
        else:
            duration = engine.synthesize(ref.text, target, ref.voice)
            result = SynthResult(path=target, duration=duration, from_cache=False)
        results[(ref.slide_id, ref.speech_index)] = result
        if progress is not None:
            progress(ref.slide_id, i + 1, len(refs))

    return results


def _ref_targets(deck: Deck, config: Config, audio_dir: Path) -> list[tuple[SpeechRef, Path]]:
    """Every speech segment paired with its content-addressed cache path."""
    engines: dict[float, TTSEngine] = {}
    out: list[tuple[SpeechRef, Path]] = []
    for ref in speech_refs(deck, config):
        engine = engine_for_pace(config.tts, ref.pace, engines)
        out.append(
            (ref, audio_path(audio_dir, ref.text, engine.name(), engine.cache_key(), ref.voice))
        )
    return out


def ref_cache_status(deck: Deck, config: Config, audio_dir: Path) -> list[tuple[SpeechRef, bool]]:
    """Every speech segment paired with whether its cached audio exists.

    One deck-wide scan callers can derive counts/flags/id-sets from, instead
    of re-walking every segment (with stat calls) per question.
    """
    return [
        (ref, audio_cache_path_or_alt(target) is not None)
        for ref, target in _ref_targets(deck, config, audio_dir)
    ]


def uncached_targets(
    deck: Deck,
    config: Config,
    audio_dir: Path,
    *,
    only_ids: set[str] | None = None,
) -> list[Path]:
    """Cache paths of speech segments that have no cached audio yet.

    Never synthesizes — lets callers count (or pre-create) what a synthesis
    run would actually generate, e.g. to warn before spending API credits.
    """
    return [
        target
        for ref, target in _ref_targets(deck, config, audio_dir)
        if (only_ids is None or ref.slide_id in only_ids)
        and audio_cache_path_or_alt(target) is None
    ]


def cached_speech_flags(deck: Deck, config: Config, audio_dir: Path, slide_id: str) -> list[bool]:
    """Aligned to *slide_id*'s speech segments: True where cached audio exists.

    Never synthesizes — drives the editor's per-utterance generated indicator.
    """
    return [
        audio_cache_path_or_alt(target) is not None
        for ref, target in _ref_targets(deck, config, audio_dir)
        if ref.slide_id == slide_id
    ]


def ungenerated_ids(deck: Deck, config: Config, audio_dir: Path) -> set[str]:
    """Slide-ids that still have at least one speech segment without cached audio."""
    return {
        ref.slide_id
        for ref, target in _ref_targets(deck, config, audio_dir)
        if audio_cache_path_or_alt(target) is None
    }


def page_speech_durations(
    deck: Deck,
    results: dict[tuple[str, int], SynthResult],
) -> list[list[float]]:
    """Per-page lists of speech-segment durations, aligned to ``deck.pages``.

    A page whose clips are missing from *results* yields an empty list (its
    speech, if any, hasn't been synthesized).
    """
    out: list[list[float]] = []
    for slide_id in deck.pages:
        block = deck.page_narration(slide_id)
        durations: list[float] = []
        for speech_index in range(len(block.speech_segments)):
            res = results.get((slide_id, speech_index))
            durations.append(res.duration if res else 0.0)
        out.append(durations)
    return out


@dataclass(frozen=True)
class CachedDurations:
    """Speech durations read from the cache, plus which ones had to be guessed.

    ``per_page`` aligns to ``deck.pages`` (each entry aligned to that page's
    speech segments). ``estimated`` holds the utterances with no cached audio —
    their duration is a words/WPM guess, not the real timeline. Callers that
    promised ``tts`` timing must not pass those off as exact: a guess is ~2 %
    off per utterance, and the error accumulates into visible subtitle drift.
    """

    per_page: list[list[float]]
    estimated: list[SpeechRef]
    total: int

    @property
    def all_estimated(self) -> bool:
        """True when the deck has speech and *none* of it was found in the cache."""
        return self.total > 0 and len(self.estimated) == self.total


def cached_durations(
    deck: Deck,
    config: Config,
    audio_dir: Path,
    *,
    fallback_wpm: float = 150.0,
) -> CachedDurations:
    """Per-page speech durations from the cache, estimating any uncached segment.

    Never synthesizes — used by ``subs`` so subtitle generation costs nothing.
    The estimated utterances are reported alongside the durations rather than
    blended in silently, because a cache lookup misses for mundane reasons (the
    audio was rendered by a different engine, or never generated) and the
    resulting timeline is fiction.
    """
    from slidesonnet.timing import estimate_speech_seconds

    engines: dict[float, TTSEngine] = {}
    refs = speech_refs(deck, config)
    by_page: dict[int, dict[int, float]] = {}
    estimated: list[SpeechRef] = []
    for ref in refs:
        engine = engine_for_pace(config.tts, ref.pace, engines)
        target = audio_path(audio_dir, ref.text, engine.name(), engine.cache_key(), ref.voice)
        cached = audio_cache_path_or_alt(target)
        if cached is not None:
            dur = get_duration(cached)
        else:
            dur = estimate_speech_seconds(ref.text, fallback_wpm)
            estimated.append(ref)
        by_page.setdefault(ref.page_index, {})[ref.speech_index] = dur

    out: list[list[float]] = []
    for page_index, slide_id in enumerate(deck.pages):
        block = deck.page_narration(slide_id)
        page = by_page.get(page_index, {})
        out.append([page.get(i, 0.0) for i in range(len(block.speech_segments))])
    return CachedDurations(per_page=out, estimated=estimated, total=len(refs))


def page_speech_clips(
    deck: Deck,
    results: dict[tuple[str, int], SynthResult],
) -> list[list[Path]]:
    """Per-page lists of speech clip paths, aligned to ``deck.pages``."""
    out: list[list[Path]] = []
    for slide_id in deck.pages:
        block = deck.page_narration(slide_id)
        clips: list[Path] = []
        for speech_index in range(len(block.speech_segments)):
            res = results.get((slide_id, speech_index))
            if res is not None:
                clips.append(res.path)
        out.append(clips)
    return out
