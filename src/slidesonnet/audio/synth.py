"""Cache-aware TTS synthesis of a deck's speech segments.

Each speech segment is synthesized into the content-addressed audio cache
(``hashing.audio_path``) so editing one block re-synthesizes only that block.
Per-block ``:pace`` maps to a TTS speed multiplier (which participates in the
cache key, so pace changes invalidate correctly).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from slidesonnet.config import Config
from slidesonnet.hashing import audio_cache_path_or_alt, audio_path
from slidesonnet.models import TTSConfig, resolve_voice
from slidesonnet.narration.format import pace_to_speed
from slidesonnet.narration.model import Deck, Pace
from slidesonnet.tts import create_tts
from slidesonnet.tts.base import TTSEngine
from slidesonnet.video.composer import get_duration

ProgressFn = Callable[[str, int, int], None]


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
    """All speech segments across the deck, in page order, with processed text."""
    refs: list[SpeechRef] = []
    backend = config.tts.backend
    for page_index, slide_id in enumerate(deck.pages):
        block = deck.page_narration(slide_id)
        voice = resolve_voice(block.voice, config.voices, backend)
        for speech_index, seg in enumerate(block.speech_segments):
            refs.append(
                SpeechRef(
                    page_index=page_index,
                    slide_id=slide_id,
                    speech_index=speech_index,
                    text=config.apply_pronunciation(seg.text),
                    voice=voice,
                    pace=block.pace,
                )
            )
    return refs


def _engine_for_pace(tts: TTSConfig, pace: Pace | None, cache: dict[float, TTSEngine]) -> TTSEngine:
    speed = pace_to_speed(pace)
    if speed not in cache:
        cfg = replace(
            tts,
            kokoro_speed=tts.kokoro_speed * speed,
            elevenlabs_speed=tts.elevenlabs_speed * speed,
        )
        cache[speed] = create_tts(cfg)
    return cache[speed]


def synthesize(
    deck: Deck,
    config: Config,
    *,
    audio_dir: Path,
    only_ids: set[str] | None = None,
    progress: ProgressFn | None = None,
) -> dict[tuple[str, int], SynthResult]:
    """Synthesize (or reuse cached) audio for the deck's speech segments.

    Returns a map ``(slide_id, speech_index) -> SynthResult``. ``only_ids``
    restricts synthesis to those slide-ids (others are skipped entirely).
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    refs = [r for r in speech_refs(deck, config) if only_ids is None or r.slide_id in only_ids]
    engines: dict[float, TTSEngine] = {}
    results: dict[tuple[str, int], SynthResult] = {}

    for i, ref in enumerate(refs):
        engine = _engine_for_pace(config.tts, ref.pace, engines)
        target = audio_path(audio_dir, ref.text, engine.name(), engine.cache_key(), ref.voice)
        cached = audio_cache_path_or_alt(target)
        if cached is not None:
            result = SynthResult(path=cached, duration=get_duration(cached), from_cache=True)
        else:
            duration = engine.synthesize(ref.text, target, ref.voice)
            result = SynthResult(path=target, duration=duration, from_cache=False)
        results[(ref.slide_id, ref.speech_index)] = result
        if progress is not None:
            progress(ref.slide_id, i + 1, len(refs))

    return results


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


def cached_durations(
    deck: Deck,
    config: Config,
    audio_dir: Path,
    *,
    fallback_wpm: float = 150.0,
) -> list[list[float]]:
    """Per-page speech durations from the cache, estimating any uncached segment.

    Never synthesizes — used by ``subs`` so subtitle generation costs nothing.
    """
    from slidesonnet.timing import word_count

    engines: dict[float, TTSEngine] = {}
    refs = speech_refs(deck, config)
    by_page: dict[int, dict[int, float]] = {}
    for ref in refs:
        engine = _engine_for_pace(config.tts, ref.pace, engines)
        target = audio_path(audio_dir, ref.text, engine.name(), engine.cache_key(), ref.voice)
        cached = audio_cache_path_or_alt(target)
        if cached is not None:
            dur = get_duration(cached)
        else:
            dur = word_count(ref.text) / fallback_wpm * 60.0
        by_page.setdefault(ref.page_index, {})[ref.speech_index] = dur

    out: list[list[float]] = []
    for page_index, slide_id in enumerate(deck.pages):
        block = deck.page_narration(slide_id)
        page = by_page.get(page_index, {})
        out.append([page.get(i, 0.0) for i in range(len(block.speech_segments))])
    return out


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
