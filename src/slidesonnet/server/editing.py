"""Narration edits as pure operations on a :class:`Deck`, addressed by slide id.

Every operation names its slide explicitly, so the same rules serve the HTTP
API and tests alike. Nothing in this module touches the disk;
:class:`slidesonnet.server.decks.DeckService` persists the result.
"""

from __future__ import annotations

from dataclasses import replace

from slidesonnet.diagnostics import boundary_transition
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.models import VoiceConfig
from slidesonnet.narration.model import Deck, PageNarration, Segment, Transition


class EditError(SlideSonnetError, ValueError):
    """An edit that can't apply to this deck (unknown slide, occupied target, …)."""


def _neighbours(deck: Deck, slide_id: str) -> tuple[str | None, str | None]:
    index = deck.pages.index(slide_id)
    prev_id = deck.pages[index - 1] if index > 0 else None
    next_id = deck.pages[index + 1] if index + 1 < len(deck.pages) else None
    return prev_id, next_id


def incoming_transition(deck: Deck, slide_id: str) -> Transition:
    """The effective transition *entering* *slide_id*.

    A boundary is one transition shared by two slides; it lives canonically on
    the earlier slide's ``transition_out`` (see
    :func:`diagnostics.boundary_transition`). So a slide's incoming transition is
    its boundary with the previous slide. The first slide has no previous, so its
    own ``transition_in`` stands alone as the deck-open animation.
    """
    prev_id, _ = _neighbours(deck, slide_id)
    block = deck.page_narration(slide_id)
    if prev_id is None:
        return block.transition_in
    return boundary_transition(deck.page_narration(prev_id), block)


def _set_transition_out(deck: Deck, slide_id: str, tr: Transition) -> bool:
    """Set *slide_id*'s ``transition_out`` (dropping an emptied block); changed?"""
    old = deck.narration.get(slide_id)
    base = old if old is not None else PageNarration(slide_id=slide_id)
    if base.transition_out == tr:
        return False
    new = base.with_content(base.segments, transition_out=tr)
    if new.is_empty:
        if old is None:
            return False
        deck.narration.pop(slide_id)
    else:
        deck.narration[slide_id] = new
    return True


def _clear_transition_in(deck: Deck, slide_id: str) -> bool:
    """Reset *slide_id*'s ``transition_in`` to a cut (dropping an emptied block)."""
    old = deck.narration.get(slide_id)
    if old is None or old.transition_in.kind == "cut":
        return False
    new = old.with_content(old.segments, transition_in=Transition())
    if new.is_empty:
        deck.narration.pop(slide_id)
    else:
        deck.narration[slide_id] = new
    return True


def apply_block_edit(
    deck: Deck,
    slide_id: str,
    segments: list[Segment],
    *,
    transition_in: Transition | None = None,
    transition_out: Transition | None = None,
) -> bool:
    """Replace *slide_id*'s block wholesale, in memory; True if the deck changed.

    A block that ends up empty (no segments, plain cuts) is dropped entirely.

    A boundary is only ever stored on the earlier slide's ``transition_out``, so
    the two transition controls stay consistent: *transition_in* is the boundary
    with the previous slide — a real change to it is written to that slide's
    ``transition_out`` (and this slide's own ``transition_in`` cleared), and a
    non-cut *transition_out* clears the *next* slide's ``transition_in``. The
    first slide keeps its own ``transition_in`` (the deck-open animation).
    """
    if not slide_id:
        raise EditError("this page has no slide-id")
    if slide_id not in deck.pages:
        raise EditError(f"'{slide_id}' is not a page in the deck")
    tin = transition_in or Transition()
    tout = transition_out or Transition()
    prev_id, next_id = _neighbours(deck, slide_id)
    current = deck.page_narration(slide_id)

    changed = False
    # The incoming transition belongs to the boundary with the previous slide.
    # Only move it (onto that slide's out, clearing ours) when it actually
    # changed — a plain blur/navigation must not rewrite the sidecar.
    if prev_id is not None and tin != incoming_transition(deck, slide_id):
        changed |= _set_transition_out(deck, prev_id, tin)
        own_in = Transition()
    elif prev_id is None:
        own_in = tin  # first slide: its own deck-open transition
    else:
        own_in = current.transition_in  # unchanged: leave it in place

    cur = deck.narration.get(slide_id)
    cur_base = cur if cur is not None else PageNarration(slide_id=slide_id)
    new_cur = cur_base.with_content(segments, transition_in=own_in, transition_out=tout)
    if new_cur.is_empty:
        if cur is not None:
            deck.narration.pop(slide_id)
            changed = True
    elif cur != new_cur:
        deck.narration[slide_id] = new_cur
        changed = True

    if tout.kind != "cut" and next_id is not None:
        changed |= _clear_transition_in(deck, next_id)
    return changed


# ---- unattached narration (a slide dropped/renamed by a recompile) -----------
def has_narration(deck: Deck, slide_id: str) -> bool:
    block = deck.narration.get(slide_id)
    return block is not None and bool(block.segments)


def orphan_blocks(deck: Deck) -> list[PageNarration]:
    """Narration blocks whose slide id matches no PDF page (sidecar order)."""
    on_page = set(deck.pages)
    return [b for sid, b in deck.narration.items() if sid not in on_page]


def _require_orphan(deck: Deck, orphan_id: str) -> None:
    """Refuse an id that isn't unattached narration (a slide's own, or none at all)."""
    if orphan_id in deck.pages:
        raise EditError(f"'{orphan_id}' is on a slide in the PDF, so it isn't unattached narration")
    if orphan_id not in deck.narration:
        raise EditError(f"no narration block '{orphan_id}'")


def attach_orphan(deck: Deck, orphan_id: str, target_id: str) -> None:
    """Move an orphan block's narration onto the empty page *target_id*."""
    _require_orphan(deck, orphan_id)
    if target_id not in deck.pages:
        raise EditError(f"'{target_id}' is not a page in the deck")
    if has_narration(deck, target_id):
        raise EditError(f"slide '{target_id}' already has narration")
    block = deck.narration.pop(orphan_id)
    deck.narration[target_id] = block.rekeyed(target_id)


def append_orphan(deck: Deck, orphan_id: str, target_id: str) -> None:
    """Append an orphan block's segments after *target_id*'s own narration.

    Unlike :func:`attach_orphan` (which targets an *empty* slide), this merges
    the orphan's utterances/pauses into a live slide.
    """
    if not target_id:
        raise EditError("this page has no slide-id to append to")
    if target_id not in deck.pages:
        raise EditError(f"'{target_id}' is not a page in the deck")
    _require_orphan(deck, orphan_id)
    orphan = deck.narration.pop(orphan_id)
    target = deck.page_narration(target_id)
    deck.narration[target_id] = target.with_content([*target.segments, *orphan.segments])


def delete_orphan(deck: Deck, orphan_id: str) -> bool:
    """Drop an orphan block (and its text) from the deck; False when already gone."""
    if orphan_id in deck.pages:
        _require_orphan(deck, orphan_id)
    return deck.narration.pop(orphan_id, None) is not None


# ---- the portable voice layer -------------------------------------------------
def edit_voices(
    deck: Deck,
    voices: dict[str, VoiceConfig],
    default_voice: str | None,
    *,
    renames: dict[str, str] | None = None,
) -> bool:
    """Replace the voice map + default voice (file paths already resolved); changed?

    *renames* maps an old voice name to its new one: every utterance ``voice:``
    naming the old voice is rewritten, so no reference is left dangling. A delete
    (old name with no new) is *not* a rename — its references stay and surface
    as unmapped. Dropping ``preamble_source`` makes the save regenerate the
    preamble canonically from the edited map.
    """
    default_voice = default_voice or None
    active = {old: new for old, new in (renames or {}).items() if old != new}
    if not active and voices == deck.voices and default_voice == deck.default_voice:
        return False
    for block in deck.narration.values():
        block.segments = [
            replace(seg, voice=active[seg.voice]) if seg.is_speech and seg.voice in active else seg
            for seg in block.segments
        ]
    deck.voices = voices
    deck.default_voice = default_voice
    deck.preamble_source = None
    return True
