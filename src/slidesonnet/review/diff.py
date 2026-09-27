"""Compare two deck versions slide by slide, matched by slide id."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from slidesonnet.review.versions import DeckVersion

ChangeKind = Literal["new", "deleted", "edited", "moved"]


@dataclass(frozen=True)
class SlideChange:
    """How one slide differs between the base and the current version."""

    slide_id: str
    base_index: int | None  # position in the base order; None when new
    current_index: int | None  # position in the current order; None when deleted
    image: bool = False  # the page looks different
    narration: bool = False  # the narration block differs
    moved: bool = False  # off the longest common subsequence of the two orders

    @property
    def new(self) -> bool:
        return self.base_index is None

    @property
    def deleted(self) -> bool:
        return self.current_index is None

    @property
    def kinds(self) -> tuple[ChangeKind, ...]:
        if self.new:
            return ("new",)
        if self.deleted:
            return ("deleted",)
        kinds: list[ChangeKind] = []
        if self.image or self.narration:
            kinds.append("edited")
        if self.moved:
            kinds.append("moved")
        return tuple(kinds)


def moved_ids(base: tuple[str, ...], current: tuple[str, ...]) -> set[str]:
    """Ids in both orders that aren't on their longest common subsequence.

    Inserting or deleting a slide shifts every later position but moves
    nothing: the survivors keep their relative order, so they're all on the
    LCS. Only a slide that jumped past others falls off it.
    """
    common = set(base) & set(current)
    a = [s for s in base if s in common]
    b = [s for s in current if s in common]
    # classic O(n·m) LCS table — decks are tens of slides
    lengths = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) - 1, -1, -1):
        for j in range(len(b) - 1, -1, -1):
            if a[i] == b[j]:
                lengths[i][j] = lengths[i + 1][j + 1] + 1
            else:
                lengths[i][j] = max(lengths[i + 1][j], lengths[i][j + 1])
    on_lcs: set[str] = set()
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            on_lcs.add(a[i])
            i += 1
            j += 1
        elif lengths[i + 1][j] >= lengths[i][j + 1]:
            i += 1
        else:
            j += 1
    return common - on_lcs


def diff_versions(base: DeckVersion, current: DeckVersion) -> list[SlideChange]:
    """Every slide that differs: current order first, then deleted in base order."""
    base_pos = {sid: i for i, sid in enumerate(base.order)}
    cur_pos = {sid: i for i, sid in enumerate(current.order)}
    moved = moved_ids(base.order, current.order)
    changes: list[SlideChange] = []
    for sid in current.order:
        if sid not in base_pos:
            changes.append(SlideChange(sid, None, cur_pos[sid]))
            continue
        old, new = base.slides[sid], current.slides[sid]
        change = SlideChange(
            sid,
            base_pos[sid],
            cur_pos[sid],
            image=old.image_hash != new.image_hash,
            narration=old.narration != new.narration,
            moved=sid in moved,
        )
        if change.kinds:
            changes.append(change)
    changes += [SlideChange(sid, base_pos[sid], None) for sid in base.order if sid not in cur_pos]
    return changes
