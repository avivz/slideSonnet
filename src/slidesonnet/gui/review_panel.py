"""The editor's review tools: conversations, compare view, filmstrip badges.

A component of :class:`slidesonnet.gui.app.EditorView`. The UI-free logic lives
in :class:`slidesonnet.gui.review.ReviewModel`; this module only draws it:

- **console** — "Start review" until ``<deck>.review`` exists; then Send (with
  optional auto-send), Clear accepted, the permanent Deck conversation, this
  slide's conversations (reply / Accept / Reopen, and a note box that opens a
  new one), and the list of all conversations (click one to filter the strip).
- **stage** — the base version of the current slide beside the current one when
  the page changed (``D`` toggles before-only), and a word diff of the narration.
- **filmstrip** — a badge per slide (your turn / agent's turn / closed /
  unfiled), and a *before* strip in base order when slides were added, removed,
  or moved.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nicegui import run, ui

from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.gui.review import EditorReviewStatus
from slidesonnet.review.log import Conversation

if TYPE_CHECKING:
    from slidesonnet.gui.app import EditorView

logger = logging.getLogger(__name__)

#: A reload that files more unrequested slides than this raises a warning.
MASS_EDIT_THRESHOLD = 5

_BADGE_CLASSES = "ss-rv-your-turn ss-rv-agent-turn ss-rv-closed ss-rv-unfiled"
_BADGE_TEXT = {
    "your-turn": "●",
    "agent-turn": "◌",
    "closed": "✓",
    "unfiled": "!",
}
_BADGE_TIP = {
    "your-turn": "A conversation here is waiting for you",
    "agent-turn": "Waiting for the agent",
    "closed": "Accepted — not yet cleared",
    "unfiled": "Changed without a conversation",
}
_AUTHOR_LABEL = {"author": "You", "agent": "Agent", "system": "Note"}


def _turn_label(conv: Conversation) -> str:
    if conv.status == "closed":
        return "accepted"
    return "your turn" if conv.turn == "author" else "agent's turn"


def _origin_label(conv: Conversation) -> str:
    return {"unrequested": " · unrequested", "author-edits": " · your edits"}.get(conv.origin, "")


class ReviewPanel:
    def __init__(self, view: EditorView) -> None:
        self.view = view
        self.status: EditorReviewStatus | None = None
        self.filter_conv: str | None = None
        self.before_only = False  # D: show the base version full-size
        self.show_closed = False  # accepted conversations stay out of the way
        self.badges: list[Any] = []
        self.moved_marks: list[Any] = []
        self.removed_cards: dict[str, Any] = {}  # removed slide id -> its strip tile
        self._built_layout: dict[int, list[str]] = {}  # removed slides the strip shows
        self.viewing_removed: str | None = None  # a removed slide shown on the stage
        self._log_stamp: tuple[float, int] | None = None
        self._refreshing = False

    @property
    def refreshing(self) -> bool:
        return self._refreshing

    @property
    def model(self) -> Any:
        return self.view.state.review

    # ---- building ------------------------------------------------------------
    def build_console(self) -> None:
        """Called inside the console's Review tab."""
        self.box = ui.column().classes("w-full gap-2 ss-review").mark("review-panel")

    def build_tab_badge(self) -> None:
        """Called inside the Review tab: how many conversations here wait for you."""
        self.tab_badge = ui.badge("").props("rounded").classes("ss-tab-badge")
        self.tab_badge.mark("console-tab-review-badge")
        self.tab_badge.visible = False

    def build_stage(self) -> None:
        """Called inside the stage view, before the current slide image."""
        with ui.column().classes("ss-before gap-0 hidden").mark("stage-before-box") as col:
            self.before_col = col
            self.before_cap = ui.label("Before").classes("ss-before-cap")
            self.before_img = (
                ui.image().classes("ss-stage-img").props('fit="contain" no-spinner')
            ).mark("stage-before")
        self.before_img.visible = False

    def build_diff_box(self) -> None:
        self.diff_box = ui.html("").classes("ss-narr-diff w-full").mark("narration-diff")
        self.diff_box.visible = False

    def decorate_thumb(self, index: int) -> None:
        """Add the review badge and moved mark to the thumb being built (inside its card)."""
        badge = ui.label("").classes("ss-thumb-review hidden").mark(f"thumb-review-{index}")
        self.badges.append(badge)
        moved = ui.label("↕").classes("ss-thumb-moved hidden").mark(f"thumb-moved-{index}")
        self.moved_marks.append(moved)

    def reset_thumbs(self) -> None:
        self.badges.clear()
        self.moved_marks.clear()
        self.removed_cards.clear()

    # ---- removed slides in the strip -------------------------------------------
    def removed_after(self) -> dict[int, list[str]]:
        """For building the strip: removed slides by the index they follow (-1: first)."""
        self._built_layout = self._removed_layout()
        return self._built_layout

    def _removed_layout(self) -> dict[int, list[str]]:
        """One filmstrip, in the current order: a slide that's gone sits right after
        the slide that preceded it in the base order (the nearest one still here)."""
        st = self.status
        layout: dict[int, list[str]] = {}
        if st is not None and st.base is not None:
            pages = self.view.state.deck.pages
            position = {sid: i for i, sid in enumerate(pages)}
            gone = {c.slide_id for c in st.changes if c.deleted}
            anchor = -1
            for sid in st.base.order:
                if sid in position:
                    anchor = position[sid]
                elif sid in gone:
                    layout.setdefault(anchor, []).append(sid)
        return layout

    def build_removed_thumb(self, sid: str) -> None:
        """A faded tile for a removed slide (its base image); click to look at it."""
        image = self.model.base_image(sid)
        with (
            ui.element("div")
            .classes("ss-thumb ss-removed-thumb")
            .mark(f"removed-thumb-{sid}") as card
        ):
            with ui.element("div").classes("ss-thumb-slot"):
                if image is not None:
                    ui.image(self.view.base_media_url(image)).classes("w-full")
                else:
                    ui.label(sid).classes("ss-thumb-fallback ss-mono")
            ui.label("removed").classes("ss-thumb-removed-cap")
        card.props('title="Removed since the base — click to see it"')
        card.on("click", lambda _e=None, sid=sid: self._removed_click(sid))
        self.removed_cards[sid] = card

    def _removed_click(self, sid: str) -> None:
        self.leave_filter_for(sid)
        self.view_removed(sid)

    def view_removed(self, sid: str) -> None:
        """Show a removed slide's base version on the stage (and its conversations)."""
        self.view.blocks.save_current()
        self.viewing_removed = sid
        self.sync()

    def leave_removed(self) -> None:
        self.viewing_removed = None

    # ---- the chosen conversation: dims the rest, arrows stay inside ------------
    def _scope(self) -> set[str] | None:
        st = self.status
        if st is None or self.filter_conv is None:
            return None
        conv = st.state.conversations.get(self.filter_conv)
        return set(conv.slides) if conv is not None else None

    def leave_filter_for(self, sid: str) -> None:
        """Clicking a slide outside the chosen conversation leaves that view."""
        scope = self._scope()
        if scope is not None and sid not in scope:
            self.filter_conv = None

    def _strip_order(self) -> list[tuple[str, int]]:
        """(slide id, current index or -1 for removed) in filmstrip order."""
        pages = self.view.state.deck.pages
        order: list[tuple[str, int]] = [(sid, -1) for sid in self._built_layout.get(-1, [])]
        for i, sid in enumerate(pages):
            order.append((sid, i))
            order += [(gone, -1) for gone in self._built_layout.get(i, [])]
        return order

    def step(self, delta: int) -> bool:
        """Arrow keys: through the chosen conversation's slides, or off a removed one.

        Returns False when there's nothing special to do (plain slide stepping).
        """
        scope = self._scope()
        if scope is None and self.viewing_removed is None:
            return False
        order = self._strip_order()
        here = self.viewing_removed or self.view.state.current_id
        pos = next((k for k, (sid, _i) in enumerate(order) if sid == here), None)
        if pos is None:
            return False
        k = pos + delta
        while 0 <= k < len(order):
            sid, index = order[k]
            if scope is None and index >= 0:
                self.view.jump(index)
                return True
            if scope is not None and sid in scope:
                if index >= 0:
                    self.view.jump(index)
                else:
                    self.view_removed(sid)
                return True
            k += delta
        return True  # at the end of the conversation (or strip): stay put

    # ---- status --------------------------------------------------------------
    def compute(self) -> None:
        """Recompute status now (cheap unless the PDF changed since last time)."""
        state = self.view.state
        try:
            self.status = self.model.status(state.deck.narration) if self.model.active else None
        except Exception:  # never let a review hiccup take the editor down
            logger.warning("review status failed", exc_info=True)
            self.status = None

    async def refresh(self) -> None:
        """Recompute off the event loop (the page capture rasterizes every page)."""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            state = self.view.state
            if self.model.active:
                self.status = await run.io_bound(self.model.status, state.deck.narration)
            else:
                self.status = None
        except Exception:
            logger.warning("review status failed", exc_info=True)
            self.status = None
        finally:
            self._refreshing = False
        self._log_stamp = self.model.log_stamp()
        self.sync()

    async def poll(self) -> None:
        """Relight when the log changed (an agent replied, another window wrote)."""
        stamp = self.model.log_stamp()
        if stamp != self._log_stamp:
            await self.refresh()

    async def after_reload(self) -> None:
        """A recompile or outside narration edit landed: file unrequested changes."""
        state = self.view.state
        try:
            filed = await run.io_bound(self.model.file_unrequested, state.deck.narration)
        except Exception:
            logger.warning("could not file unrequested changes", exc_info=True)
            filed = None
        await self.refresh()
        if filed is None:
            return
        cid, count = filed
        if count > MASS_EDIT_THRESHOLD:
            self.filter_conv = cid
            self.sync()
        noun = "slide" if count == 1 else "slides"
        self.view.flash(f"{count} {noun} changed without being asked — see {cid}", "warning")

    # ---- drawing -------------------------------------------------------------
    def sync(self) -> None:
        """Redraw everything review-related from the current status."""
        self._sync_console()
        self._sync_tab_badge()
        self._sync_strip()
        self._sync_stage()

    def _sync_console(self) -> None:
        self.box.clear()
        with self.box:
            if not self.model.active:
                with ui.row().classes("w-full items-center justify-between no-wrap"):
                    ui.label("Review").classes("ss-section")
                start = ui.button("Start review", icon="rate_review", on_click=self._start)
                start.props("flat dense no-caps").mark("review-start")
                ui.label(
                    "Compare the next changes against the deck as it is now, "
                    "slide by slide, and talk them over with the agent."
                ).classes("ss-diag ss-diag-info")
                return
            st = self.status
            with ui.row().classes("w-full items-center no-wrap gap-1"):
                ui.label("Review").classes("ss-section")
                ui.space()
                closed = [
                    c
                    for c in (st.state.slide_conversations() if st else [])
                    if c.status == "closed"
                ]
                clear = ui.button(f"Clear accepted ({len(closed)})", on_click=self._clear)
                clear.props("flat dense no-caps size=sm").mark("review-clear")
                clear.set_enabled(bool(closed))
                clear.tooltip("Make accepted changes the new starting point")
            if closed or self.show_closed:
                show = ui.checkbox(
                    f"Show closed ({len(closed)})",
                    value=self.show_closed,
                    on_change=lambda e: self._set_show_closed(bool(e.value)),
                )
                show.props("dense size=xs").classes("ss-diag").mark("review-show-closed")
            if st is not None and st.final_build:
                ui.label("Final build — comparison paused until the next normal compile.").classes(
                    "ss-diag ss-diag-warn"
                )
            if st is None:
                ui.label("Comparing…").classes("ss-diag ss-diag-info")
                return
            self._draw_deck(st)
            self._draw_this_slide(st)
            self._draw_list(st)

    def _sync_tab_badge(self) -> None:
        st = self.status
        sid = self.view.state.current_id
        waiting = 0
        if self.model.active and st is not None and sid:
            waiting = sum(
                1
                for c in self.model.conversations_for(st, sid)
                if c.status == "open" and c.turn == "author"
            )
        self.tab_badge.set_text(str(waiting))
        self.tab_badge.visible = waiting > 0

    def _messages(self, conv: Conversation) -> None:
        for msg in conv.messages:
            with ui.column().classes(f"ss-msg ss-msg-{msg.author} gap-0 w-full"):
                ui.label(f"{_AUTHOR_LABEL[msg.author]} · {msg.at[11:16]}").classes("ss-msg-meta")
                ui.label(msg.text).classes("ss-msg-text")

    def _note_box(self, marker: str, placeholder: str, on_add: Any) -> None:
        """A note field: Enter (or the Send button) sends it; Shift+Enter is a new line."""
        area = ui.textarea(placeholder=placeholder).props("dense outlined autogrow")
        area.classes("w-full ss-note").mark(marker)

        def on_enter(e: Any) -> None:
            if isinstance(e.args, dict) and e.args.get("shiftKey"):
                return
            on_add(area)

        area.on("keydown.enter", on_enter, args=["shiftKey"])
        send = ui.button("Send", icon="send", on_click=lambda: on_add(area))
        send.props("flat dense no-caps size=sm").mark(f"{marker}-add")
        send.tooltip("Send to the agent (Enter)")

    def _draw_deck(self, st: EditorReviewStatus) -> None:
        deck = st.state.conversations["deck"]
        with ui.expansion("Deck", value=True).classes("w-full ss-rv-deck").props("dense"):
            if deck.messages:
                ui.label(_turn_label(deck)).classes("ss-msg-meta")
            self._messages(deck)
            self._note_box(
                "deck-note",
                "Instructions for the agent about the whole deck…",
                lambda area: self._add(area, lambda text: self.model.reply("deck", text)),
            )

    def _draw_this_slide(self, st: EditorReviewStatus) -> None:
        sid = self.viewing_removed or self.view.state.current_id
        if not sid:
            return
        ui.label("This slide").classes("ss-section")
        change = self.model.change_for(st, sid)
        if change is not None:
            detail = [
                k for k, on in (("slide", change.image), ("narration", change.narration)) if on
            ]
            text = ", ".join(change.kinds)
            if change.moved and change.base_index is not None:
                text += f" (was slide {change.base_index + 1})"
            if detail:
                text += " — " + ", ".join(detail)
            ui.label(f"Changed: {text}").classes("ss-diag ss-diag-warn")
        convs = sorted(
            (
                c
                for c in self.model.conversations_for(st, sid)
                if c.status == "open" or self.show_closed
            ),
            key=lambda c: (c.status != "open", c.id),
        )
        for conv in convs:
            with ui.column().classes("w-full gap-1 ss-conv"):
                ui.label(f"{conv.id} · {_turn_label(conv)}{_origin_label(conv)}").classes(
                    "ss-conv-head"
                )
                self._messages(conv)
                if conv.status == "open":
                    self._note_box(
                        f"reply-{conv.id}",
                        "Reply…",
                        lambda area, cid=conv.id: self._add(
                            area, lambda text: self.model.reply(cid, text)
                        ),
                    )
                    accept = ui.button(
                        "Accept", icon="check", on_click=lambda cid=conv.id: self._accept(cid)
                    )
                    accept.props("flat dense no-caps size=sm").mark(f"accept-{conv.id}")
                    accept.tooltip("Close this conversation — its changes are accepted")
                else:
                    reopen = ui.button(
                        "Reopen", icon="undo", on_click=lambda cid=conv.id: self._reopen(cid)
                    )
                    reopen.props("flat dense no-caps size=sm").mark(f"reopen-{conv.id}")
        self._note_box(
            "slide-note",
            "New note for the agent about this slide…",
            lambda area: self._add(area, lambda text: self.model.comment([sid], text)),
        )

    def _draw_list(self, st: EditorReviewStatus) -> None:
        convs = [
            c
            for c in st.state.slide_conversations()
            if c.status == "open" or self.show_closed or c.id == self.filter_conv
        ]
        if not convs:
            return
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("Conversations").classes("ss-section")
            ui.space()
            if self.filter_conv is not None:
                clr = ui.button("Show all slides", on_click=self._clear_filter)
                clr.props("flat dense no-caps size=sm").mark("conv-filter-clear")
        for conv in convs:
            scope = " ".join(f"@{s}" for s in conv.slides)
            row = ui.label(f"{conv.id} · {_turn_label(conv)}{_origin_label(conv)} · {scope}")
            row.classes("ss-conv-row" + (" ss-active" if conv.id == self.filter_conv else ""))
            row.mark(f"conv-row-{conv.id}")
            row.on("click", lambda _e=None, cid=conv.id: self._select(cid))

    def _sync_strip(self) -> None:
        state = self.view.state
        st = self.status
        if self._removed_layout() != self._built_layout:
            self.view.build_strip()  # removed slides came or went: re-lay the strip
            self.view.render_side()  # the rebuilt thumbs need their dots and highlight
        if self.filter_conv is not None and self._scope() is None:
            self.filter_conv = None  # its conversation is gone (cleared)
        scope = self._scope()
        moved = {c.slide_id: c.base_index for c in (st.changes if st else []) if c.moved}
        for i, badge in enumerate(self.badges):
            if i >= len(state.deck.pages):
                break
            sid = state.deck.pages[i]
            kind = self.model.badge(st, sid) if st is not None else None
            badge.classes(remove=_BADGE_CLASSES + " hidden")
            if kind is None:
                badge.classes(add="hidden")
            else:
                badge.set_text(_BADGE_TEXT[kind])
                badge.classes(add=f"ss-rv-{kind}")
                # a title attribute, not .tooltip(): that adds a child per redraw
                badge.props(f'title="{_BADGE_TIP[kind]}"')
            if i < len(self.moved_marks):
                mark = self.moved_marks[i]
                if sid in moved:
                    was = moved[sid]
                    mark.classes(remove="hidden")
                    tip = f"Moved — was slide {was + 1}" if was is not None else "Moved"
                    mark.props(f'title="{tip}"')
                else:
                    mark.classes(add="hidden")
            if i < len(self.view.thumb_cards):
                card = self.view.thumb_cards[i][0]
                dim = scope is not None and sid not in scope
                card.classes(add="ss-dimmed") if dim else card.classes(remove="ss-dimmed")
                if self.viewing_removed is not None:
                    card.classes(remove="ss-active")
        for sid, card in self.removed_cards.items():
            dim = scope is not None and sid not in scope
            card.classes(add="ss-dimmed") if dim else card.classes(remove="ss-dimmed")
            if sid == self.viewing_removed:
                card.classes(add="ss-active")
            else:
                card.classes(remove="ss-active")

    def _sync_stage(self) -> None:
        state = self.view.state
        st = self.status
        removed = self.viewing_removed
        sid = removed or state.current_id
        change = self.model.change_for(st, sid) if (st is not None and sid) else None
        image = self.model.base_image(sid) if change is not None and change.image else None
        if removed is not None:
            image = self.model.base_image(removed)
            self.view.id_label.set_text(f"{removed} (removed)")
        self.before_cap.set_text("Removed" if removed is not None else "Before")
        compare = image is not None
        self.before_img.visible = compare
        if compare and image is not None:
            self.before_img.set_source(self.view.base_media_url(image))
            self.before_col.classes(remove="hidden")
        else:
            self.before_col.classes(add="hidden")
        self.view.stage_view.classes(
            remove="ss-compare ss-before-only",
            add=(
                ("ss-compare" + (" ss-before-only" if self.before_only or removed else ""))
                if compare
                else ""
            ),
        )
        if change is not None and change.narration and sid:
            parts = []
            for op, word in self.model.narration_diff(sid, state.deck.narration):
                w = html.escape(word)
                parts.append({"=": w, "-": f"<del>{w}</del>", "+": f"<ins>{w}</ins>"}[op])
            self.diff_box.set_content(
                "<span class='ss-narr-diff-cap'>Narration changes</span> " + " ".join(parts)
            )
            self.diff_box.visible = True
        else:
            self.diff_box.visible = False

    # ---- actions -------------------------------------------------------------
    def _write(self, action: Any) -> bool:
        try:
            action()
        except SlideSonnetError as exc:
            self.view.flash(str(exc), "warning")
            return False
        return True

    def _after_write(self) -> None:
        self.compute()
        self._log_stamp = self.model.log_stamp()
        self.sync()

    def _add(self, area: Any, write: Any) -> None:
        text = str(area.value or "").strip()
        if not text:
            return
        self.view.blocks.save_current()  # the agent should see the saved narration
        # Every note wakes a waiting agent (`review wait`) — sending *is* the handover.
        if self._write(lambda: write(text)) and self._write(self.model.send):
            self._after_write()

    def _start(self) -> None:
        self.view.blocks.save_current()
        if self._write(self.model.start):
            self.view.flash("Review started — changes are compared from here", "positive")
            self._after_write()

    def _set_show_closed(self, value: bool) -> None:
        self.show_closed = value
        self.sync()

    def _accept(self, cid: str) -> None:
        if self._write(lambda: self.model.accept(cid)):
            self._after_write()

    def _reopen(self, cid: str) -> None:
        if self._write(lambda: self.model.reopen(cid)):
            self._after_write()

    def _clear(self) -> None:
        result = None

        def do() -> None:
            nonlocal result
            result = self.model.clear()

        if self._write(do) and result is not None:
            msg = f"Cleared {len(result.cleared)} conversation(s)"
            if result.skipped:
                msg += " — some slides wait on an open conversation"
            self.view.flash(msg, "positive")
            self._after_write()

    def _select(self, cid: str) -> None:
        self.filter_conv = cid
        st = self.status
        conv = st.state.conversations.get(cid) if st else None
        pages = self.view.state.deck.pages
        target = next((s for s in (conv.slides if conv else []) if s in pages), None)
        if target is not None and target != self.view.state.current_id:
            self.view.jump(pages.index(target))  # renders, which syncs the panel
        else:
            self.sync()

    def _clear_filter(self) -> None:
        self.filter_conv = None
        self.sync()

    def _jump_to(self, sid: str) -> None:
        pages = self.view.state.deck.pages
        if sid in pages:
            self.view.jump(pages.index(sid))
        elif sid in self.removed_cards:
            self.view_removed(sid)

    def toggle_before_only(self) -> None:
        self.before_only = not self.before_only
        self._sync_stage()

    def next_your_turn(self) -> None:
        """Jump to the next slide with a conversation waiting for you."""
        st = self.status
        if st is None:
            return
        state = self.view.state
        pages = state.deck.pages
        n = len(pages)
        for step in range(1, n + 1):
            sid = pages[(state.index + step) % n]
            if self.model.badge(st, sid) == "your-turn":
                self.view.jump(pages.index(sid))
                return
        self.view.flash("Nothing waiting for you", "info")


def base_media_path(filename: str) -> str:
    """The media route prefix for base page images (see ``_read_media``)."""
    return f"_base/{Path(filename).name}"
