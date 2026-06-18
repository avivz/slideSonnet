"""Narration data model: Segment / Transition / PageNarration / Deck.

A narration sidecar is a flat list of per-slide blocks. Each block is a
:class:`PageNarration` keyed by a stable slide-id, holding an ordered list of
:class:`Segment`s (attributed spoken utterances or explicit pauses) plus the
transitions into and out of the slide. The :class:`Deck` ties a PDF (its
page-ordered slide-ids) to the parsed narration.

Per-utterance attributes (voice, pace, director's note) live on the speech
segment itself, so one slide can mix voices and paces — each speech segment is
its own synthesis call. ``direction`` is stored and serialized for forward
compatibility; the current local engine ignores it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from slidesonnet.models import VoiceConfig
from slidesonnet.narration.transitions import TRANSITION_NAMES

SegmentKind = Literal["speech", "pause"]
Pace = Literal["slow", "normal", "fast"]
# A stored transition name from the curated gallery (``narration.transitions``):
# ``cut`` (the default), the ``crossfade`` legacy alias, or an xfade name such
# as ``wipeleft`` / ``slideup`` / ``circleopen``.
TransitionKind = str


@dataclass(frozen=True)
class Transition:
    """How a slide enters or leaves: a hard *cut* or a timed xfade animation.

    ``kind`` is a name from the curated gallery (see
    :mod:`slidesonnet.narration.transitions`); ``seconds`` is the animation
    duration, ignored for a cut.
    """

    kind: TransitionKind = "cut"
    seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in TRANSITION_NAMES:
            raise ValueError(f"unknown transition '{self.kind}'")
        if self.seconds < 0:
            raise ValueError(f"transition seconds must be non-negative, got {self.seconds}")

    @property
    def is_animated(self) -> bool:
        """True when this is a real transition (anything but a hard cut)."""
        return self.kind != "cut"


@dataclass(frozen=True)
class Segment:
    """One narration element: a spoken utterance or a *pause* of *seconds*.

    Speech segments carry their own ``voice`` (backend voice name, or None for
    the configured default), ``pace``, and free-text ``direction``.
    """

    kind: SegmentKind
    text: str = ""
    seconds: float = 0.0
    voice: str | None = None
    pace: Pace | None = None
    direction: str | None = None

    @classmethod
    def speech(
        cls,
        text: str,
        *,
        voice: str | None = None,
        pace: Pace | None = None,
        direction: str | None = None,
    ) -> Segment:
        return cls(kind="speech", text=text, voice=voice, pace=pace, direction=direction)

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
    """Narration for a single slide-id: attributed segments plus transitions.

    The last four fields are round-trip bookkeeping set by the parser, so a
    save can re-emit a block exactly as the author wrote it (comments, hand
    wrapping) when its content didn't change: ``source`` is the block's raw
    text (header line included), ``canon`` its canonical serialization at
    parse time (the change detector), ``lead`` the comment/blank lines above
    the header (``None`` marks a block never read from a file), and ``tail``
    any trailing end-of-file comments owned by the last block. ``lead`` and
    ``tail`` are emitted even when the block's body is rewritten.
    """

    slide_id: str
    segments: list[Segment] = field(default_factory=list)
    transition_in: Transition = field(default_factory=Transition)
    transition_out: Transition = field(default_factory=Transition)
    source: str | None = field(default=None, compare=False, repr=False)
    canon: str | None = field(default=None, compare=False, repr=False)
    lead: str | None = field(default=None, compare=False, repr=False)
    tail: str | None = field(default=None, compare=False, repr=False)

    def rekeyed(self, slide_id: str) -> PageNarration:
        """Copy of this block under a new slide-id (orphan re-attachment).

        Comments (``lead``/``tail``) travel with the block; the raw ``source``
        and ``canon`` are deliberately dropped — the content now lives under a
        new header, so it must re-serialize canonically.
        """
        return PageNarration(
            slide_id=slide_id,
            segments=list(self.segments),
            transition_in=self.transition_in,
            transition_out=self.transition_out,
            lead=self.lead,
            tail=self.tail,
        )

    def with_content(
        self,
        segments: list[Segment],
        *,
        transition_in: Transition | None = None,
        transition_out: Transition | None = None,
    ) -> PageNarration:
        """Copy with new segments/transitions, keeping all round-trip bookkeeping.

        The serializer re-emits ``source`` verbatim only while ``canon`` still
        matches, so an actual content change rewrites the block canonically.
        """
        return PageNarration(
            slide_id=self.slide_id,
            segments=list(segments),
            transition_in=transition_in or self.transition_in,
            transition_out=transition_out or self.transition_out,
            source=self.source,
            canon=self.canon,
            lead=self.lead,
            tail=self.tail,
        )

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

    @property
    def has_nondefault_transitions(self) -> bool:
        """True if either transition differs from a plain cut."""
        return self.transition_in.is_animated or self.transition_out.is_animated

    @property
    def is_empty(self) -> bool:
        """True for a placeholder block: no segments and plain-cut transitions.

        Such a block carries no information, so it is never serialized — writing
        a bare ``@id`` header would otherwise register the page as "narrated"
        (an empty block) and suppress its ``missing-narration`` warning.
        """
        return (
            not self.segments
            and self.transition_in.kind == "cut"
            and self.transition_out.kind == "cut"
        )


@dataclass
class Deck:
    """A PDF deck joined to its narration sidecar.

    ``voices`` and ``default_voice`` are the deck-level *portable voice layer*
    read from the sidecar preamble: internal voice names mapped to per-engine
    voices, and the name an utterance with no explicit ``voice:`` falls back to.
    They travel with the deck so the same script narrates under any engine.
    ``preamble_source`` is the raw preamble text kept for a byte-stable save.
    """

    pdf_path: Path
    sidecar_path: Path
    pages: list[str] = field(default_factory=list)  # slide-ids in PDF page order
    narration: dict[str, PageNarration] = field(default_factory=dict)
    voices: dict[str, VoiceConfig] = field(default_factory=dict)
    default_voice: str | None = None
    preamble_source: str | None = field(default=None, compare=False, repr=False)

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
            voices=self.voices,
            default_voice=self.default_voice,
            preamble_source=self.preamble_source,
        )

    @property
    def ordered_narration(self) -> list[PageNarration]:
        """Narration blocks in PDF page order (empty blocks for un-narrated pages)."""
        return [self.page_narration(sid) for sid in self.pages]
