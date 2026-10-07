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
from slidesonnet.narration.format import PREAMBLE_KEY_RE, PREAMBLE_VALUE_RE
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
#: A duration in seconds: finite (no NaN/Infinity) and non-negative.
Seconds = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]


def _single_line(v: str | None) -> str | None:
    """Refuse a line break: the sidecar holds each voice/direction on one line."""
    if v is not None and ("\n" in v or "\r" in v):
        raise ValueError("must be a single line")
    return v


def _voice_name(v: str) -> str:
    if not PREAMBLE_KEY_RE.fullmatch(v):
        raise ValueError(f"'{v}' must start with a letter and use only letters, digits, '-' or '_'")
    return v


def _voice_value(v: str) -> str:
    v = v.strip()
    if not PREAMBLE_VALUE_RE.fullmatch(v):
        raise ValueError(f"'{v}' must be one non-blank line with no '#' after a space")
    return v


class TransitionDTO(_Model):
    kind: str = "cut"
    seconds: Seconds = 0.0

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

    _one_line = field_validator("voice", "direction")(_single_line)


class PauseDTO(_Model):
    kind: Literal["pause"] = "pause"
    seconds: Seconds


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


class ClipDTO(_Model):
    """One utterance's audio under the snapshot's engine."""

    cached: bool
    seconds: float | None = None  # from the WAV header, when readable
    bytes: int | None = None


class PageDTO(_Model):
    index: int
    slide_id: str  # "" for a page without a slide id (unmarked)
    status: SlideStatus
    image_url: str | None
    #: The effective transition entering this page (its boundary with the previous).
    incoming: TransitionDTO
    audio: AudioStatusDTO
    #: Per speech segment of this slide, in order.
    clips: list[ClipDTO]


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
    #: What each name resolves to under the snapshot's engine (None = unmapped).
    resolved: dict[str, str | None]


class SilenceDefaultsDTO(_Model):
    """The deck's hold before and after a slide's speech when none is written."""

    start: float
    end: float


class DeckSnapshot(_Model):
    token: str
    name: str
    label: str
    revisions: RevisionsDTO
    engine: Backend
    engines: list[EngineDTO]
    pages: list[PageDTO]
    #: Every narration block, keyed by slide id — including ids absent from the PDF.
    narration: dict[str, BlockDTO]
    #: Slide ids with narration but no page in the current PDF (unattached).
    orphans: list[str]
    #: Unattached ids that are a repeated ``@id``'s later block (tray id → the id repeated).
    duplicates: dict[str, str]
    diagnostics: list[DiagnosticDTO]
    voices: VoicesDTO
    missing_audio: int
    silence: SilenceDefaultsDTO
    #: False while the snapshot's engine still has a heavy model to load.
    engine_warm: bool
    #: Other decks in library order, for stepping (Alt+←/→).
    neighbours: dict[str, str | None]
    #: Page width ÷ height (the stage and filmstrip keep the slide's shape).
    aspect: float


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
    #: Names of the folders above the root, outermost first ("~" for home); the
    #: last is one folder up. Names only, so no absolute path goes on the wire.
    parents: list[str]
    sections: list[LibrarySectionDTO]
    unnarrated: list[LibraryDeckDTO]
    truncated: bool


class LibraryRootRequest(_Model):
    #: The folder to list decks from, relative to the current one (``..`` is up).
    path: str = Field(min_length=1)


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

    # Everything here is written to the sidecar's voice preamble, so it must be
    # something that preamble reads back as itself.
    @field_validator("voices")
    @classmethod
    def _map(cls, v: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        return {
            _voice_name(name): {_voice_name(eng): _voice_value(vid) for eng, vid in m.items()}
            for name, m in v.items()
        }

    @field_validator("default_voice")
    @classmethod
    def _default(cls, v: str | None) -> str | None:
        return None if v is None or not v.strip() else _voice_value(v)

    @field_validator("renames")
    @classmethod
    def _renames(cls, v: dict[str, str]) -> dict[str, str]:
        return {old: _voice_name(new) for old, new in v.items()}


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
    #: The quick export: 720p, cuts, one encoding pass; writes ``<name>.fast.mp4``.
    fast: bool = False
    engine: Backend | None = None
    allow_paid: bool = False


class RenderPagesJob(_Model):
    kind: Literal["render_pages"] = "render_pages"
    #: Render outward from this page first (the one being looked at).
    near: int = 0


class WarmJob(_Model):
    kind: Literal["warm"] = "warm"
    engine: Backend | None = None


JobRequest = Annotated[
    GenerateJob | PreviewJob | ExportJob | RenderPagesJob | WarmJob, Field(discriminator="kind")
]


class ProgressDTO(_Model):
    phase: str
    done: int
    total: int
    label: str


class JobDTO(_Model):
    id: str
    kind: Literal["generate", "preview", "export", "render_pages", "warm"]
    deck: str
    status: Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]
    inputs: dict[str, Any]
    progress: ProgressDTO
    result: dict[str, Any] | None
    error: ErrorBody | None
    created_at: float
    started_at: float | None
    finished_at: float | None


class TransitionFamilyDTO(_Model):
    key: str
    label: str
    #: (direction label, stored name) pairs; empty for a non-directional family.
    options: list[tuple[str, str]]


class MetaDTO(_Model):
    """Static facts the editor needs: the transition gallery and the engines."""

    transitions: list[TransitionFamilyDTO]
    aliases: dict[str, str]
    engines: list[EngineDTO]


class EngineVoicesDTO(_Model):
    engine: Backend
    voices: list[str]
    default: str | None


class PagesDTO(_Model):
    """Page images only — cheap to refetch while pages render in the background."""

    images: list[str | None]


class GenerateRequest(_Model):
    #: Specific clips, or ``None`` for every clip without audio.
    targets: list[ClipRef] | None = None
    force: bool = False
    engine: Backend | None = None
    allow_paid: bool = False
    #: The asking tab (so leaving the deck drops only its own queued clips).
    owner: str | None = None


class GenerationRunningDTO(_Model):
    slide_id: str
    speech_index: int
    elapsed: float
    estimate: float | None


class GenerationStatusDTO(_Model):
    engine: Backend
    done: int
    total: int
    running: GenerationRunningDTO | None
    inflight: list[ClipRef]
    queued: int = 0  # how many clips the request that returned this added


class CancelGenerationRequest(_Model):
    engine: Backend | None = None
    owner: str | None = None


class FocusRequest(_Model):
    slide_id: str | None
    engine: Backend | None = None


class CountDTO(_Model):
    count: int


# ---- review ---------------------------------------------------------------------------
class MessageDTO(_Model):
    author: Literal["author", "agent", "system"]
    at: str
    text: str


class ConversationDTO(_Model):
    id: str
    #: An optional name (the agent's, or the author's rename); "" when untitled.
    title: str
    slides: list[str]
    origin: str
    status: Literal["open", "closed"]
    turn: Literal["author", "agent"]
    messages: list[MessageDTO]


class SlideChangeDTO(_Model):
    slide_id: str
    kinds: list[str]
    image: bool
    narration: bool
    moved: bool
    base_index: int | None
    current_index: int | None


class ReviewDTO(_Model):
    """Review for one deck. ``active`` false: no base could be taken (a final build)."""

    active: bool
    final_build: bool
    conversations: list[ConversationDTO]
    changes: list[SlideChangeDTO]
    #: Changed slides no conversation covers yet.
    unfiled: list[str]
    #: Declared in an open conversation, but in neither the base nor the PDF yet.
    pending: dict[str, list[str]]
    #: slide id → "your-turn" | "agent-turn" | "closed" | "unfiled".
    badges: dict[str, str]
    #: The base version's slide order (removed slides sit after their old predecessor).
    base_order: list[str]
    #: Base-version page images of changed or removed slides.
    base_images: dict[str, str]
    #: Word diffs of changed narration: ``[op, word]`` with op ``=``, ``-``, or ``+``.
    diffs: dict[str, list[list[str]]]


class ReviewMarkSeen(_Model):
    """Everything as it is now becomes the base: no changes left to look at."""

    type: Literal["mark_seen"] = "mark_seen"


class ReviewComment(_Model):
    type: Literal["comment"] = "comment"
    slides: list[str]
    text: str = Field(min_length=1)


class ReviewReply(_Model):
    type: Literal["reply"] = "reply"
    conversation: str
    text: str = Field(min_length=1)


class ReviewAccept(_Model):
    type: Literal["accept"] = "accept"
    conversation: str


class ReviewRetitle(_Model):
    type: Literal["retitle"] = "retitle"
    conversation: str
    title: str


class ReviewReopen(_Model):
    type: Literal["reopen"] = "reopen"
    conversation: str


class ReviewClear(_Model):
    type: Literal["clear"] = "clear"


class ReviewFileUnrequested(_Model):
    type: Literal["file_unrequested"] = "file_unrequested"


ReviewCommand = Annotated[
    ReviewMarkSeen
    | ReviewComment
    | ReviewReply
    | ReviewAccept
    | ReviewRetitle
    | ReviewReopen
    | ReviewClear
    | ReviewFileUnrequested,
    Field(discriminator="type"),
]


class ReviewOutcomeDTO(_Model):
    message: str
    conversation: str | None
    count: int
    #: Point the user at this conversation (a big batch of unrequested changes).
    focus: bool


class SessionDTO(_Model):
    #: Sent back as ``X-SlideSonnet-Session`` on every mutating request.
    token: str
