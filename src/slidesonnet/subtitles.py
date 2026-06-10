"""Subtitle formatting: SRT + WebVTT writers and text splitting.

Cue *timing* is computed by the render layer from the page timeline; this module
only turns :class:`SubtitleEntry` objects into SRT/VTT text and splits long
narration into subtitle-sized chunks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENTENCE_RE = re.compile(r"(?<=[.!?])(?:\s+|$)")
_CLAUSE_RE = re.compile(r"(?<=[,;:—–])\s+")


@dataclass
class SubtitleEntry:
    """One subtitle cue."""

    index: int
    start: float  # seconds
    end: float  # seconds
    text: str


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def split_text(text: str, max_chars: int = 80) -> list[str]:
    """Split narration text into subtitle-sized chunks (sentence/clause/word)."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return _split_long_sentence(text, max_chars)

    chunks: list[str] = []
    current = sentences[0]
    for sentence in sentences[1:]:
        combined = current + " " + sentence
        if len(combined) <= max_chars:
            current = combined
        else:
            chunks.extend(_split_long_sentence(current, max_chars))
            current = sentence
    chunks.extend(_split_long_sentence(current, max_chars))
    return chunks


def _split_long_sentence(text: str, max_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

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
        if all(len(c) <= max_chars for c in chunks):
            return chunks

    return _split_at_midpoint(text, max_chars)


def _split_at_midpoint(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    mid = len(text) // 2
    best = -1
    for offset in range(mid):
        if mid + offset < len(text) and text[mid + offset] == " ":
            best = mid + offset
            break
        if mid - offset >= 0 and text[mid - offset] == " ":
            best = mid - offset
            break
    if best == -1:
        return [text]
    left = text[:best].strip()
    right = text[best:].strip()
    result: list[str] = []
    if left:
        result.extend(_split_at_midpoint(left, max_chars))
    if right:
        result.extend(_split_at_midpoint(right, max_chars))
    return result


def _format_timestamp(seconds: float, *, sep: str) -> str:
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{millis:03d}"


def format_srt(entries: list[SubtitleEntry]) -> str:
    """Render entries as an SRT document."""
    blocks: list[str] = []
    for i, entry in enumerate(entries, start=1):
        start = _format_timestamp(entry.start, sep=",")
        end = _format_timestamp(entry.end, sep=",")
        blocks.append(f"{i}\n{start} --> {end}\n{entry.text}")
    return "\n\n".join(blocks) + "\n" if blocks else ""


def format_vtt(entries: list[SubtitleEntry]) -> str:
    """Render entries as a WebVTT document."""
    blocks: list[str] = ["WEBVTT"]
    for entry in entries:
        start = _format_timestamp(entry.start, sep=".")
        end = _format_timestamp(entry.end, sep=".")
        blocks.append(f"{start} --> {end}\n{entry.text}")
    return "\n\n".join(blocks) + "\n"
