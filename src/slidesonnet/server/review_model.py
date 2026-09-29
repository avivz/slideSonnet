"""The editor's view of review state — UI-free, so it's unit-testable.

Wraps :mod:`slidesonnet.review.ops` for the editor: caches the expensive page
capture (a raster hash of every page) until the PDF changes, joins it with the
narration the editor already holds, and answers per-slide questions (what
changed, which conversations, which badge). Everything it writes goes through
``ops`` as the author; automatic filing and edit notes happen only while review
mode is on (``<deck>.review`` exists), so an editor session never starts a
review by itself.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from slidesonnet.narration.format import parse_sidecar, serialize_body
from slidesonnet.narration.model import PageNarration
from slidesonnet.pdf.reader import is_final_build
from slidesonnet.review import base as base_mod
from slidesonnet.review import ops
from slidesonnet.review.diff import SlideChange, diff_versions
from slidesonnet.review.log import Conversation, ReviewState
from slidesonnet.review.versions import DeckVersion, PageCapture, capture_pages, combine

Badge = Literal["your-turn", "agent-turn", "closed", "unfiled"]
WordOp = tuple[Literal["=", "-", "+"], str]


def _stamp(path: Path) -> tuple[float, int]:
    try:
        st = path.stat()
    except OSError:
        return (0.0, 0)
    return (st.st_mtime, st.st_size)


def word_diff(old: str, new: str) -> list[WordOp]:
    """Word-level diff: ``=`` kept, ``-`` removed, ``+`` added, in reading order."""
    a, b = old.split(), new.split()
    out: list[WordOp] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            out += [("=", w) for w in a[i1:i2]]
        else:
            out += [("-", w) for w in a[i1:i2]]
            out += [("+", w) for w in b[j1:j2]]
    return out


def _body(narration_block_text: str) -> str:
    if not narration_block_text:
        return ""
    blocks = parse_sidecar(narration_block_text)
    return serialize_body(blocks[0]) if blocks else ""


@dataclass
class EditorReviewStatus:
    """What the editor shows: diffs, conversations, and the two versions."""

    state: ReviewState
    changes: list[SlideChange]
    unfiled: list[str]
    final_build: bool
    base: DeckVersion | None
    current: DeckVersion | None


class ReviewModel:
    def __init__(self, pdf_path: Path, sidecar_path: Path | None = None) -> None:
        self.pdf_path = pdf_path.resolve()
        #: An explicit narration file (``edit --narration``); None is ``<deck>.narration``.
        self.sidecar_path = sidecar_path
        self._pages: tuple[tuple[float, int], PageCapture, bool] | None = None
        self._log: tuple[tuple[float, int], ReviewState] | None = None
        self._base: tuple[tuple[float, int], DeckVersion | None] | None = None

    # ---- mode ------------------------------------------------------------------
    @property
    def active(self) -> bool:
        return ops.is_active(self.pdf_path)

    @property
    def review_path(self) -> Path:
        return ops.review_path(self.pdf_path)

    def log_stamp(self) -> tuple[float, int]:
        """Change signature of the log — the editor polls it to relight the panel."""
        return _stamp(self.review_path)

    def ensure_base(self) -> None:
        """Take the base now if the deck has none (quietly: no file beside the deck)."""
        if self._base_version() is None:
            ops.ensure_base(self.pdf_path, sidecar_path=self.sidecar_path)
            self._base = None

    def mark_seen(self) -> None:
        """Everything as it is now becomes the base."""
        ops.mark_seen(self.pdf_path, sidecar_path=self.sidecar_path)
        self._base = None

    def pages_fresh(self) -> bool:
        """True when the cached page capture still matches the PDF (status is cheap)."""
        return self._pages is not None and self._pages[0] == _stamp(self.pdf_path)

    # ---- cached reads --------------------------------------------------------------
    def _page_capture(self) -> tuple[PageCapture, bool]:
        stamp = _stamp(self.pdf_path)
        if self._pages is None or self._pages[0] != stamp:
            final = is_final_build(self.pdf_path)
            pages = (
                PageCapture(order=(), pages={})
                if final
                else capture_pages(
                    self.pdf_path, reference=base_mod.reference_images(self.pdf_path)
                )
            )
            self._pages = (stamp, pages, final)
        return self._pages[1], self._pages[2]

    def _state(self) -> ReviewState:
        stamp = self.log_stamp()
        if self._log is None or self._log[0] != stamp:
            self._log = (stamp, ops.load(self.pdf_path))
        return self._log[1]

    def _base_version(self) -> DeckVersion | None:
        path = base_mod.base_dir(self.pdf_path) / "base.json"
        stamp = _stamp(path)
        if self._base is None or self._base[0] != stamp:
            self._base = (stamp, base_mod.load_base(self.pdf_path))
        return self._base[1]

    def status(self, narration: Mapping[str, PageNarration]) -> EditorReviewStatus:
        """Diff the base against the PDF on disk + the editor's *narration*."""
        state = self._state()
        pages, final = self._page_capture()
        base = self._base_version()
        if final or base is None:
            return EditorReviewStatus(state, [], [], final, base, None)
        current = combine(pages, narration)
        changes = diff_versions(base, current)
        filed = {sid for c in state.slide_conversations() for sid in c.slides}
        unfiled = [c.slide_id for c in changes if c.slide_id not in filed]
        return EditorReviewStatus(state, changes, unfiled, final, base, current)

    # ---- per-slide questions ---------------------------------------------------
    @staticmethod
    def change_for(status: EditorReviewStatus, slide_id: str) -> SlideChange | None:
        return next((c for c in status.changes if c.slide_id == slide_id), None)

    @staticmethod
    def conversations_for(status: EditorReviewStatus, slide_id: str) -> list[Conversation]:
        return [c for c in status.state.slide_conversations() if slide_id in c.slides]

    def badge(self, status: EditorReviewStatus, slide_id: str) -> Badge | None:
        convs = self.conversations_for(status, slide_id)
        open_convs = [c for c in convs if c.status == "open"]
        if any(c.turn == "author" for c in open_convs):
            return "your-turn"
        if open_convs:
            return "agent-turn"
        if convs:
            return "closed"
        if slide_id in status.unfiled:
            return "unfiled"
        return None

    def base_image(self, slide_id: str) -> Path | None:
        return base_mod.base_image(self.pdf_path, slide_id)

    def narration_diff(self, slide_id: str, narration: Mapping[str, PageNarration]) -> list[WordOp]:
        base = self._base_version()
        old = _body(base.slides[slide_id].narration) if base and slide_id in base.slides else ""
        block = narration.get(slide_id)
        new = serialize_body(block) if block is not None else ""
        return word_diff(old, new)

    # ---- writes (as the author) ------------------------------------------------
    def comment(self, slide_ids: list[str], text: str) -> str:
        return ops.comment(self.pdf_path, slide_ids, text, author="author")

    def reply(self, conv_id: str, text: str) -> None:
        ops.reply(self.pdf_path, conv_id, text, author="author")

    def accept(self, conv_id: str) -> None:
        ops.accept(self.pdf_path, conv_id)

    def reopen(self, conv_id: str) -> None:
        ops.reopen(self.pdf_path, conv_id)

    def send(self) -> None:
        ops.send(self.pdf_path)

    def clear(self) -> ops.ClearResult:
        pages, _final = self._page_capture()
        result = ops.clear(self.pdf_path, pages=pages, sidecar_path=self.sidecar_path)
        self._base = None
        return result

    def file_unrequested(self, narration: Mapping[str, PageNarration]) -> tuple[str, int] | None:
        """File changed slides that are in no conversation; (id, count) or None."""
        if not self.active:
            return None
        unfiled = self.status(narration).unfiled
        if not unfiled:
            return None
        return ops.open_unrequested(self.pdf_path, unfiled), len(unfiled)

    def note_edits(self, slide_ids: set[str]) -> None:
        """The author edited these slides' narration in the editor."""
        if not self.active:
            return
        for sid in sorted(slide_ids):
            ops.note_author_edit(self.pdf_path, sid)
