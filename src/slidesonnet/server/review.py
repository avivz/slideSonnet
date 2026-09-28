"""Review, seen from the editor: one read model and typed commands over ``review/*``.

The on-disk format and the CLI are untouched: every write goes through
:mod:`slidesonnet.review.ops` as the author, exactly as ``slidesonnet review``
and the NiceGUI panel did. Capturing the current pages (a raster hash of every
page) is the slow part, so each deck keeps one
:class:`~slidesonnet.server.review_model.ReviewModel`, which caches that capture until
the PDF changes. Blocking — call off the event loop.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidesonnet.pdf.reader import is_final_build
from slidesonnet.review import ops
from slidesonnet.server.decks import deck_service
from slidesonnet.server.library import DeckEntry
from slidesonnet.server.media import base_media_url
from slidesonnet.server.review_model import EditorReviewStatus, ReviewModel

#: A reload that files more unrequested slides than this points the user at them.
MASS_EDIT_THRESHOLD = 5

_models: dict[Path, ReviewModel] = {}
_models_lock = threading.Lock()


def review_model(pdf_path: Path) -> ReviewModel:
    pdf = Path(pdf_path).resolve()
    with _models_lock:
        model = _models.get(pdf)
        if model is None:
            model = _models[pdf] = ReviewModel(pdf)
        return model


def reset_review_models() -> None:
    with _models_lock:
        _models.clear()


def _conversation(conv: Any) -> dict[str, Any]:
    return {
        "id": conv.id,
        "title": conv.title,
        "slides": list(conv.slides),
        "origin": conv.origin,
        "status": conv.status,
        "turn": conv.turn,
        "is_deck": bool(conv.is_deck),
        "messages": [{"author": m.author, "at": m.at, "text": m.text} for m in conv.messages],
    }


def review_snapshot(entry: DeckEntry) -> dict[str, Any]:
    """Everything the review panel shows, as plain data."""
    pdf = entry.pdf_path
    model = review_model(pdf)
    model.ensure_base()  # review is always on: the first look at a deck takes its base
    if not model.active:
        return {
            "active": False, "final_build": is_final_build(pdf), "conversations": [], "changes": [],
            "unfiled": [], "pending": {}, "badges": {}, "base_order": [], "base_images": {},
            "diffs": {},
        }  # fmt: skip
    loaded = deck_service(pdf, entry.sidecar_path).load()
    narration = loaded.deck.narration
    status: EditorReviewStatus = model.status(narration)
    state = status.state
    pages = set(loaded.deck.pages)
    base_order = list(status.base.order) if status.base is not None else []
    known = pages | set(base_order)

    pending: dict[str, list[str]] = {}
    for conv in state.slide_conversations():
        if conv.status != "open":
            continue
        for sid in conv.slides:
            if sid not in known:
                pending.setdefault(sid, []).append(conv.id)

    base_images: dict[str, str] = {}
    diffs: dict[str, list[list[str]]] = {}
    for change in status.changes:
        if change.image or change.deleted:
            image = model.base_image(change.slide_id)
            if image is not None:
                base_images[change.slide_id] = base_media_url(pdf, image)
        if change.narration and not change.deleted:
            diffs[change.slide_id] = [
                [op, word] for op, word in model.narration_diff(change.slide_id, narration)
            ]
    badges = {}
    for sid in known:
        badge = model.badge(status, sid)
        if badge is not None:
            badges[sid] = badge
    return {
        "active": True,
        "final_build": status.final_build,
        "conversations": [_conversation(c) for c in state.conversations.values()],
        "changes": [
            {
                "slide_id": c.slide_id,
                "kinds": list(c.kinds),
                "image": c.image,
                "narration": c.narration,
                "moved": c.moved,
                "base_index": c.base_index,
                "current_index": c.current_index,
            }
            for c in status.changes
        ],
        "unfiled": list(status.unfiled),
        "pending": pending,
        "badges": badges,
        "base_order": base_order,
        "base_images": base_images,
        "diffs": diffs,
    }


@dataclass(frozen=True)
class CommandOutcome:
    message: str
    conversation: str | None = None
    count: int = 0


def run_command(entry: DeckEntry, command: str, args: dict[str, Any]) -> CommandOutcome:
    """Apply one review command as the author. Raises SlideSonnetError on refusal."""
    pdf = entry.pdf_path
    model = review_model(pdf)
    if command == "mark_seen":
        model.mark_seen()
        return CommandOutcome("Comparison reset — changes are shown from here")
    if command == "comment":
        conv_id = model.comment(list(args["slides"]), str(args["text"]))
        model.send()  # every note wakes a waiting agent: sending *is* the handover
        return CommandOutcome("Note sent", conversation=conv_id)
    if command == "reply":
        model.reply(str(args["conversation"]), str(args["text"]))
        model.send()
        return CommandOutcome("Reply sent", conversation=str(args["conversation"]))
    if command == "retitle":
        ops.retitle(pdf, str(args["conversation"]), str(args["title"]))
        return CommandOutcome("Renamed", conversation=str(args["conversation"]))
    if command == "accept":
        model.accept(str(args["conversation"]))
        return CommandOutcome("Accepted", conversation=str(args["conversation"]))
    if command == "reopen":
        model.reopen(str(args["conversation"]))
        return CommandOutcome("Reopened", conversation=str(args["conversation"]))
    if command == "clear":
        result = model.clear()
        message = f"Cleared {len(result.cleared)} conversation(s)"
        if result.skipped:
            message += " — some slides wait on an open conversation"
        return CommandOutcome(message, count=len(result.cleared))
    if command == "file_unrequested":
        narration = deck_service(pdf, entry.sidecar_path).load().deck.narration
        filed = model.file_unrequested(narration)
        if filed is None:
            return CommandOutcome("")
        conv_id, count = filed
        noun = "slide" if count == 1 else "slides"
        return CommandOutcome(
            f"{count} {noun} changed without being asked — see {conv_id}",
            conversation=conv_id,
            count=count,
        )
    raise ValueError(f"unknown review command {command!r}")


def is_active(entry: DeckEntry) -> bool:
    return ops.is_active(entry.pdf_path)
