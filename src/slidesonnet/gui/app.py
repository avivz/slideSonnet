"""NiceGUI narration editor: page nav, editing, per-slide TTS, preview, export.

The whole-deck preview plays a single pre-rendered track (silences baked in)
and flips the slide image on cue-sheet boundaries, so the preview is
sample-accurate to the exported video.
"""

from __future__ import annotations

import logging
import os
import shutil
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from nicegui import app, background_tasks, run, ui
from nicegui.events import KeyEventArguments

from slidesonnet.audio.track import Cue
from slidesonnet.cache import audio_dir, render_dir
from slidesonnet.diagnostics import boundary_transition
from slidesonnet.gui.jobs import JobQueue
from slidesonnet.gui.launch import (
    app_invocation,
    browser_invocation,
    is_wsl,
    launch_browser,
)
from slidesonnet.gui.state import EditorState, cue_start
from slidesonnet.narration import transitions as trans
from slidesonnet.narration.model import Deck, Pace, Segment, Transition
from slidesonnet.pdf.reader import page_aspect

logger = logging.getLogger(__name__)

_MEDIA_URL = "/ssmedia"
_served: set[str] = set()


_STAGE_RESERVE = 680.0  # stage minimum (620px content) + its padding + separators
_STRIP_MAX = 400.0
_CONSOLE_MAX = 520.0


def clamp_panel_widths(
    window_px: float, strip: float, console: float, *, reserve: float = _STAGE_RESERVE
) -> tuple[float, float]:
    """Shrink pane widths (console first, then filmstrip) until the stage keeps *reserve* px."""
    avail = max(0.0, window_px - reserve)
    console = max(0.0, min(console, avail - strip))
    strip = max(0.0, min(strip, avail - console))
    return strip, console


class ResponsivePanes:
    """Auto-collapse side panes below a window-width breakpoint, restore above it.

    Only panes that the breakpoint itself collapsed are restored on widening —
    a pane the user closed while wide stays closed, and a pane the user
    reopened while narrow stays open.
    """

    def __init__(self, breakpoint_px: float = 1100.0) -> None:
        self.breakpoint_px = breakpoint_px
        self.narrow = False
        self._auto: set[str] = set()

    def update(self, width: float, open_panes: dict[str, bool]) -> tuple[set[str], set[str]]:
        """Return ``(panes to collapse, panes to restore)`` for the new *width*."""
        narrow = width < self.breakpoint_px
        if narrow == self.narrow:
            return set(), set()
        self.narrow = narrow
        if narrow:
            self._auto = {k for k, is_open in open_panes.items() if is_open}
            return set(self._auto), set()
        restore = {k for k in self._auto if not open_panes.get(k, False)}
        self._auto = set()
        return set(), restore


class PlaybackController:
    """Defined behaviors for the preview player (one transport, no extra widgets).

    - The play buttons toggle: pressed for the loaded track they pause/resume,
      pressed for anything else they build that track.
    - A play request supersedes whatever is rolling; the superseded track
      never starts (or stops) playing.
    - Stop cancels a play request even while its track is still being built,
      and resets the player (the next press rebuilds).
    - A single-slide track belongs to its slide: navigating away clears the
      player. The deck track spans every slide: navigating seeks it, playing
      or paused.
    """

    def __init__(self) -> None:
        self._generation = 0
        self.playing = False
        self.loaded_key: str | None = None  # "deck" or a slide id
        self._pending_deck: bool | None = None  # a build is in flight (deck or single)

    def begin(self, *, deck: bool) -> int:
        """Register a new play request; returns its token."""
        self._generation += 1
        self._pending_deck = deck
        return self._generation

    def may_start(self, token: int) -> bool:
        """True if no stop/newer request arrived since *token* was issued."""
        return token == self._generation

    def mark_loaded(self, key: str) -> None:
        """The player now holds the track for *key* ("deck" or a slide id)."""
        self.loaded_key = key
        self._pending_deck = None

    def unload(self) -> None:
        self.loaded_key = None
        self.playing = False
        self._pending_deck = None

    def stop(self) -> None:
        self._generation += 1
        self.unload()

    def set_playing(self, value: bool) -> None:
        self.playing = value

    def press_action(self, key: str) -> Literal["build", "pause", "resume"]:
        """What a play-button press for *key* should do right now."""
        if self.loaded_key != key:
            return "build"
        return "pause" if self.playing else "resume"

    def nav_action(self) -> Literal["seek", "clear", "none"]:
        """What slide navigation should do to the player right now."""
        if self.loaded_key == "deck" or self._pending_deck is True:
            return "seek"
        if self.loaded_key is not None or self._pending_deck is False:
            return "clear"  # a single-slide track (even mid-build) belongs to its slide
        return "none"


def nav_direction(key: Any) -> int:
    """Slide-navigation delta for an arrow key: ←/↑ previous, →/↓ next, else 0.

    Both pairs navigate: ↑/↓ matches the vertical filmstrip, ←/→ matches
    presentation order (and presenters' muscle memory).
    """
    if key.arrow_left or key.arrow_up:
        return -1
    if key.arrow_right or key.arrow_down:
        return 1
    return 0


def toggled_width(current: float, remembered: float, *, default: float) -> tuple[float, float]:
    """Next ``(width, remembered)`` for a collapse toggle on a px-unit splitter pane.

    Collapsing an open pane remembers its width; expanding restores the
    remembered width, falling back to *default* when none was remembered.
    """
    if current > 2.0:
        return 0.0, current
    return (remembered if remembered > 2.0 else default), remembered


def _media_url(state: EditorState, path: Path, *, cache_bust: bool = False) -> str:
    """URL for a render artifact under the deck's media dir.

    Page images are re-rasterized to the same ``page-N.png`` paths on every
    recompile, so without a version query the browser serves the stale cached
    image (you'd still see a dropped/old slide). ``cache_bust`` appends a
    ``(mtime, size)`` stamp so a re-render changes the URL and forces a refetch.
    """
    rel = path.resolve().relative_to(render_dir(state.pdf_path).resolve())
    url = f"{_MEDIA_URL}/{rel.as_posix()}"
    if cache_bust:
        try:
            st = path.stat()
            url = f"{url}?v={st.st_mtime_ns}-{st.st_size}"
        except OSError:
            pass
    return url


def _morph_schedule(
    cues: Sequence[Cue],
    deck: Deck,
    images: Sequence[Path],
    media_url: Callable[[Path], str],
) -> list[dict[str, Any]]:
    """Per-boundary morph steps for the preview's transition overlay.

    Mirrors the export's absorb-into-hold model: each animated boundary's morph
    *completes* at the next slide's cue start (``at``), running ``dur`` seconds
    of the outgoing slide's trailing hold — so the preview's transition lands at
    the same instant the cue flips, just as the rendered wipe does. Plain cuts
    emit nothing. Returns JSON-able dicts the client-side engine plays against
    the audio clock.
    """
    steps: list[dict[str, Any]] = []
    index = {sid: i for i, sid in enumerate(deck.pages)}
    for i in range(len(cues) - 1):
        a_start, a_sid = cues[i]
        b_start, b_sid = cues[i + 1]
        tr = boundary_transition(deck.page_narration(a_sid), deck.page_narration(b_sid))
        if not tr.is_animated:
            continue
        ia, ib = index.get(a_sid), index.get(b_sid)
        if ia is None or ib is None or ia >= len(images) or ib >= len(images):
            continue  # filmstrip not rasterized (no pdftoppm) — fall back to a flip
        span = b_start - a_start
        steps.append(
            {
                "at": b_start,
                "dur": max(0.05, min(tr.seconds, span)),
                "kind": tr.kind,
                "from": media_url(images[ia]),
                "to": media_url(images[ib]),
            }
        )
    return steps


def _serve_media(state: EditorState) -> None:
    rdir = render_dir(state.pdf_path)
    (rdir / "pages").mkdir(parents=True, exist_ok=True)
    key = str(rdir)
    if key in _served:
        return
    app.add_media_files(_MEDIA_URL, rdir)
    _served.add(key)


# look & feel lives in gui/static/ (editor.css, fonts.html, resize.html),
# inlined into the page head once per editor build
_STATIC_DIR = Path(__file__).parent / "static"
_HEAD_CSS = (_STATIC_DIR / "editor.css").read_text(encoding="utf-8")
_HEAD_FONTS = (_STATIC_DIR / "fonts.html").read_text(encoding="utf-8")
_HEAD_RESIZE = (_STATIC_DIR / "resize.html").read_text(encoding="utf-8")
_HEAD_MORPH = (_STATIC_DIR / "morph.html").read_text(encoding="utf-8")


_ALL_DOTS = "ss-dot-error ss-dot-warning ss-dot-ready ss-dot-empty"
_FLASH_COLORS = "ss-flash-ok ss-flash-info ss-flash-warn ss-flash-err"

# Auto-build waits this long after the last edit before generating a slide's
# audio, so we synthesize once the text is stable — not on every keystroke-blur.
AUTO_BUILD_DEBOUNCE_S = 2.5


def _pace_value(v: str | None) -> Pace | None:
    return None if v in (None, "", "normal") else v  # type: ignore[return-value]


class PaneLayout:
    """Collapsible side panes: toggles, drag limits, narrow-window overlay mode.

    The stage keeps its minimum width by capping the splitters' drag limits;
    below the breakpoint, panes auto-collapse and reopened ones float over the
    stage instead of squeezing it.
    """

    def __init__(
        self, strip_split: Any, console_split: Any, strip_toggle: Any, console_toggle: Any
    ) -> None:
        self.strip_split = strip_split
        self.console_split = console_split
        self.strip_toggle = strip_toggle
        self.console_toggle = console_toggle
        self.remembered = {"strip": 0.0, "console": 0.0}
        self.responsive = ResponsivePanes()
        self.panes: dict[str, tuple[Any, float, str]] = {
            "strip": (strip_split, 150.0, "ss-overlay-left"),
            "console": (console_split, 264.0, "ss-overlay-right"),
        }
        self.window_px = 0.0

    def sync_toggles(self) -> None:
        for splitter, btn in (
            (self.strip_split, self.strip_toggle),
            (self.console_split, self.console_toggle),
        ):
            is_open = float(splitter.value or 0.0) > 2.0
            btn.props(f"color={'primary' if is_open else 'grey-7'}")

    def toggle(self, key: str) -> None:
        splitter, default, _cls = self.panes[key]
        width, self.remembered[key] = toggled_width(
            float(splitter.value or 0.0), self.remembered[key], default=default
        )
        splitter.value = width
        self.sync_toggles()

    def _set_pane(self, key: str, *, open_pane: bool) -> None:
        splitter, default, _cls = self.panes[key]
        current = float(splitter.value or 0.0)
        if open_pane and current <= 2.0:
            splitter.value = self.remembered[key] if self.remembered[key] > 2.0 else default
        elif not open_pane and current > 2.0:
            self.remembered[key] = current
            splitter.value = 0.0

    def apply_limits(self) -> None:
        """Cap drag limits so panes can't push the stage below its minimum."""
        width = self.window_px
        if not width:
            return
        if self.responsive.narrow:  # overlay mode: panes float over the stage, no cap needed
            self.strip_split.props(f"limits=[0,{_STRIP_MAX:.0f}]")
            self.console_split.props(f"limits=[0,{_CONSOLE_MAX:.0f}]")
            return
        avail = max(0.0, width - _STAGE_RESERVE)
        strip_w = float(self.strip_split.value or 0.0)
        console_w = float(self.console_split.value or 0.0)
        self.strip_split.props(f"limits=[0,{min(_STRIP_MAX, max(0.0, avail - console_w)):.0f}]")
        self.console_split.props(f"limits=[0,{min(_CONSOLE_MAX, max(0.0, avail - strip_w)):.0f}]")

    def on_resize(self, e: Any) -> None:
        width = float(e.args)
        self.window_px = width
        open_now = {k: float(s.value or 0.0) > 2.0 for k, (s, _d, _c) in self.panes.items()}
        to_collapse, to_restore = self.responsive.update(width, open_now)
        for key in to_collapse:
            self._set_pane(key, open_pane=False)
        for key in to_restore:
            self._set_pane(key, open_pane=True)
        if not self.responsive.narrow:  # stretched panes yield before the stage shrinks
            strip_w, console_w = clamp_panel_widths(
                width,
                float(self.strip_split.value or 0.0),
                float(self.console_split.value or 0.0),
            )
            self.strip_split.value = strip_w
            self.console_split.value = console_w
        for _key, (splitter, _d, cls) in self.panes.items():
            if self.responsive.narrow:
                splitter.classes(add=cls)
            else:
                splitter.classes(remove=cls)
        self.apply_limits()
        self.sync_toggles()

    def on_drag(self) -> None:
        self.apply_limits()
        self.sync_toggles()


class PreviewPlayer:
    """The preview transport: build/pause/resume/stop, clock, seek, cue flips."""

    def __init__(
        self,
        view: EditorView,
        *,
        audio: Any,
        pos_slider: Any,
        time_label: Any,
        play_one: Any,
        play_all: Any,
    ) -> None:
        self.view = view
        self.audio = audio
        self.pos_slider = pos_slider
        self.time_label = time_label
        self.play_one = play_one
        self.play_all = play_all
        self.playback = PlaybackController()
        self.cues: list[Cue] = []
        self.track_duration = 0.0
        self.scrubbing = False  # user is dragging the seek handle; don't fight them

    @staticmethod
    def _fmt_clock(t: float) -> str:
        s = max(0, int(t))
        return f"{s // 60}:{s % 60:02d}"

    def _sync_clock(self, t: float) -> None:
        if self.track_duration <= 0:
            return
        if not self.scrubbing:
            self.pos_slider.value = min(1.0, t / self.track_duration)
        self.time_label.set_text(f"{self._fmt_clock(t)} / {self._fmt_clock(self.track_duration)}")

    def _run_js(self, script: str) -> None:
        try:  # no JS client under the in-process test sim
            ui.run_javascript(script)
        except Exception:
            pass

    def _arm_morph(self, whole_deck: bool) -> None:
        """Push the boundary-transition schedule to the client morph engine."""
        if not whole_deck or not self.cues:
            self._run_js("window.ssMorph && window.ssMorph.stop()")
            return
        state = self.view.state
        try:
            images = state.ensure_images()
        except Exception:
            images = []
        steps = _morph_schedule(
            self.cues, state.deck, images, lambda p: _media_url(state, p, cache_bust=True)
        )
        cfg = {
            "audioId": f"c{self.audio.id}",
            "stageId": f"c{self.view.stage_view.id}",
            "steps": steps,
        }
        self._run_js(f"window.ssMorph && window.ssMorph.start({json.dumps(cfg)})")

    def stop_playback(self) -> None:
        self.playback.stop()  # cancels a pending play too — Stop always wins
        self.audio.pause()
        self._run_js("window.ssMorph && window.ssMorph.stop()")
        self.cues = []
        self.track_duration = 0.0
        self.pos_slider.value = 0.0
        self.pos_slider.props("disable")
        self.time_label.set_text("")
        self.sync_transport()

    def request_preview(self, btn: Any, whole_deck: bool) -> None:
        """Claim the player synchronously at click time, then build off the loop.

        Claiming the token here (not inside the task) means a Stop click that
        lands before the build even starts still cancels it.
        """
        view = self.view
        state = view.state
        if not whole_deck and not state.current_block.has_speech:
            view.flash("This slide has no narration to play", "info")
            return
        key = "deck" if whole_deck else state.current_id
        action = self.playback.press_action(key)
        if action == "pause":
            self.audio.pause()
            self.playback.set_playing(False)  # optimistic; the browser event confirms
            self.sync_transport()
            return
        if action == "resume":
            self.audio.play()
            self.playback.set_playing(True)
            self.sync_transport()
            return
        if view.busy:
            return
        view.busy = True
        token = self.playback.begin(deck=whole_deck)
        self.audio.pause()  # a rolling preview yields to the new request right away
        self.playback.set_playing(False)
        self.sync_transport()
        background_tasks.create(self._preview(btn, whole_deck, token))

    async def _preview(self, btn: Any, whole_deck: bool, token: int) -> None:
        view = self.view
        state = view.state
        client = view.client  # background tasks must re-enter the page's slot stack
        with client:
            view.blocks.save_current()
            btn.props("loading")
        try:
            if state.tts_is_paid:
                count = (
                    state.uncached_total() if whole_deck else state.uncached_count(state.current_id)
                )
                with client:
                    if count and not await view.confirm_paid_synth(count):
                        return
            # If the clips we need are already generating in the background, wait
            # for those jobs instead of racing or launching a duplicate synth.
            scope = None if whole_deck else state.current_id
            await view.jobs.await_targets(state.all_targets(only_id=scope))
            preview = await run.io_bound(
                state.preview_deck if whole_deck else state.preview_current
            )
            with client:
                if not self.playback.may_start(token):  # user pressed Stop while building
                    view.flash("Preview stopped", "info")
                    return
                self.cues = preview.cues if whole_deck else []
                self._arm_morph(whole_deck)
                # whole-deck playback starts where the user is, not back at slide 1:
                # seek to the current slide's cue (a #t= media fragment so the
                # browser starts there on load).
                start_at = (cue_start(self.cues, state.current_id) or 0.0) if whole_deck else 0.0
                # every preview renders to the same track path — vary the URL so
                # the browser refetches instead of replaying the previous audio
                src = f"{_media_url(state, preview.track)}?v={token}"
                if start_at > 0:
                    src = f"{src}#t={start_at}"
                self.audio.set_source(src)
                self.playback.mark_loaded("deck" if whole_deck else state.current_id)
                self.track_duration = preview.total_duration
                self.pos_slider.value = (
                    start_at / self.track_duration if self.track_duration else 0.0
                )
                self.pos_slider.props(remove="disable")
                self._sync_clock(start_at)
                self.audio.play()
                if start_at > 0:
                    self.audio.seek(start_at)  # belt-and-suspenders for browsers that ignore #t=
                self.playback.set_playing(True)  # optimistic; the browser event confirms
                self.sync_transport()
                view.flash(f"Preview ready ({preview.total_duration:.1f}s)", "positive")
        except Exception as exc:
            logger.exception("preview failed")
            with client:
                view.flash(f"Error: {exc}", "negative")
        finally:
            view.busy = False
            with client:
                btn.props(remove="loading")
                view.render()

    # clock/scrubber sync + cue-driven image flip during deck preview
    def on_timeupdate(self, e: Any) -> None:
        t = float(e.args) if e.args is not None else 0.0
        self._sync_clock(t)
        if not self.cues:
            return
        state = self.view.state
        current = self.cues[0][1]
        for start, sid in self.cues:
            if t + 1e-6 >= start:
                current = sid
            else:
                break
        if current in state.deck.pages:
            idx = state.deck.pages.index(current)
            if idx != state.index:
                if self.view.blocks.editing_active:
                    return  # mid-edit: defer following until the field blurs
                self.view.blocks.save_current()  # don't clobber narration typed during playback
                state.index = idx
                self.view.render()

    def on_player_state(self, playing: bool) -> None:
        self.playback.set_playing(playing)
        self.sync_transport()

    def on_scrub_pan(self, e: Any) -> None:
        self.scrubbing = e.args == "start"

    def on_scrub(self, e: Any) -> None:
        if self.track_duration > 0:
            self.audio.seek(float(e.args) * self.track_duration)

    def sync_transport(self) -> None:
        """Play buttons mirror the player: the loaded track's button shows pause.

        Play grays out when the slide has no speech.
        """
        state = self.view.state
        one_active = self.playback.playing and self.playback.loaded_key == state.current_id
        self.play_one.props(f"icon={'pause' if one_active else 'play_arrow'}")
        deck_active = self.playback.playing and self.playback.loaded_key == "deck"
        self.play_all.props(f"icon={'pause' if deck_active else 'playlist_play'}")
        self.play_one.set_enabled(state.current_block.has_speech)


class BlockEditor:
    """The structured per-slide editor: utterance/pause cards and transitions."""

    def __init__(self, view: EditorView, blocks_col: Any) -> None:
        self.view = view
        self.blocks_col = blocks_col
        # collectors for the structured block editor, refreshed by render()
        self.seg_collectors: list[Callable[[], Segment]] = []
        self.seg_gen_controls: list[tuple[Any, Any, int]] = []  # (button, tooltip, speech index)
        self.transition_getters: dict[str, Callable[[], Transition]] = {}
        # While a narration field holds keyboard focus, playback auto-advance must
        # not rebuild the block editor — that would destroy the field mid-typing
        # and lose everything typed after the rebuild. Tracked per focus/blur.
        self.editing_active = False
        # Which utterance is being edited right now (None = none/pause/transition),
        # so auto-build can skip the half-typed line the user is still in.
        self.focused_speech_index: int | None = None

    def _set_editing(self, active: bool, speech_index: int | None = None) -> None:
        self.editing_active = active
        self.focused_speech_index = speech_index if active else None

    def _track_editing(self, widget: Any, speech_index: int | None = None) -> None:
        widget.on("focus", lambda: self._set_editing(True, speech_index))
        widget.on("blur", lambda: self._set_editing(False, speech_index))

    def _transition_row(self, which: str, transition: Transition, disabled: bool) -> None:
        label = "Transition in" if which == "in" else "Transition out"
        family_key, direction = trans.decompose(transition.kind)
        type_options = {f.key: f.label for f in trans.FAMILIES}
        init_dirs = trans.directions_for(family_key) or trans.directions_for("wipe")
        with ui.row().classes("w-full items-center no-wrap gap-2 ss-transition"):
            ui.label(label).classes("ss-trans-label ss-mono")
            kind = (
                ui.select(type_options, value=family_key)
                .props("dense filled options-dense")
                .classes("ss-trans-type")
                .mark(f"trans-{which}")
            )
            dirs = (
                ui.select(init_dirs, value=direction or init_dirs[0])
                .props("dense filled options-dense")
                .classes("ss-trans-dir")
                .mark(f"trans-{which}-dir")
            )
            secs = (
                ui.number(value=transition.seconds or 0.5, min=0, step=0.1, format="%.1f")
                .props("dense filled")
                .classes("ss-trans-secs")
            )
            dirs.bind_visibility_from(
                kind, "value", backward=lambda k: bool(trans.directions_for(k))
            )
            secs.bind_visibility_from(kind, "value", backward=lambda k: k != "cut")
            if disabled:
                kind.disable()
                dirs.disable()
                secs.disable()

            def on_type_change() -> None:
                opts = trans.directions_for(kind.value or "cut")
                if opts:
                    keep = dirs.value if dirs.value in opts else opts[0]
                    dirs.set_options(opts, value=keep)
                self.commit_audible()

            kind.on_value_change(on_type_change)
            dirs.on_value_change(lambda: self.commit_audible())
            secs.on("blur", lambda: self.commit_audible())
            secs.on("keydown.ctrl.s.prevent", lambda: self.commit_audible())
            self._track_editing(secs)

        def collect() -> Transition:
            family: str = kind.value or "cut"
            direction_label = dirs.value if trans.directions_for(family) else None
            name = trans.compose(family, direction_label)
            seconds = float(secs.value or 0.0) if name != "cut" else 0.0
            return Transition(kind=name, seconds=seconds)

        self.transition_getters[which] = collect

    def _reorder_controls(self, index: int, disabled: bool) -> None:
        """Up/down reorder arrows — placed on the *left* of a card."""
        up = ui.button(icon="keyboard_arrow_up", on_click=lambda: self._move_segment(index, -1))
        up.props("flat round dense size=sm").mark(f"seg-up-{index}").tooltip("Move up")
        down = ui.button(icon="keyboard_arrow_down", on_click=lambda: self._move_segment(index, 1))
        down.props("flat round dense size=sm").mark(f"seg-down-{index}").tooltip("Move down")
        if disabled:
            up.disable()
            down.disable()

    def _delete_control(self, index: int, disabled: bool) -> None:
        """Destructive delete — placed on the *right*, far from the reorder arrows."""
        trash = ui.button(icon="delete", on_click=lambda: self._delete_segment(index))
        trash.props("flat round dense size=sm color=negative").mark(f"seg-del-{index}")
        trash.tooltip("Delete this block")
        if disabled:
            trash.disable()

    def _utterance_card(
        self, index: int, seg: Segment, disabled: bool, speech_index: int
    ) -> Callable[[], Segment]:
        view = self.view
        state = view.state
        with ui.card().classes("ss-card ss-utterance w-full").mark(f"utterance-{index}"):
            with ui.row().classes("w-full items-start no-wrap gap-1"):
                with ui.column().classes("gap-0 ss-seg-controls"):
                    self._reorder_controls(index, disabled)
                text = (
                    ui.textarea(value=seg.text, placeholder="Spoken words…")
                    .props("filled autogrow dense")
                    .classes("ss-mono ss-utext")
                    .mark(f"utext-{index}")
                )
                with ui.column().classes("gap-0 ss-seg-controls"):
                    self._delete_control(index, disabled)
                    # generate button doubles as the audio indicator: amber = no
                    # audio yet, green = generated (click again for a fresh take)
                    gen = ui.button(icon="graphic_eq")
                    gen.props("flat round dense size=sm color=warning").mark(f"gen-seg-{index}")
                    with gen:  # one tooltip, retext-ed as the state flips
                        gen_tip = ui.tooltip("No audio yet · click to generate")
                    if disabled:
                        gen.disable()
                    gen.on_click(lambda: view.enqueue_segment(speech_index))
                    self.seg_gen_controls.append((gen, gen_tip, speech_index))
            voice_choices = state.voice_options()
            if seg.voice and seg.voice not in voice_choices:
                voice_choices = [seg.voice, *voice_choices]  # keep an off-list value visible
            with ui.row().classes("ss-utt-opts w-full items-end gap-2 no-wrap"):
                voice = (
                    ui.select(
                        voice_choices,
                        value=seg.voice or None,
                        label="Voice",
                        with_input=True,  # type to filter the voice list
                    )
                    .props(
                        "filled dense options-dense clearable hide-bottom-space stack-label "
                        'title="Voice (type to filter; clear for the deck default)"'
                    )
                    .classes("ss-mono ss-uvoice")
                    .mark(f"uvoice-{index}")
                )
                fallback = state.default_voice()
                if fallback:  # an unset voice isn't "no voice" — show what will speak
                    voice.props(f'placeholder="{fallback} (default)"')
                pace = (
                    ui.select(["slow", "normal", "fast"], value=seg.pace or "normal", label="Pace")
                    .props("filled dense options-dense hide-bottom-space")
                    .classes("ss-upace")
                    .mark(f"upace-{index}")
                )
                direct = (
                    ui.input(
                        value=seg.direction or "",
                        label="Director's note",
                        placeholder="how to speak it (optional)",
                    )
                    .props("filled dense hide-bottom-space stack-label")
                    .classes("ss-udirect")
                    .mark(f"udirect-{index}")
                )
            for w in (text, voice, pace, direct):
                if disabled:
                    w.disable()
            # text and director's note both change what gets spoken, so a loaded
            # preview track is stale the moment they differ — commit_audible drops
            # it so the next Play rebuilds instead of replaying the old narration.
            text.on("blur", lambda: self.commit_audible())
            text.on("keydown.ctrl.s.prevent", lambda: self.commit_audible())  # save w/o leaving
            voice.on_value_change(lambda: self.commit_audible())
            pace.on_value_change(lambda: self.commit_audible())
            direct.on("blur", lambda: self.commit_audible())
            direct.on("keydown.ctrl.s.prevent", lambda: self.commit_audible())
            for w in (text, voice, direct):  # keystroke-holding fields
                self._track_editing(w, speech_index)

        def collect() -> Segment:
            return Segment.speech(
                text.value or "",
                voice=(voice.value or "").strip() or None,
                pace=_pace_value(pace.value),
                direction=(direct.value or "").strip() or None,
            )

        return collect

    def _pause_card(self, index: int, seg: Segment, disabled: bool) -> Callable[[], Segment]:
        with ui.card().classes("ss-card ss-pause w-full").mark(f"pause-{index}"):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                with ui.row().classes("gap-0 no-wrap ss-seg-controls"):
                    self._reorder_controls(index, disabled)
                ui.icon("hourglass_empty").classes("ss-pause-icon")
                secs = (
                    ui.number(value=seg.seconds, min=0, step=0.1, format="%.1f", suffix="s")
                    .props("filled dense")
                    .classes("ss-pause-secs")
                    .mark(f"pause-secs-{index}")
                )
                ui.label("silence").classes("ss-diag ss-diag-info")
                ui.space()
                self._delete_control(index, disabled)
            if disabled:
                secs.disable()
            secs.on("blur", lambda: self.commit_audible())
            secs.on("keydown.ctrl.s.prevent", lambda: self.commit_audible())
            self._track_editing(secs)

        def collect() -> Segment:
            return Segment.pause(max(0.0, float(secs.value or 0.0)))

        return collect

    def render(self) -> None:
        self.editing_active = False  # the rebuild destroys any focused field
        self.focused_speech_index = None
        state = self.view.state
        self.blocks_col.clear()
        self.seg_collectors.clear()
        self.seg_gen_controls.clear()
        self.transition_getters.clear()
        block = state.current_block
        disabled = not state.current_id
        with self.blocks_col:
            if not state.current_id:
                ui.label(
                    "This page has no slide-id — add \\ssid in the source to narrate it."
                ).classes("ss-diag ss-diag-warn")
                return
            self._transition_row("in", block.transition_in, disabled)
            speech_i = 0
            for i, seg in enumerate(block.segments):
                if seg.is_speech:
                    self.seg_collectors.append(self._utterance_card(i, seg, disabled, speech_i))
                    speech_i += 1
                else:
                    self.seg_collectors.append(self._pause_card(i, seg, disabled))
            if not block.segments:
                ui.label("(empty — add a line or a pause above)").classes("ss-diag ss-diag-info")
            self._transition_row("out", block.transition_out, disabled)
        self.sync_gen_buttons()

    def collect(self) -> tuple[list[Segment], Transition, Transition]:
        segs = [c() for c in self.seg_collectors]
        getters = self.transition_getters
        tin = getters["in"]() if "in" in getters else Transition()
        tout = getters["out"]() if "out" in getters else Transition()
        return segs, tin, tout

    def _apply_structure(self, segs: list[Segment], tin: Transition, tout: Transition) -> None:
        """Commit an add/delete/move — the loaded track no longer matches the deck."""
        if self.view.state.replace_block(segs, transition_in=tin, transition_out=tout):
            self.view.player.stop_playback()
            self.view.render()

    def add_segment(self, kind: str) -> None:
        segs, tin, tout = self.collect()
        segs.append(Segment.speech("") if kind == "speech" else Segment.pause(1.0))
        self._apply_structure(segs, tin, tout)

    def _delete_segment(self, index: int) -> None:
        segs, tin, tout = self.collect()
        if 0 <= index < len(segs):
            del segs[index]
        self._apply_structure(segs, tin, tout)

    def _move_segment(self, index: int, delta: int) -> None:
        segs, tin, tout = self.collect()
        j = index + delta
        if 0 <= index < len(segs) and 0 <= j < len(segs):
            segs[index], segs[j] = segs[j], segs[index]
            self._apply_structure(segs, tin, tout)

    def save_current(self) -> bool:
        """Flush the open editor widgets to disk without rebuilding the cards."""
        if not self.seg_collectors and "in" not in self.transition_getters:
            return False  # nothing built (e.g. unmarked page)
        segs, tin, tout = self.collect()
        slide_id = self.view.state.current_id
        changed = self.view.state.replace_block(segs, transition_in=tin, transition_out=tout)
        if changed:
            self.view.show_saved_flash()
            self.view.render_side()
            self.view.schedule_auto_build(slide_id)
        return changed

    def commit(self) -> None:
        self.save_current()

    def commit_audible(self) -> None:
        """Commit a knob that changes what plays (pause length, voice, pace,
        transition): once the block differs, a loaded track is stale."""
        if self.save_current():
            self.view.player.stop_playback()

    def sync_gen_buttons(self) -> None:
        """Each utterance's generate button doubles as its audio indicator:
        amber wave = no audio yet, green refresh = generated (fresh take), and a
        spinner while a background job for that clip is queued or running."""
        if not self.seg_gen_controls:
            return
        view = self.view
        state = view.state
        flags = state.speech_cached_flags()
        speeches = state.current_block.speech_segments
        for btn, tip, si in self.seg_gen_controls:
            handle = view.jobs.handle_for(state.current_id, si)
            if handle is not None and handle.status in ("queued", "running"):
                btn.props("loading color=primary")
                tip.set_text("Generating…")
                btn.set_enabled(False)
                continue
            btn.props(remove="loading")
            cached = si < len(flags) and flags[si]
            btn.props(
                f"icon={'autorenew' if cached else 'graphic_eq'} "
                f"color={'positive' if cached else 'warning'}"
            )
            tip.set_text(
                "Generated · click for a fresh take"
                if cached
                else "No audio yet · click to generate"
            )
            btn.set_enabled(si < len(speeches) and bool(speeches[si].text.strip()))


class OrphanTray:
    """Narration whose slide vanished in a recompile: keep it visible and actionable."""

    def __init__(self, view: EditorView, tray_box: Any) -> None:
        self.view = view
        self.tray_box = tray_box

    def render(self) -> None:
        state = self.view.state
        self.tray_box.clear()
        orphans = state.orphan_blocks()
        self.tray_box.visible = bool(orphans)
        if not orphans:
            return
        with self.tray_box, ui.column().classes("ss-tray w-full gap-2 no-wrap"):
            with ui.row().classes("w-full items-center no-wrap gap-1"):
                ui.icon("link_off").classes("ss-tray-icon")
                ui.label("Unattached narration").classes("ss-tray-title")
            ui.label("these slides are gone — fold the text into a slide or keep it here").classes(
                "ss-tray-hint"
            )
            for block in orphans:
                full = block.speech_text or "(pauses only)"
                with ui.column().classes("w-full gap-1 ss-orphan no-wrap"):
                    with ui.row().classes("w-full items-center no-wrap gap-1"):
                        ui.label(f"@{block.slide_id}").classes("ss-mono ss-orphan-id")
                        ui.space()
                        copy = ui.button(icon="content_copy").props("flat round dense size=sm")
                        copy.mark(f"copy-{block.slide_id}").tooltip("Copy the text")
                        copy.on_click(lambda text=full: self._copy_text(text))
                        trash = ui.button(icon="delete").props("flat round dense size=sm")
                        trash.mark(f"delete-{block.slide_id}").tooltip("Delete this narration")
                        trash.on_click(lambda sid=block.slide_id: self._delete_orphan_dialog(sid))
                    # full text, selectable so it can always be copied by hand
                    ui.label(full).classes("ss-orphan-text").mark(f"orphan-text-{block.slide_id}")
                    with ui.row().classes("w-full items-center no-wrap gap-1"):
                        here = ui.button(
                            "Append here",
                            icon="south",
                            on_click=lambda sid=block.slide_id: self._append_orphan_here(sid),
                        ).props("flat dense no-caps size=sm")
                        here.mark(f"append-{block.slide_id}")
                        here.set_enabled(bool(state.current_id))
                        here.tooltip(
                            f"Append to this slide (@{state.current_id})"
                            if state.current_id
                            else "Open a slide with an id first"
                        )
                        attach = ui.button("Attach to…", icon="move_down").props(
                            "flat dense no-caps size=sm"
                        )
                        attach.mark(f"attach-{block.slide_id}").tooltip("Move onto an empty slide")
                        attach.on_click(lambda sid=block.slide_id: self._attach_orphan_dialog(sid))

    def _copy_text(self, text: str) -> None:
        ui.clipboard.write(text)
        self.view.flash("Copied narration text", "info")

    def _append_orphan_here(self, orphan_id: str) -> None:
        view = self.view
        target = view.state.current_id
        try:
            view.state.append_orphan_to_current(orphan_id)
        except ValueError as exc:
            view.flash(str(exc), "warning")
            return
        view.flash(f"Appended '@{orphan_id}' to '{target}'", "positive")
        view.render()

    def _attach_orphan_dialog(self, orphan_id: str) -> None:
        view = self.view
        candidates = view.state.unnarrated_pages()
        if not candidates:
            view.flash("No un-narrated slide to attach to", "warning")
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Attach narration '@{orphan_id}' to which slide?")
            target = ui.select(candidates, value=candidates[0]).classes("w-full")
            target.mark("attach-target")

            def _do_attach() -> None:
                dialog.close()
                try:
                    view.state.attach_orphan(orphan_id, str(target.value))
                except ValueError as exc:
                    view.flash(str(exc), "warning")
                    return
                view.flash(f"Narration attached to '{target.value}'", "positive")
                view.render()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Attach", on_click=_do_attach).props("no-caps").mark("attach-confirm")
        dialog.open()

    def _delete_orphan_dialog(self, orphan_id: str) -> None:
        view = self.view
        with ui.dialog() as dialog, ui.card():
            ui.label(
                f"Delete the unattached narration '@{orphan_id}'? "
                "This removes its text from the sidecar."
            )

            def _do_delete() -> None:
                dialog.close()
                try:
                    view.state.delete_orphan(orphan_id)
                except ValueError as exc:
                    view.flash(str(exc), "warning")
                    return
                view.flash(f"Deleted narration '@{orphan_id}'", "info")
                view.render()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                delete_btn = ui.button("Delete", on_click=_do_delete).props(
                    "no-caps color=negative"
                )
                delete_btn.mark("delete-confirm")
        dialog.open()


class EditorView:
    """The editor page: builds the widget tree and owns the cross-cutting bits.

    Component seams: :class:`PaneLayout` (side panes), :class:`PreviewPlayer`
    (transport), :class:`BlockEditor` (narration cards), :class:`OrphanTray`
    (unattached narration). The view itself keeps the shared services they
    coordinate through: the single busy flag, the footer flash, the filmstrip,
    navigation, and the one-at-a-time action runner.
    """

    # the components and the page client, attached by build()
    blocks: BlockEditor
    tray: OrphanTray
    player: PreviewPlayer
    layout: PaneLayout
    client: Any
    jobs: JobQueue

    def __init__(self, state: EditorState) -> None:
        self.state = state
        self.busy = False  # one action (synth/export/preview build) at a time
        self._flash_token = 0  # keeps an old fade timer from wiping a newer message
        self.thumb_cards: list[tuple[Any, Any, Any]] = []  # (card, dot, audio-missing badge)
        self._auto_build_timers: dict[str, Any] = {}  # per-slide debounce timers

    def build(self) -> None:
        """Build the widget tree, attach the components, and wire all events."""
        state = self.state
        ui.dark_mode().enable()
        ui.colors(
            primary="#5db3f0",
            positive="#2e7d4f",
            negative="#c0443c",
            warning="#a8772a",
            dark="#151a22",
            dark_page="#0e1116",
        )
        try:
            aspect = page_aspect(state.pdf_path)
        except Exception:  # never let a malformed page block the editor
            aspect = 16 / 9
        ar_css = f":root{{--ss-ar:{aspect:.4f}}}"
        ui.add_head_html(
            _HEAD_FONTS + "<style>" + _HEAD_CSS + ar_css + "</style>" + _HEAD_RESIZE + _HEAD_MORPH
        )

        # --- header: wordmark · deck · save flash · error pill ---
        with ui.header().classes("ss-header items-center justify-between no-wrap"):
            with ui.row().classes("items-center gap-3 no-wrap"):
                ui.html(
                    '<span class="ss-wordmark">slide<span class="ss-accent">Sonnet</span></span>'
                )
                ui.label(state.pdf_path.name).classes("ss-chip ss-mono")
            with ui.row().classes("items-center gap-3 no-wrap"):
                self.saved_flash = ui.label("● saved").classes("ss-saved opacity-0")
                self.err_badge = ui.label().classes("ss-pill")
                # material's view_sidebar glyph puts the sidebar on the RIGHT; flip for the left
                strip_toggle = ui.button(icon="view_sidebar").props("flat round dense")
                strip_toggle.classes("ss-flip").mark("toggle-strip").tooltip("Show/hide filmstrip")
                console_toggle = ui.button(icon="view_sidebar").props("flat round dense")
                console_toggle.mark("toggle-console").tooltip("Show/hide console")

        # --- body: filmstrip | stage | console — draggable, collapsible panes ---
        strip_split = (
            ui.splitter(value=150, limits=(0, 400))
            .props("unit=px")
            .classes("ss-main w-full ss-split")
        )
        strip_split.mark("split-strip")
        with strip_split.separator:
            ui.icon("drag_indicator").classes("ss-grip")

        with strip_split.before, ui.column().classes("ss-side no-wrap gap-0"):
            with ui.row().classes("ss-side-head w-full items-center justify-between no-wrap"):
                ui.label("Slides").classes("ss-section")
                collapse_strip = ui.button(icon="chevron_left").props("flat round dense size=sm")
                collapse_strip.mark("collapse-strip").tooltip("Collapse filmstrip")
            self.strip_col = ui.column().classes("ss-strip gap-2")

        self.build_strip()

        with strip_split.after:
            console_split = (
                ui.splitter(value=264, limits=(0, 520))
                .props("unit=px reverse")
                .classes("h-full w-full ss-split")
            )
            console_split.mark("split-console")
            with console_split.separator:
                ui.icon("drag_indicator").classes("ss-grip")

            with console_split.before, ui.column().classes("ss-stage no-wrap gap-0"):
                with ui.column().classes("ss-stage-inner gap-3 no-wrap"):
                    # slide above, narration cards below — the divider apportions the
                    # stage between them, like the side panes do horizontally
                    stage_split = ui.splitter(horizontal=True, value=58, limits=(20, 85)).classes(
                        "ss-stage-split"
                    )
                    stage_split.mark("split-stage")
                    with stage_split.separator:
                        ui.icon("drag_indicator").classes("ss-grip ss-grip-h")
                    with (
                        stage_split.before,
                        ui.element("div").classes("ss-stage-view") as stage_view,
                    ):
                        self.stage_view = stage_view
                        self.slide_img = (
                            ui.image()
                            .classes("ss-stage-img")
                            .props('fit="contain" no-spinner')
                            .mark("stage-img")
                        )
                    with (
                        stage_split.after,
                        ui.column().classes("ss-edit-pane no-wrap gap-2 w-full"),
                    ):
                        with ui.row().classes("w-full items-center no-wrap gap-3"):
                            self.id_label = ui.label().classes("ss-id ss-mono")
                            ui.space()
                            self.add_line_btn = ui.button(
                                "Line",
                                icon="add",
                                on_click=lambda: self.blocks.add_segment("speech"),
                            )
                            self.add_line_btn.props("flat dense no-caps").mark("add-utterance")
                            self.add_line_btn.tooltip("Add a spoken line")
                            self.add_pause_btn = ui.button(
                                "Pause",
                                icon="hourglass_empty",
                                on_click=lambda: self.blocks.add_segment("pause"),
                            )
                            self.add_pause_btn.props("flat dense no-caps").mark("add-pause")
                            self.add_pause_btn.tooltip("Add a silent pause")
                        blocks_col = ui.column().classes("ss-blocks no-wrap gap-2 w-full")
                    with ui.row().classes("w-full items-center no-wrap gap-1"):
                        prev_btn = ui.button(icon="chevron_left").props("flat round dense")
                        prev_btn.mark("Previous").tooltip("Back (←)")
                        self.page_label = ui.label().classes("ss-counter ss-mono")
                        next_btn = ui.button(icon="chevron_right").props("flat round dense")
                        next_btn.mark("Next").tooltip("Forward (→)")
                        ui.element("div").classes("ss-vsep")
                        play_one = ui.button(icon="play_arrow").props("flat round dense")
                        play_one.mark("play-slide").tooltip("Hear this slide")
                        play_all = ui.button(icon="playlist_play").props("flat round dense")
                        play_all.mark("play-deck").tooltip("Preview whole deck")
                        stop_btn = ui.button(icon="stop").props("flat round dense")
                        stop_btn.mark("stop").tooltip("Stop preview")
                        ui.element("div").classes("ss-vsep")
                        audio = ui.audio("").classes("ss-audio")
                        audio.mark("preview-audio")
                        pos_slider = (
                            ui.slider(min=0.0, max=1.0, step=0.001, value=0.0)
                            .props("dense disable")
                            .classes("ss-seek")
                        )
                        pos_slider.mark("seek")
                        time_label = ui.label("").classes("ss-mono ss-time")

            with console_split.after, ui.column().classes("ss-console gap-3 no-wrap"):
                with ui.row().classes("w-full items-center justify-between no-wrap"):
                    ui.label("Checks · this slide").classes("ss-section")
                    collapse_console = ui.button(icon="chevron_right").props(
                        "flat round dense size=sm"
                    )
                    collapse_console.mark("collapse-console").tooltip("Collapse console")
                self.diag_box = ui.column().classes("w-full gap-1")
                ui.label("Audio · this slide").classes("ss-section")
                self.audio_status = ui.label().classes("ss-diag ss-diag-info")
                tray_box = ui.column().classes("w-full gap-1")
                tray_box.mark("orphan-tray")
                tray_box.visible = False
                ui.space()
                auto_build = ui.checkbox("Auto-generate as I edit").classes("ss-autobuild")
                auto_build.props("dense").mark("auto-build")
                auto_build.bind_value(app.storage.general, "auto_build")
                if state.tts_is_paid:
                    auto_build.set_value(False)
                    auto_build.disable()
                    auto_build.tooltip(
                        "Local (Kokoro) voices only — a paid engine would bill on every save"
                    )
                else:
                    auto_build.tooltip(
                        "Quietly generate each slide's audio in the background after you edit it"
                    )
                auto_build.on_value_change(lambda e: self._on_auto_build_toggle(bool(e.value)))
                self.gen_all_btn = ui.button("Generate missing", icon="library_music").classes(
                    "w-full"
                )
                self.gen_all_btn.props("flat no-caps").mark("gen-missing")
                self.gen_all_btn.tooltip(
                    "Makes only the clips that don't exist yet — finished audio is left untouched"
                )
                export_btn = ui.button("Export video", icon="movie").classes("w-full ss-export")
                export_btn.props("unelevated no-caps color=primary")

        # --- footer: engine · sidecar · status flash · hints ---
        with ui.footer().classes("ss-footer no-wrap"):
            ui.label(f"engine {state.config.tts.backend}").classes("ss-mono ss-foot")
            ui.element("div").classes("ss-vsep")
            ui.label(state.sidecar_path.name).classes("ss-mono ss-foot")
            ui.space()
            self.flash_label = ui.label("").classes("ss-mono ss-flash")
            self.flash_label.mark("flash")
            ui.space()
            ui.label(
                "←→ or ↑↓ slides · drag dividers · saves automatically · Ctrl+S saves now"
            ).classes("ss-mono ss-foot")

        # --- components -----------------------------------------------------
        self.blocks = BlockEditor(self, blocks_col)
        self.tray = OrphanTray(self, tray_box)
        self.player = PreviewPlayer(
            self,
            audio=audio,
            pos_slider=pos_slider,
            time_label=time_label,
            play_one=play_one,
            play_all=play_all,
        )
        self.layout = PaneLayout(strip_split, console_split, strip_toggle, console_toggle)
        self.client = ui.context.client  # background tasks must re-enter the page's slot stack

        # background generation: keep the editor live while clips render
        self.jobs = JobQueue(
            deck_provider=lambda: (state.deck, state.config, audio_dir(state.pdf_path)),
            synth=lambda targets, force: state.synth_targets(targets, force=force),
            is_paid=lambda: state.tts_is_paid,
            on_change=self._on_jobs_changed,
        )
        self.jobs.start()
        self.client.on_disconnect(self.jobs.stop)

        # --- event wiring -----------------------------------------------------
        # NiceGUI's `args` filter only reaches top-level event keys, so a real
        # browser can't deliver `event.target.currentTime` that way (the handler
        # would receive an empty dict). Transform client-side and emit the number.
        audio.on(
            "timeupdate", self.player.on_timeupdate, js_handler="(e) => emit(e.target.currentTime)"
        )
        audio.on("play", lambda: self.player.on_player_state(True))
        audio.on("pause", lambda: self.player.on_player_state(False))
        audio.on("ended", lambda: self.player.on_player_state(False))
        pos_slider.on("pan", self.player.on_scrub_pan)
        pos_slider.on("change", self.player.on_scrub)  # fires on release: one seek per scrub
        prev_btn.on_click(lambda: self.go(-1))
        next_btn.on_click(lambda: self.go(1))
        play_one.on_click(lambda: self.player.request_preview(play_one, False))
        play_all.on_click(lambda: self.player.request_preview(play_all, True))
        stop_btn.on_click(lambda: self.player.stop_playback())
        gen_all_btn = self.gen_all_btn
        gen_all_btn.on_click(lambda: self.enqueue_missing())
        export_btn.on_click(lambda: self.run_action(export_btn, self._export_work))

        ui.timer(1.0, self._poll_sources)

        strip_toggle.on_click(lambda: self.layout.toggle("strip"))
        console_toggle.on_click(lambda: self.layout.toggle("console"))
        collapse_strip.on_click(lambda: self.layout.toggle("strip"))
        collapse_console.on_click(lambda: self.layout.toggle("console"))
        strip_split.on_value_change(lambda _e: self.layout.on_drag())
        console_split.on_value_change(lambda _e: self.layout.on_drag())
        ui.on("ss_resize", self.layout.on_resize)
        ui.keyboard(on_key=self._on_key)

        self.render()
        self.layout.sync_toggles()
        if self.auto_build_active():  # deck opened with auto-build already on: fill it
            self._sweep_auto_build()

    # ---- filmstrip -----------------------------------------------------
    def build_strip(self) -> None:
        """(Re)build the filmstrip; thumbnails degrade to id tiles without pdftoppm."""
        state = self.state
        images: list[Path] = []
        try:
            images = state.ensure_images()
        except Exception as exc:
            logger.warning("thumbnail render failed: %s", exc)
        self.thumb_cards.clear()
        self.strip_col.clear()
        with self.strip_col:
            for i, sid in enumerate(state.deck.pages):
                with ui.element("div").classes("ss-thumb").mark(f"thumb-{i}") as card:
                    if i < len(images):
                        ui.image(_media_url(state, images[i], cache_bust=True)).classes("w-full")
                    else:
                        ui.label(sid or f"page {i + 1}").classes("ss-thumb-fallback ss-mono")
                    dot = ui.element("div").classes("ss-dot")
                    audio_badge = ui.icon("graphic_eq").classes("ss-thumb-audio hidden")
                    audio_badge.mark(f"thumb-audio-{i}")
                    audio_badge.tooltip("Some audio on this slide isn't generated yet")
                    ui.label(str(i + 1)).classes("ss-thumb-num")
                card.on("click", lambda _e=None, i=i: self.jump(i))
                self.thumb_cards.append((card, dot, audio_badge))

    def _scroll_strip(self) -> None:
        card = self.thumb_cards[self.state.index][0]
        try:  # best-effort; no JS client in tests
            ui.run_javascript(
                f"document.getElementById('c{card.id}')"
                "?.scrollIntoView({block: 'nearest', behavior: 'smooth'})"
            )
        except Exception:
            pass

    # ---- footer flash + save indicator -----------------------------------
    def flash(self, message: str, kind: str = "info") -> None:
        """Status messages glide through the footer instead of popping up as pills
        (pills stack over the transport and steal clicks). Last message wins; a
        token keeps an old fade timer from wiping a newer message early."""
        self._flash_token += 1
        token = self._flash_token
        css = {"positive": "ss-flash-ok", "warning": "ss-flash-warn", "negative": "ss-flash-err"}
        self.flash_label.set_text(message)
        self.flash_label.classes(remove=_FLASH_COLORS, add=css.get(kind, "ss-flash-info"))

        def _fade() -> None:
            if self._flash_token == token:
                self.flash_label.set_text("")

        linger = 8.0 if kind in ("warning", "negative") else 4.0
        with self.flash_label:  # park the timer in a slot that outlives any card rebuild
            ui.timer(linger, _fade, once=True)

    def show_saved_flash(self) -> None:
        self.saved_flash.classes(remove="opacity-0")
        with self.saved_flash:  # park the timer in a slot that outlives card rebuilds
            ui.timer(1.2, lambda: self.saved_flash.classes(add="opacity-0"), once=True)

    # ---- rendering -------------------------------------------------------
    def render(self) -> None:
        self.render_side()
        self.blocks.render()

    def render_side(self) -> None:
        """Everything but the block editor — safe to call on a silent commit."""
        state = self.state
        self.page_label.set_text(f"Slide {state.index + 1} / {state.page_count}")
        if state.error_count:
            self.err_badge.set_text(f"⛔ {state.error_count} errors")
            self.err_badge.classes(remove="ss-pill-ok", add="ss-pill-err")
        else:
            self.err_badge.set_text("✓ no errors")
            self.err_badge.classes(remove="ss-pill-err", add="ss-pill-ok")
        self.id_label.set_text(state.current_id or "(no slide id)")
        editable = bool(state.current_id)
        self.add_line_btn.set_enabled(editable)
        self.add_pause_btn.set_enabled(editable)
        try:
            img = state.current_image()
            if img is not None:
                self.slide_img.set_source(_media_url(state, img, cache_bust=True))
        except Exception as exc:  # rasterize may fail without pdftoppm
            logger.warning("image render failed: %s", exc)
        ungenerated = state.ungenerated_ids()
        for i, (card, dot, audio_badge) in enumerate(self.thumb_cards):
            if i >= len(state.deck.pages):
                break  # strip is briefly stale after a recompile; poll rebuilds it
            if i == state.index:
                card.classes(add="ss-active")
            else:
                card.classes(remove="ss-active")
            dot.classes(remove=_ALL_DOTS, add=f"ss-dot-{state.status_for(state.deck.pages[i])}")
            if state.deck.pages[i] in ungenerated:
                audio_badge.classes(remove="hidden")
            else:
                audio_badge.classes(add="hidden")
        self._scroll_strip()
        self._render_diagnostics()
        self._render_audio_status()
        self.tray.render()
        self.player.sync_transport()
        self.blocks.sync_gen_buttons()

    def _render_diagnostics(self) -> None:
        self.diag_box.clear()
        with self.diag_box:
            diags = self.state.diagnostics_for_current()
            if not diags:
                ui.label("no issues on this slide").classes("ss-diag ss-diag-ok")
            for d in diags:
                css = {"error": "ss-diag-err", "warning": "ss-diag-warn"}.get(
                    d.severity, "ss-diag-info"
                )
                ui.label(f"{d.severity}: {d.message}").classes(f"ss-diag {css}")

    def _render_audio_status(self) -> None:
        # deck-wide: the button promises exactly what a click will do — only the
        # missing clips are made; existing audio is never re-made or re-billed
        state = self.state
        missing = state.uncached_total()
        self.gen_all_btn.set_text(
            f"Generate missing ({missing})" if missing else "All audio generated"
        )
        self.gen_all_btn.set_enabled(missing > 0)
        total = len(state.current_block.speech_segments)
        self.audio_status.classes(remove="ss-diag-ok ss-diag-warn ss-diag-info")
        if total == 0:
            self.audio_status.set_text("no speech on this slide")
            self.audio_status.classes(add="ss-diag-info")
            return
        done = total - state.uncached_count(state.current_id)
        self.audio_status.set_text(f"{done} of {total} generated")
        self.audio_status.classes(add="ss-diag-ok" if done == total else "ss-diag-warn")

    # ---- navigation (each saves first) ----
    def jump(self, index: int) -> None:
        self.blocks.save_current()
        state = self.state
        moved = max(0, min(index, state.page_count - 1)) != state.index
        state.go(index)
        action = self.player.playback.nav_action() if moved else "none"
        if action == "seek" and self.player.cues:  # deck track loaded: follow to this cue
            start = cue_start(self.player.cues, state.current_id)
            if start is not None:
                self.player.audio.seek(start)
        elif action == "clear":  # a single-slide track belongs to its slide — reset
            self.player.stop_playback()
        self.render()

    def go(self, delta: int) -> None:
        self.jump(self.state.index + delta)

    def _on_key(self, e: KeyEventArguments) -> None:
        if not e.action.keydown:
            return
        delta = nav_direction(e.key)
        if delta:
            self.go(delta)

    # ---- actions (saved first, run off the event loop, one at a time) ----
    async def run_action(
        self,
        btn: Any,
        work: Callable[[], str],
        *,
        stops_player: bool | Callable[[], bool] = False,
    ) -> None:
        if self.busy:
            return
        self.busy = True
        # The action may replace audio, making a rolling preview stale — but only
        # stop playback when it actually touches the loaded track (a predicate
        # decides at click time; a plain True always stops).
        if stops_player() if callable(stops_player) else stops_player:
            self.player.stop_playback()
        self.blocks.save_current()
        btn.props("loading")
        try:
            self.flash(await run.io_bound(work), "positive")
        except NotImplementedError as exc:
            self.flash(str(exc), "warning")
        except Exception as exc:  # surface backend errors without crashing the UI
            logger.exception("action failed")
            self.flash(f"Error: {exc}", "negative")
        finally:
            self.busy = False
            btn.props(remove="loading")
            self.render()

    def enqueue_segment(self, speech_index: int) -> None:
        """Queue (re)generation of one utterance — non-blocking; the editor stays live.

        A cached clip means the press is a "fresh take" (force). Manual generation
        is an explicit user action, so it may bill a paid engine (unlike the
        unattended auto-build path). A rolling preview of the affected slide/deck
        is stopped so the next play rebuilds with the new audio.
        """
        # flush the (possibly typed-but-unblurred) field first: the worker
        # re-reads the sidecar from disk, so it must see the current text
        self.blocks.save_current()
        state = self.state
        flags = state.speech_cached_flags()
        force = speech_index < len(flags) and flags[speech_index]
        handles = self.jobs.enqueue(
            {(state.current_id, speech_index)}, force=force, allow_paid=True
        )
        if handles and self.player.playback.loaded_key in ("deck", state.current_id):
            self.player.stop_playback()
        self.blocks.sync_gen_buttons()

    def enqueue_missing(self) -> None:
        """Queue every uncached clip across the deck — non-blocking background fill."""
        self.blocks.save_current()  # flush any open edit before the worker reads disk
        targets = self.state.targets_for_sweep()
        if not targets:
            return
        self.jobs.enqueue(targets, allow_paid=True)
        self.render_side()

    def _on_jobs_changed(self) -> None:
        """A background job changed state — repaint clip indicators and audio status.

        Runs from the worker task (outside any slot), so re-enter the page client.
        """
        try:
            with self.client:
                self.render_side()
        except Exception:  # the client may have disconnected mid-job
            logger.debug("jobs UI refresh failed (client gone?)", exc_info=True)

    # ---- auto-build (opt-in background generation as you edit) ------------
    def auto_build_active(self) -> bool:
        """Whether to quietly generate audio in the background after edits.

        Off by default; persisted per user. Local-only: a paid engine would bill
        on every save, so the checkbox is disabled and this stays False there.
        """
        enabled = bool(app.storage.general.get("auto_build", False))
        return enabled and not self.state.tts_is_paid

    def _sweep_auto_build(self) -> None:
        """One-time fill: queue every uncached clip except the focused slide's."""
        targets = self.state.targets_for_sweep(exclude_id=self.state.current_id)
        if targets:
            self.jobs.enqueue(targets)  # allow_paid stays False — never bills
            self.render_side()

    def _on_auto_build_toggle(self, enabled: bool) -> None:
        # read the toggle's new value directly (storage may not have synced yet)
        if enabled and not self.state.tts_is_paid:
            self._sweep_auto_build()

    def schedule_auto_build(self, slide_id: str) -> None:
        """Debounce an edited slide's background generation (restart its timer)."""
        if not self.auto_build_active():
            return
        existing = self._auto_build_timers.pop(slide_id, None)
        if existing is not None:
            existing.cancel()
        with self.saved_flash:  # park in a slot that outlives card rebuilds
            self._auto_build_timers[slide_id] = ui.timer(
                AUTO_BUILD_DEBOUNCE_S, lambda: self._run_auto_build(slide_id), once=True
            )

    def _run_auto_build(self, slide_id: str) -> None:
        self._auto_build_timers.pop(slide_id, None)
        if not self.auto_build_active():
            return
        # skip the utterance the user is still editing on this slide
        exclude = self.blocks.focused_speech_index if slide_id == self.state.current_id else None
        targets = self.state.targets_for_slide(slide_id, exclude_speech=exclude)
        if targets:
            self.jobs.enqueue(targets)
            self.render_side()

    def _export_work(self) -> str:
        out = self.state.pdf_path.with_suffix(".mp4")
        result = self.state.export(out)
        return f"Exported {out.name} ({result.duration:.1f}s)"

    async def confirm_paid_synth(self, count: int) -> bool:
        backend = self.state.config.tts.backend
        with ui.dialog() as dialog, ui.card():
            ui.label(
                f"{count} segment(s) aren't cached — synthesizing them with "
                f"{backend} will spend API credits."
            )
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button("Generate & play", on_click=lambda: dialog.submit(True)).props("no-caps")
        return bool(await dialog)

    # ---- live reload of deck sources (PDF recompile, sidecar/config edits) ----
    async def _poll_sources(self) -> None:
        if self.busy:  # don't yank the deck out from under a synth/export
            return
        state = self.state
        changes = await run.io_bound(state.external_changes)
        if not changes:
            return
        if "sidecar" not in changes:
            # a recompile is landing: flush typing first, so narration for a
            # dropped slide survives as an unattached block instead of vanishing.
            # (never on sidecar changes — that would clobber the external edit)
            self.blocks.save_current()
        prev_id = state.current_id
        if not await run.io_bound(state.poll_sources):
            return
        if state.source_error is not None:
            # bad TOML / sidecar grammar: the last good deck stays on screen,
            # but silence here would leave the user wondering why edits to the
            # file do nothing
            self.flash(f"Deck file has an error — {state.source_error}", "warning")
            return
        try:
            await run.io_bound(state.ensure_images)  # rasterize off the event loop
        except Exception:
            pass  # build_strip degrades to id tiles
        self.build_strip()
        # A PDF/config-only recompile leaves the narration untouched on disk, so
        # rebuilding the block editor would only revert whatever the user is
        # mid-typing. Refresh everything *but* the editor — unless our own slide
        # moved (dropped/renamed/reordered), where the cards must follow it.
        if "sidecar" in changes or state.current_id != prev_id:
            self.render()
        else:
            self.render_side()
        self.flash("Deck files changed on disk — reloaded", "info")


def build_editor(pdf_path: Path, sidecar_path: Path | None = None) -> EditorState:
    """Build the editor UI for *pdf_path* in the current page; return its state."""
    state = EditorState(pdf_path, sidecar_path=sidecar_path)
    _serve_media(state)
    EditorView(state).build()
    return state


def run_editor(
    pdf_path: Path,
    *,
    sidecar_path: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
    browser: str | None = None,
    app_window: bool = False,
) -> None:
    """Launch the NiceGUI editor for *pdf_path* (blocking).

    *browser* (or the ``SLIDESONNET_BROWSER`` env var) is a command used to open
    the URL — e.g. ``wslview``, ``"cmd.exe /c start"``, or a browser path; a
    ``{url}`` token in it is replaced with the URL (else the URL is appended).
    Under WSL, ``wslview`` (if installed) is used by default.

    *app_window* opens a chromeless app window via a Chromium browser
    (``<edge|chrome> --app=URL``) — auto-detecting Edge/Chrome (Windows-side
    under WSL). Note: Firefox has no app-window mode.
    """
    pdf_path = pdf_path.resolve()
    url = f"http://{host}:{port}"
    env_browser = os.environ.get("SLIDESONNET_BROWSER")
    wsl = is_wsl()

    @ui.page("/")
    def _index() -> None:
        build_editor(pdf_path, sidecar_path)

    show = False
    if open_browser and app_window:
        app_opener = app_invocation(browser, env_browser=env_browser, wsl=wsl)
        if app_opener is not None:
            app.on_startup(lambda o=app_opener: launch_browser(o, url))
        else:
            logger.warning(
                "--app needs a Chromium browser (Edge/Chrome) and none was found. "
                "Pass --browser with its path, or drop --app. Open %s manually.",
                url,
            )
    elif open_browser:
        opener, show = browser_invocation(
            browser, env_browser=env_browser, wsl=wsl, wslview=shutil.which("wslview")
        )
        if opener is not None:
            app.on_startup(lambda o=opener: launch_browser(o, url))
        elif not show and wsl:
            logger.info(
                "WSL detected and no browser configured — open %s in your Windows browser "
                "(install 'wslview', or pass --browser / --app to auto-open).",
                url,
            )

    print(f"slideSonnet editor running at {url}  (Ctrl-C to stop)")
    ui.run(host=host, port=port, title="slideSonnet", reload=False, show=show)
