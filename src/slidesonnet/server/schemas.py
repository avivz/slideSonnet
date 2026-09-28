"""Request/response models for ``/api/v1`` — the contract the frontend is typed from.

The TypeScript DTOs are generated from the OpenAPI schema FastAPI derives from
these models, so every field here is part of the frontend contract. Commands
and job requests are *discriminated unions* (a ``type``/``kind`` tag), never
free-form dicts or method names. Nothing here carries a secret or an absolute
filesystem path: decks are addressed by token, files by name.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from slidesonnet.models import Backend
from slidesonnet.narration.model import Segment, Transition
from slidesonnet.narration.transitions import TRANSITION_NAMES

SlideStatus = Literal["error", "warning", "ready", "empty"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(_Model):
    code: str
    message: str


class ErrorResponse(_Model):
    error: ErrorBody


# ---- narration content -----------------------------------------------------------
class TransitionDTO(_Model):
    kind: str = "cut"
    seconds: float = Field(default=0.0, ge=0.0)

    @field_validator("kind")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in TRANSITION_NAMES:
            raise ValueError(f"unknown transition '{v}'")
        return v

    @classmethod
    def of(cls, tr: Transition) -> TransitionDTO:
        return cls(kind=tr.kind, seconds=tr.seconds)

    def to_domain(self) -> Transition:
        return Transition(kind=self.kind, seconds=self.seconds)


class SpeechDTO(_Model):
    kind: Literal["speech"] = "speech"
    text: str = ""
    voice: str | None = None
    pace: Literal["slow", "normal", "fast"] | None = None
    direction: str | None = None


class PauseDTO(_Model):
    kind: Literal["pause"] = "pause"
    seconds: float = Field(ge=0.0)


SegmentDTO = Annotated[SpeechDTO | PauseDTO, Field(discriminator="kind")]


def segment_dto(seg: Segment) -> SpeechDTO | PauseDTO:
    if seg.is_pause:
        return PauseDTO(seconds=seg.seconds)
    return SpeechDTO(text=seg.text, voice=seg.voice, pace=seg.pace, direction=seg.direction)


def segment_domain(dto: SpeechDTO | PauseDTO) -> Segment:
    if isinstance(dto, PauseDTO):
        return Segment.pause(dto.seconds)
    return Segment.speech(dto.text, voice=dto.voice, pace=dto.pace, direction=dto.direction)


class BlockDTO(_Model):
    slide_id: str
    segments: list[SegmentDTO]
    transition_in: TransitionDTO
    transition_out: TransitionDTO


# ---- snapshots -------------------------------------------------------------------
class RevisionsDTO(_Model):
    narration: str
    pdf: str
    config: str
    review: str


class AudioStatusDTO(_Model):
    speech: int
    cached: int


class PageDTO(_Model):
    index: int
    slide_id: str  # "" for a page without a slide id (unmarked)
    status: SlideStatus
    image_url: str | None
    #: The effective transition entering this page (its boundary with the previous).
    incoming: TransitionDTO
    audio: AudioStatusDTO


class DiagnosticDTO(_Model):
    severity: str
    code: str
    message: str
    slide_id: str | None


class EngineDTO(_Model):
    name: str
    paid: bool
    realtime: bool
    installed: bool


class VoicesDTO(_Model):
    #: Named voices → {engine: engine voice}; file voices are deck-relative.
    map: dict[str, dict[str, str]]
    default_voice: str | None
    names: list[str]


class DeckSnapshot(_Model):
    token: str
    name: str
    label: str
    pdf_name: str
    sidecar_name: str
    revisions: RevisionsDTO
    engine: Backend
    default_engine: Backend
    engines: list[EngineDTO]
    pages: list[PageDTO]
    #: Every narration block, keyed by slide id — including ids absent from the PDF.
    narration: dict[str, BlockDTO]
    #: Slide ids with narration but no page in the current PDF (unattached).
    orphans: list[str]
    diagnostics: list[DiagnosticDTO]
    voices: VoicesDTO
    missing_audio: int
    review_active: bool


# ---- library -------------------------------------------------------------------------
class LibraryDeckDTO(_Model):
    token: str
    name: str
    label: str
    group: str
    section: str
    narrated: bool
    url: str


class LibrarySectionDTO(_Model):
    title: str
    decks: list[LibraryDeckDTO]


class LibraryDTO(_Model):
    root: str  # the scan root's folder name (never an absolute path)
    sections: list[LibrarySectionDTO]
    unnarrated: list[LibraryDeckDTO]
    truncated: bool


class DeckStatsDTO(_Model):
    token: str
    slides: int
    narrated: int
    errors: int
    warnings: int


# ---- edits -------------------------------------------------------------------------
class SlideEdit(_Model):
    expected_revision: str
    segments: list[SegmentDTO]
    #: The boundary entering this slide (stored on the previous slide's out).
    transition_in: TransitionDTO = Field(default_factory=TransitionDTO)
    transition_out: TransitionDTO = Field(default_factory=TransitionDTO)


class SaveResponse(_Model):
    changed: bool
    revision: str


class AttachOrphan(_Model):
    type: Literal["attach_orphan"] = "attach_orphan"
    expected_revision: str
    orphan_id: str
    target_id: str


class AppendOrphan(_Model):
    type: Literal["append_orphan"] = "append_orphan"
    expected_revision: str
    orphan_id: str
    target_id: str


class DeleteOrphan(_Model):
    type: Literal["delete_orphan"] = "delete_orphan"
    expected_revision: str
    orphan_id: str


class EditVoices(_Model):
    type: Literal["edit_voices"] = "edit_voices"
    expected_revision: str
    voices: dict[str, dict[str, str]]
    default_voice: str | None = None
    renames: dict[str, str] = Field(default_factory=dict)


DeckCommand = Annotated[
    AttachOrphan | AppendOrphan | DeleteOrphan | EditVoices, Field(discriminator="type")
]


# ---- jobs ----------------------------------------------------------------------------
class ClipRef(_Model):
    slide_id: str
    speech_index: int = Field(ge=0)


class GenerateJob(_Model):
    kind: Literal["generate"] = "generate"
    #: Specific clips, or ``None`` for every clip without audio.
    targets: list[ClipRef] | None = None
    force: bool = False
    engine: Backend | None = None
    #: Explicit approval to spend credits on a paid engine (never implied).
    allow_paid: bool = False


class PreviewJob(_Model):
    kind: Literal["preview"] = "preview"
    #: One slide, or ``None`` for the whole deck.
    slide_id: str | None = None
    engine: Backend | None = None
    allow_paid: bool = False
    #: Deck preview only: start playback at this slide's cue.
    start_slide: str | None = None
    single_slide_transitions: bool = False


class ExportJob(_Model):
    kind: Literal["export"] = "export"
    draft: bool = False
    engine: Backend | None = None
    allow_paid: bool = False


class RenderPagesJob(_Model):
    kind: Literal["render_pages"] = "render_pages"


JobRequest = Annotated[
    GenerateJob | PreviewJob | ExportJob | RenderPagesJob, Field(discriminator="kind")
]


class ProgressDTO(_Model):
    phase: str
    done: int
    total: int
    label: str


class JobDTO(_Model):
    id: str
    kind: Literal["generate", "preview", "export", "render_pages"]
    deck: str
    status: Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]
    inputs: dict[str, Any]
    progress: ProgressDTO
    result: dict[str, Any] | None
    error: ErrorBody | None
    created_at: float
    started_at: float | None
    finished_at: float | None


class SessionDTO(_Model):
    #: Sent back as ``X-SlideSonnet-Session`` on every mutating request.
    token: str
