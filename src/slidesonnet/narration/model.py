"""Narration data model: Segment / PageNarration / Deck.

A narration sidecar is a flat list of per-slide blocks. Each block is a
:class:`PageNarration` keyed by a stable slide-id, holding an ordered list of
:class:`Segment`s (spoken text or explicit pauses) plus optional voice/pace
directives. The :class:`Deck` ties a PDF (its page-ordered slide-ids) to the
parsed narration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SegmentKind = Literal["speech", "pause"]
Pace = Literal["slow", "normal", "fast"]


@dataclass(frozen=True)
class Segment:
    """One narration element: either spoken *text* or a *pause* of *seconds*."""

    kind: SegmentKind
    text: str = ""
    seconds: float = 0.0

    @classmethod
    def speech(cls, text: str) -> Segment:
        return cls(kind="speech", text=text)

    @classmethod
    def pause(cls, seconds: float) -> Segment:
        if seconds < 0:
            raise ValueError(f"pause seconds must be non-negative, got {seconds}")
        return cls(kind="pause", seconds=seconds)

    @property
    def is_speech(self) -> bool:
        return self.kind == "speech"

    @property
    def is_pause(self) -> bool:
        return self.kind == "pause"


@dataclass
class PageNarration:
    """Narration for a single slide-id."""

    slide_id: str
    segments: list[Segment] = field(default_factory=list)
    voice: str | None = None
    pace: Pace | None = None

    @property
    def speech_segments(self) -> list[Segment]:
        return [s for s in self.segments if s.is_speech]

    @property
    def speech_text(self) -> str:
        """All spoken text joined with spaces (no pause markers)."""
        return " ".join(s.text for s in self.speech_segments).strip()

    @property
    def has_speech(self) -> bool:
        return any(s.is_speech and s.text.strip() for s in self.segments)

    @property
    def is_silent(self) -> bool:
        """True when the block holds the slide with no spoken words (pauses only / empty)."""
        return not self.has_speech

    @property
    def total_pause_seconds(self) -> float:
        return sum(s.seconds for s in self.segments if s.is_pause)


@dataclass
class Deck:
    """A PDF deck joined to its narration sidecar."""

    pdf_path: Path
    sidecar_path: Path
    pages: list[str] = field(default_factory=list)  # slide-ids in PDF page order
    narration: dict[str, PageNarration] = field(default_factory=dict)

    def page_narration(self, slide_id: str) -> PageNarration:
        """Return the narration for *slide_id*, or an empty silent block if none."""
        return self.narration.get(slide_id, PageNarration(slide_id=slide_id))

    def restricted_to(self, slide_id: str) -> Deck:
        """A one-page view of this deck (narration shared), for single-slide rendering."""
        return Deck(
            pdf_path=self.pdf_path,
            sidecar_path=self.sidecar_path,
            pages=[slide_id],
            narration=self.narration,
        )

    @property
    def ordered_narration(self) -> list[PageNarration]:
        """Narration blocks in PDF page order (empty blocks for un-narrated pages)."""
        return [self.page_narration(sid) for sid in self.pages]
