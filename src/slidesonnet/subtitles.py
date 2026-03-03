"""SRT subtitle generation from narrated slide presentations."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from slidesonnet.actions import get_parser_and_extractor
from slidesonnet.hashing import audio_path as _audio_path
from slidesonnet.hashing import concat_filename as _concat_filename
from slidesonnet.models import (
    ModuleType,
    PlaylistEntry,
    ProjectConfig,
    resolve_voice,
)
from slidesonnet.tts.base import TTSEngine
from slidesonnet.tts.pronunciation import apply_pronunciation
from slidesonnet.video.composer import get_duration

logger = logging.getLogger(__name__)

# Sentence-ending punctuation followed by space or end-of-string
_SENTENCE_RE = re.compile(r"(?<=[.!?])(?:\s+|$)")

# Clause boundary punctuation
_CLAUSE_RE = re.compile(r"(?<=[,;:\u2014\u2013])\s+")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences at .!? boundaries."""
    parts = _SENTENCE_RE.split(text.strip())
    return [s for s in parts if s.strip()]


def split_text(text: str, max_chars: int = 80) -> list[str]:
    """Split narration text into subtitle-sized chunks.

    Algorithm (in priority order):
    1. Split at sentence boundaries (.!? followed by space/end)
    2. Group consecutive sentences into chunks <= max_chars
    3. If single sentence > max_chars, split at clause boundaries (, ; : -- -)
    4. Last resort: split at word boundary nearest midpoint
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return _split_long_sentence(text, max_chars)

    # Group sentences into chunks <= max_chars
    chunks: list[str] = []
    current = sentences[0]
    for sentence in sentences[1:]:
        combined = current + " " + sentence
        if len(combined) <= max_chars:
            current = combined
        else:
            # Flush current chunk (may itself be too long)
            chunks.extend(_split_long_sentence(current, max_chars))
            current = sentence
    chunks.extend(_split_long_sentence(current, max_chars))
    return chunks


def _split_long_sentence(text: str, max_chars: int) -> list[str]:
    """Split a single sentence that exceeds max_chars."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Try clause boundaries
    parts = _CLAUSE_RE.split(text)
    if len(parts) > 1:
        chunks: list[str] = []
        current = parts[0]
        for part in parts[1:]:
            combined = current + " " + part
            if len(combined) <= max_chars:
                current = combined
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = part
        if current.strip():
            chunks.append(current.strip())
        # Check if all chunks fit — if not, fall through to word split
        if all(len(c) <= max_chars for c in chunks):
            return chunks

    # Last resort: split at word boundary nearest midpoint
    return _split_at_midpoint(text, max_chars)


def _split_at_midpoint(text: str, max_chars: int) -> list[str]:
    """Split text at the word boundary nearest to the midpoint, recursively."""
    if len(text) <= max_chars:
        return [text]

    mid = len(text) // 2
    # Search outward from midpoint for a space
    best = -1
    for offset in range(mid):
        if mid + offset < len(text) and text[mid + offset] == " ":
            best = mid + offset
            break
        if mid - offset >= 0 and text[mid - offset] == " ":
            best = mid - offset
            break
    if best == -1:
        # No space found — return as-is (shouldn't happen with real text)
        return [text]

    left = text[:best].strip()
    right = text[best:].strip()
    result: list[str] = []
    if left:
        result.extend(_split_at_midpoint(left, max_chars))
    if right:
        result.extend(_split_at_midpoint(right, max_chars))
    return result


@dataclass
class SubtitleEntry:
    """One SRT subtitle cue."""

    index: int
    start: float  # seconds
    end: float  # seconds
    text: str


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_srt(entries: list[SubtitleEntry]) -> str:
    """Format subtitle entries as an SRT string."""
    blocks: list[str] = []
    for entry in entries:
        blocks.append(
            f"{entry.index}\n"
            f"{_format_srt_time(entry.start)} --> {_format_srt_time(entry.end)}\n"
            f"{entry.text}"
        )
    return "\n\n".join(blocks) + "\n" if blocks else ""


def _find_audio_path(
    audio_cache_dir: Path,
    slide: object,
    tts: TTSEngine,
) -> Path | None:
    """Locate the audio file for a narrated slide, checking alternate extensions."""
    from slidesonnet.hashing import _BACKEND_EXTENSIONS
    from slidesonnet.models import SlideNarration

    assert isinstance(slide, SlideNarration)
    parts = slide.narration_parts_processed

    if len(parts) > 1:
        part_paths: list[Path] = []
        for part_text in parts:
            p = _audio_path(audio_cache_dir, part_text, tts.name(), tts.cache_key(), slide.voice)
            part_paths.append(p)
        target = audio_cache_dir / _concat_filename(part_paths)
    else:
        target = _audio_path(
            audio_cache_dir, slide.narration_processed, tts.name(), tts.cache_key(), slide.voice
        )

    # Check target and alternate extensions
    if target.exists() and target.stat().st_size > 0:
        return target
    suffix = target.suffix
    for ext in _BACKEND_EXTENSIONS.values():
        if ext != suffix:
            alt = target.with_suffix(ext)
            if alt.exists() and alt.stat().st_size > 0:
                return alt
    return None


def generate_subtitles(
    entries: list[PlaylistEntry],
    config: ProjectConfig,
    tts: TTSEngine,
    build_dir: Path,
    playlist_dir: Path,
    max_chars: int = 80,
) -> list[SubtitleEntry]:
    """Generate subtitle entries from a parsed playlist.

    Iterates all entries, computes segment durations and cumulative offsets,
    and creates subtitle cues for narrated slides using narration_raw text.
    """
    audio_cache_dir = build_dir / "audio"
    crossfade = config.video.crossfade
    pre_silence = config.video.pre_silence
    pad_seconds = config.video.pad_seconds
    silence_duration = config.video.silence_duration

    subtitles: list[SubtitleEntry] = []
    cumulative_offset = 0.0
    segment_index = 0  # counts non-skip segments for crossfade logic
    subtitle_index = 1

    for entry in entries:
        if entry.module_type == ModuleType.VIDEO:
            # Video passthrough: advance offset by video duration
            source_path = playlist_dir / entry.path
            try:
                vid_duration = get_duration(source_path)
            except RuntimeError:
                logger.warning("Cannot probe video duration: %s", entry.path)
                continue
            if segment_index > 0:
                cumulative_offset -= crossfade
            cumulative_offset += vid_duration
            segment_index += 1
            continue

        source_path = playlist_dir / entry.path
        module_dir = build_dir / entry.path.parent / entry.path.stem
        slides_dir = module_dir / "slides"

        parser_cls, _ = get_parser_and_extractor(entry.module_type)
        parser = parser_cls()
        slides = parser.parse(source_path, slides_dir)

        # Apply pronunciation and resolve voices (same as dry_run / tasks)
        pron = config.pronunciation_for(config.tts.backend)
        for slide in slides:
            if slide.has_narration:
                slide.narration_processed = apply_pronunciation(slide.narration_raw, pron)
                slide.narration_parts_processed = [
                    apply_pronunciation(part, pron) for part in slide.narration_parts
                ]
                if slide.voice:
                    resolved = resolve_voice(slide.voice, config.voices, config.tts.backend)
                    if resolved:
                        slide.voice = resolved
                    else:
                        slide.voice = None

        for slide in slides:
            if slide.is_skip:
                continue

            if segment_index > 0:
                cumulative_offset -= crossfade

            if slide.has_narration:
                # Find audio and get its duration
                audio_path = _find_audio_path(audio_cache_dir, slide, tts)
                if audio_path is None:
                    logger.warning(
                        "Audio not found for slide %d of %s — skipping subtitle",
                        slide.index,
                        entry.path,
                    )
                    # Still advance offset with estimated duration
                    cumulative_offset += pre_silence + pad_seconds
                    segment_index += 1
                    continue

                try:
                    audio_duration = get_duration(audio_path)
                except RuntimeError:
                    logger.warning(
                        "Cannot probe audio duration for slide %d of %s",
                        slide.index,
                        entry.path,
                    )
                    cumulative_offset += pre_silence + pad_seconds
                    segment_index += 1
                    continue

                segment_duration = pre_silence + audio_duration + pad_seconds

                # Create subtitle entries from narration_raw text
                sub_start = cumulative_offset + pre_silence
                sub_end = cumulative_offset + pre_silence + audio_duration
                chunks = split_text(slide.narration_raw, max_chars)

                if len(chunks) <= 1:
                    # Single subtitle for this slide
                    subtitles.append(
                        SubtitleEntry(
                            index=subtitle_index,
                            start=sub_start,
                            end=sub_end,
                            text=chunks[0] if chunks else slide.narration_raw,
                        )
                    )
                    subtitle_index += 1
                else:
                    # Distribute duration proportionally by character count
                    total_chars = sum(len(c) for c in chunks)
                    chunk_start = sub_start
                    for chunk in chunks:
                        proportion = len(chunk) / total_chars if total_chars > 0 else 1.0
                        chunk_duration = audio_duration * proportion
                        chunk_end = chunk_start + chunk_duration
                        subtitles.append(
                            SubtitleEntry(
                                index=subtitle_index,
                                start=chunk_start,
                                end=chunk_end,
                                text=chunk,
                            )
                        )
                        subtitle_index += 1
                        chunk_start = chunk_end

                cumulative_offset += segment_duration
            else:
                # Silent or unannotated slide — advance offset, no subtitle
                duration = (
                    slide.silence_override
                    if slide.silence_override is not None
                    else silence_duration
                )
                cumulative_offset += duration

            segment_index += 1

    return subtitles
