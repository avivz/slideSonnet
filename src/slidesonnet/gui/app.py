"""NiceGUI narration editor: page nav, editing, per-slide TTS, preview, export.

The whole-deck preview plays a single pre-rendered track (silences baked in)
and flips the slide image on cue-sheet boundaries, so the preview is
sample-accurate to the exported video.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import json
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import HTTPException, Request, Response
from nicegui import app, background_tasks, run, ui
from nicegui.events import KeyEventArguments

from slidesonnet.audio.track import Cue
from slidesonnet.cache import render_dir
from slidesonnet.diagnostics import boundary_transition
from slidesonnet.gui.jobs import JobQueue
from slidesonnet.gui.launch import (
    app_invocation,
    browser_invocation,
    is_wsl,
    launch_browser,
)
from slidesonnet.gui.library import DeckEntry, DeckRegistry, deck_token
from slidesonnet.gui.theme import HEAD_MORPH, HEAD_RESIZE, apply_theme, wordmark
from slidesonnet.gui.state import (
    EditorState,
    bracket_silences,
    cue_start,
    split_edge_silences,
)
from slidesonnet.narration import transitions as trans
from slidesonnet.models import Backend, VoiceConfig
from slidesonnet.narration.model import Deck, Pace, PageNarration, Segment, Transition
from slidesonnet.pdf.reader import page_aspect
from slidesonnet.tts import BACKENDS

logger = logging.getLogger(__name__)

_MEDIA_URL = "/ssmedia"

#: The decks this process serves, addressed by token. Set by :func:`run_editor`;
#: created on demand for the standalone ``build_editor`` path (tests, dev server).
_registry: DeckRegistry | None = None
#: Set once the user ticks "don't ask again" on the switch-while-generating
#: prompt. Process-wide, i.e. for as long as this editor is running.
_skip_switch_prompt = False


def deck_url(token: str) -> str:
    """The editor page URL for a deck token."""
    return f"/d/{token}"


def _filter_decks(entries: Sequence[DeckEntry], query: str) -> list[DeckEntry]:
    """Decks whose label contains every whitespace-separated term of *query*.

    Substring-per-term rather than fuzzy subsequence: with deck names as
    regular as ``lecture02_4_llm_basics_p1``, typing ``02_4`` or ``llm`` should
    mean exactly what it looks like. Library order is preserved.
    """
    terms = query.lower().split()
    if not terms:
        return list(entries)
    return [e for e in entries if all(term in e.label.lower() for term in terms)]


def set_registry(registry: DeckRegistry) -> None:
    """Install the process-wide deck registry (see :func:`run_editor`)."""
    global _registry
    _registry = registry


def registry_for(pdf_path: Path) -> DeckRegistry:
    """The active registry, creating one rooted at *pdf_path*'s directory if needed.

    ``build_editor`` is entered directly by the dev server and the test harness,
    which never call :func:`run_editor`; those get a single-deck library rather
    than a missing one.
    """
    global _registry
    if _registry is None:
        _registry = DeckRegistry(pdf_path.resolve().parent)
    return _registry


# Sentinel value for the per-utterance picker's explicit "default" choice — an
# utterance set to it carries no voice and speaks with the deck default. Chosen so
# it can't collide with a real (named or engine) voice id.
DEFAULT_VOICE_OPTION = "__default__"


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


def _clip_meta_suffix(meta: tuple[float | None, int] | None) -> str:
    """Tooltip tail for a generated clip: ``" · 1.2s · 34 KB"`` (size always, dur if known)."""
    if meta is None:
        return ""
    duration, size = meta
    kb = size / 1024
    size_str = f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"
    return f" · {duration:.1f}s · {size_str}" if duration is not None else f" · {size_str}"


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
    url = f"{_MEDIA_URL}/{deck_token(state.pdf_path)}/{rel.as_posix()}"
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


def _single_slide_morph(
    block: PageNarration,
    incoming: Transition,
    index: int,
    images: Sequence[Path],
    total: float,
    media_url: Callable[[Path], str],
    *,
    enabled: bool = True,
) -> list[dict[str, Any]]:
    """Morph steps for a *single-slide* preview: its in- and out-transition.

    *incoming* is the effective transition entering this slide (its boundary with
    the previous slide); ``block.transition_out`` is the boundary with the next.
    The in-transition morphs the previous slide into this one as playback opens;
    the out-transition morphs this slide into the next as it closes. A missing
    neighbour (the deck's first/last slide) morphs against a black frame
    (``from``/``to`` is ``None``). Each is clamped to half the slide so the two
    never overlap.

    *enabled* is the "Play transitions in single-slide preview" toggle (off by
    default): when False a single-slide play is a plain cut, no morph at all.
    """
    if not enabled:
        return []

    def url(j: int) -> str | None:
        return media_url(images[j]) if 0 <= j < len(images) else None

    here = url(index)
    if here is None:  # no rasterized image — nothing to morph
        return []
    steps: list[dict[str, Any]] = []
    if incoming.is_animated:
        d = max(0.05, min(incoming.seconds, total / 2))
        steps.append({"at": d, "dur": d, "kind": incoming.kind, "from": url(index - 1), "to": here})
    t_out = block.transition_out
    if t_out.is_animated:
        d = max(0.05, min(t_out.seconds, total / 2))
        steps.append(
            {"at": total, "dur": d, "kind": t_out.kind, "from": here, "to": url(index + 1)}
        )
    return steps


def _serve_media(state: EditorState) -> None:
    """Ensure this deck's render dir exists and the media endpoint is live.

    One dynamic route serves every deck, keyed by token — a single ``/ssmedia``
    mount would bind to whichever deck was opened first and then hand deck A's
    page images to deck B. Requests go through NiceGUI's range-response helper,
    so the preview player can still seek within the assembled track.
    """
    (render_dir(state.pdf_path) / "pages").mkdir(parents=True, exist_ok=True)
    # Asking the router rather than tracking a flag: the route belongs to the
    # app instance, and a stale module-level flag would silently skip
    # registration on a rebuilt app (as the test server does per test).
    route_path = _MEDIA_URL + "/{token}/{filename:path}"
    if any(getattr(route, "path", None) == route_path for route in app.routes):
        return

    from nicegui.app.range_response import get_range_response

    @app.get(route_path)
    def _read_media(  # pyright: ignore[reportUnusedFunction]
        request: Request, token: str, filename: str, nicegui_chunk_size: int = 8192
    ) -> Response:
        entry = _registry.resolve(token) if _registry is not None else None
        if entry is None:  # unknown deck: never touch the filesystem for it
            raise HTTPException(status_code=404, detail="Not Found")
        local_dir = render_dir(entry.pdf_path).resolve()
        filepath = (local_dir / filename).resolve()
        if not filepath.is_relative_to(local_dir) or not filepath.is_file():
            raise HTTPException(status_code=404, detail="Not Found")
        return get_range_response(filepath, request, chunk_size=nicegui_chunk_size)


_ALL_DOTS = "ss-dot-error ss-dot-warning ss-dot-ready ss-dot-empty"
_FLASH_COLORS = "ss-flash-ok ss-flash-info ss-flash-warn ss-flash-err"

# Auto-build waits this long after the last edit before generating a slide's
# audio, so we synthesize once the text is stable — not on every keystroke-blur.
AUTO_BUILD_DEBOUNCE_S = 2.5

# How often the editor polls the deck's source files (PDF/sidecar/config) for
# external changes (a recompile, an edit in another tool).
SOURCE_POLL_INTERVAL_S = 1.0


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

    # Preview-only playback rates (HTML5 audio.playbackRate); never touch the cache.
    SPEEDS = (1.0, 1.25, 1.5, 2.0)

    def __init__(
        self,
        view: EditorView,
        *,
        audio: Any,
        pos_slider: Any,
        time_label: Any,
        play_one: Any,
        play_all: Any,
        speed_btn: Any,
    ) -> None:
        self.view = view
        self.audio = audio
        self.pos_slider = pos_slider
        self.time_label = time_label
        self.play_one = play_one
        self.play_all = play_all
        self.speed_btn = speed_btn
        self.speed = 1.0  # preview playback rate; sticks across slides and rebuilds
        self.playback = PlaybackController()
        self.cues: list[Cue] = []
        self.track_duration = 0.0
        self.scrubbing = False  # user is dragging the seek handle; don't fight them
        # An in-flight preview build (it may be waiting on the generation queue).
        # Tracked so Stop, navigation, or a second play-press can cancel the wait.
        self._build_task: asyncio.Task[None] | None = None
        self._build_key: str | None = None  # "deck" or the slide id being built
        self._build_btn: Any = None  # the play button wearing the build spinner

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

    @staticmethod
    def _fmt_speed(s: float) -> str:
        return f"{s:g}×"  # 1.0→"1×", 1.25→"1.25×", 1.5→"1.5×", 2.0→"2×"

    def cycle_speed(self) -> None:
        """Step the preview to the next playback rate, wrapping back to 1×.

        Preview-only: this is HTML5 ``audio.playbackRate``, not the per-utterance
        ``pace:`` directive — it never re-synthesizes, writes the cache, or touches
        the exported video. The chosen rate sticks across slide changes and across
        both play-slide and play-all (re-applied on every track (re)load).
        """
        i = self.SPEEDS.index(self.speed) if self.speed in self.SPEEDS else 0
        self.speed = self.SPEEDS[(i + 1) % len(self.SPEEDS)]
        self.speed_btn.set_text(self._fmt_speed(self.speed))
        self._apply_speed()

    def _apply_speed(self) -> None:
        """Push the current rate onto the audio element.

        Sets ``defaultPlaybackRate`` too: a fresh ``set_source`` triggers a media
        load that resets ``playbackRate`` to the default, so pinning the default
        keeps the speed across track rebuilds. ``preservesPitch`` keeps 2× natural
        rather than chipmunked.
        """
        self._run_js(
            f"(() => {{ const a = document.getElementById('c{self.audio.id}'); "
            f"if (a) {{ a.preservesPitch = true; "
            f"a.defaultPlaybackRate = {self.speed}; a.playbackRate = {self.speed}; }} }})()"
        )

    def _arm_morph(self, whole_deck: bool, total: float) -> None:
        """Push the morph schedule to the client engine.

        Whole-deck preview plays each boundary transition (cue-aligned); a
        single-slide preview plays just that slide's own in/out transitions.
        """
        state = self.view.state
        try:
            images = state.ensure_images()
        except Exception:
            images = []
        url = lambda p: _media_url(state, p, cache_bust=True)  # noqa: E731
        if whole_deck:
            steps = _morph_schedule(self.cues, state.deck, images, url)
        else:
            # single-slide transitions are opt-in (off by default) — a plain play
            # of one slide shouldn't flourish through its in/out morph by default.
            steps = _single_slide_morph(
                state.current_block,
                state.incoming_transition,
                state.index,
                images,
                total,
                url,
                enabled=bool(app.storage.general.get("single_slide_transitions", False)),
            )
        if not steps:
            self._run_js("window.ssMorph && window.ssMorph.stop()")
            return
        cfg = {
            "audioId": f"c{self.audio.id}",
            "stageId": f"c{self.view.stage_view.id}",
            "steps": steps,
        }
        self._run_js(f"window.ssMorph && window.ssMorph.start({json.dumps(cfg)})")

    def cancel_build(self) -> None:
        """Abort an in-flight preview build — the wait on the generation queue.

        Only the *waiting* stops: clips already queued keep generating in the
        background, so hitting Stop or navigating away never throws away audio.
        The build task's own ``finally`` does the final cleanup (and no-ops on a
        superseded build via its current-task guard), so the task handle is left
        in place here; we just drop the spinner right away for responsiveness.
        """
        task = self._build_task
        if task is None or task.done():
            return
        task.cancel()
        if self._build_btn is not None:
            self._build_btn.props(remove="loading")

    def stop_playback(self) -> None:
        self.cancel_build()  # abort a build still waiting on generation — Stop wins now
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
        lands before the build even starts still cancels it. A build may then sit
        waiting on the generation queue; that wait is cancellable — pressing the
        same play button again cancels it, pressing a *different* one supersedes
        it, and the queued audio keeps generating in the background either way.
        """
        view = self.view
        state = view.state
        # A play press flushes any open editor field first. The pause/edge-silence
        # number fields (and text/voice/etc.) commit on blur, and a play click can
        # land before that blur — so a focused, uncommitted silence change would
        # otherwise leave the loaded track stale and the press would *resume* it
        # (KNOWN_ISSUES). commit_audible saves the open block and, when it changed,
        # revokes the loaded track so press_action below returns "build", not
        # "resume". A no-op (nothing changed) leaves playback untouched.
        view.blocks.commit_audible()
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
        # action == "build". While a build is in flight, a repeat press on the
        # *same* track is ignored (so a double-click doesn't cancel itself —
        # Stop and navigation are how you cancel); a press on a *different* track
        # supersedes it. The queued audio keeps generating either way.
        if self._build_task is not None and not self._build_task.done():
            if self._build_key == key:
                return
            self.cancel_build()  # different track: supersede the in-flight build
        elif view.busy:
            return  # a blocking action (export) holds the editor
        token = self.playback.begin(deck=whole_deck)
        self._build_key = key
        self._build_btn = btn
        self.audio.pause()  # a rolling preview yields to the new request right away
        self.playback.set_playing(False)
        self.sync_transport()
        self._build_task = background_tasks.create(self._preview(btn, whole_deck, token))

    async def _preview(self, btn: Any, whole_deck: bool, token: int) -> None:
        view = self.view
        state = view.state
        client = view.client  # background tasks must re-enter the page's slot stack
        with client:
            view.blocks.save_current()
            btn.props("loading")
        try:
            scope = None if whole_deck else state.current_id
            uncached = (
                state.uncached_total() if whole_deck else state.uncached_count(state.current_id)
            )
            if state.tts_is_paid and uncached:
                with client:
                    if not await view.confirm_paid_synth(uncached):
                        return
            needed = state.all_targets(only_id=scope)
            if uncached:
                # Play needs clips that aren't generated yet. Preempt a heavy clip
                # generating for some *other* slide (it re-queues) so the worker is
                # free to make what we need now, and run the needed clips through the
                # prioritized queue. The build below then reads them from cache — no
                # second synth racing the model. (Fully-cached slides skip all this.)
                view.jobs.cancel_running_unless(needed)
                view.jobs.enqueue(needed, allow_paid=True)
            await view.jobs.await_targets(needed)

            def _on_assemble(label: str, done: int, total: int) -> None:
                # Runs in the io_bound worker thread; just record the counts. The
                # 0.5s progress timer (on the event loop) reads and renders them.
                if label == "assemble":
                    view.assembling = (done, total)

            build = state.preview_deck if whole_deck else state.preview_current
            view.assembling = (0, 0)  # show "Assembling audio…" until the first tick
            try:
                preview = await run.io_bound(build, _on_assemble)
            finally:
                view.assembling = None
            with client:
                if not self.playback.may_start(token):  # user pressed Stop while building
                    view.flash("Preview stopped", "info")
                    return
                self.cues = preview.cues if whole_deck else []
                self._arm_morph(whole_deck, preview.total_duration)
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
                self._apply_speed()  # the load resets playbackRate; re-pin the chosen speed
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
        except asyncio.CancelledError:
            # Stop / navigation / a new play press aborted the wait. The queued
            # generation keeps running — we only stopped waiting on it.
            with client:
                view.flash("Playback canceled — still generating in the background", "info")
            raise
        except Exception as exc:
            logger.exception("preview failed")
            with client:
                view.flash(f"Error: {exc}", "negative")
        finally:
            # Only the *current* build owns the spinner and player state; a
            # superseded one (a newer build already took over) cleans up nothing.
            if self._build_task is asyncio.current_task():
                self._build_task = None
                self._build_key = None
                self._build_btn = None
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
        # Speech indices whose live text diverges from the cached/saved text, so
        # their per-clip badge shows "not generated yet" the moment you type —
        # before any blur/save — and reverts if you undo back to the original.
        self._dirty_speech: set[int] = set()
        self.transition_getters: dict[str, Callable[[], Transition]] = {}
        # Per-slide start/end silence fields (only present for slides with speech);
        # "start"/"end" → a getter for that field's seconds. See render()/collect().
        self.silence_getters: dict[str, Callable[[], float]] = {}
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
            named = state.voice_options()  # the deck's named voices — no raw engine ids
            named_set = set(named)
            named_choices = list(named)
            if seg.voice and seg.voice not in named_choices:
                named_choices = [seg.voice, *named_choices]  # keep an explicit/legacy value visible
            # "default" is always offered (and selected when the utterance has no
            # voice); its label names what the deck default resolves to, without
            # leaking the engine's own voice id into this named picker.
            named_default = state.default_voice_label()
            default_label = f"default ({named_default})" if named_default else "default"

            def voice_label(v: str) -> str:
                # a named voice shows its underlying engine voice: "lecturer (am_michael)";
                # a raw/off-list id (legacy pin) shows bare. The " (...)" is greyed by the slot.
                if v not in named_set:
                    return v
                engine_voice = state.resolved_engine_voice(v)
                return f"{v} ({engine_voice})" if engine_voice else f"{v} (unmapped)"

            voice_options = {
                DEFAULT_VOICE_OPTION: default_label,
                **{v: voice_label(v) for v in named_choices},
            }
            with ui.row().classes("ss-utt-opts w-full items-end gap-2 no-wrap"):
                voice = (
                    ui.select(
                        voice_options,
                        value=seg.voice or DEFAULT_VOICE_OPTION,
                        label="Voice",
                        with_input=True,  # type to filter the named-voice list
                    )
                    .props(
                        "filled dense options-dense hide-bottom-space stack-label "
                        'title="Named voice (type to filter; pick default for the deck default)"'
                    )
                    .classes("ss-mono ss-uvoice")
                    .mark(f"uvoice-{index}")
                )
                # grey the " (engine voice)" tail in the dropdown list; the selected
                # box keeps the plain label (so it never shows raw markup).
                voice.add_slot(
                    "option",
                    r"""
                    <q-item v-bind="props.itemProps">
                      <q-item-section>
                        <q-item-label>{{ props.opt.label.indexOf(' (') < 0
                          ? props.opt.label
                          : props.opt.label.slice(0, props.opt.label.indexOf(' (')) }}<span
                          v-if="props.opt.label.indexOf(' (') >= 0" class="text-grey-6"
                          >{{ props.opt.label.slice(props.opt.label.indexOf(' (')) }}</span></q-item-label>
                      </q-item-section>
                    </q-item>
                    """,
                )
                manage = (
                    ui.button(icon="record_voice_over", on_click=self.view.open_voices_dialog)
                    .props("flat round dense size=sm color=grey-6")
                    .classes("self-center")
                    .mark(f"uvoice-manage-{index}")
                )
                with manage:
                    ui.tooltip("Manage named voices")
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
            # Flip the per-clip badge to "not generated yet" the instant the text
            # diverges from the cached take — before blur — and revert it on undo.
            text.on_value_change(
                lambda e, si=speech_index, original=seg.text: self._mark_text_dirty(
                    si, e.value, original
                )
            )
            voice.on_value_change(lambda: self.commit_audible())
            pace.on_value_change(lambda: self.commit_audible())
            direct.on("blur", lambda: self.commit_audible())
            direct.on("keydown.ctrl.s.prevent", lambda: self.commit_audible())
            for w in (text, voice, direct):  # keystroke-holding fields
                self._track_editing(w, speech_index)

        def collect() -> Segment:
            picked = voice.value
            chosen_voice = (
                None if picked == DEFAULT_VOICE_OPTION else (picked or "").strip() or None
            )
            return Segment.speech(
                text.value or "",
                voice=chosen_voice,
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

    def _silence_row(self, which: str, value: float, disabled: bool) -> None:
        """A per-slide start/end silence field (the hold the boundary plays over)."""
        label = "Start silence" if which == "start" else "End silence"
        with (
            ui.row()
            .classes("w-full items-center no-wrap gap-2 ss-silence-row")
            .mark(f"silence-{which}")
        ):
            ui.icon("more_horiz").classes("ss-pause-icon")
            secs = (
                ui.number(value=value, min=0, step=0.1, format="%.1f", suffix="s")
                .props("filled dense")
                .classes("ss-pause-secs")
                .mark(f"silence-secs-{which}")
            )
            ui.label(label).classes("ss-diag ss-diag-info")
            secs.tooltip(
                "Held silence at the slide's "
                + ("start" if which == "start" else "end")
                + " — a transition plays over it. 0 = no hold."
            )
            if disabled:
                secs.disable()
            secs.on("blur", lambda: self.commit_audible())
            secs.on("keydown.ctrl.s.prevent", lambda: self.commit_audible())
            self._track_editing(secs)

        self.silence_getters[which] = lambda: max(0.0, float(secs.value or 0.0))

    def render(self) -> None:
        self.editing_active = False  # the rebuild destroys any focused field
        self.focused_speech_index = None
        state = self.view.state
        self.blocks_col.clear()
        self.seg_collectors.clear()
        self.seg_gen_controls.clear()
        self._dirty_speech.clear()  # a fresh render reflects the saved text again
        self.transition_getters.clear()
        self.silence_getters.clear()
        block = state.current_block
        disabled = not state.current_id
        # A slide with speech gets dedicated start/end silence fields bracketing
        # its utterance/pause cards; the lone-pause case (a silent slide) keeps a
        # single pause card (its one hold). The edge silences are split out of the
        # card list and re-bracketed on save (materialize implicit→default).
        video = state.config.video
        has_speech = block.has_speech
        if has_speech:
            leading, middle, trailing = split_edge_silences(block.segments)
            start_val = leading if leading is not None else video.pre_silence
            end_val = trailing if trailing is not None else video.tail_seconds
        else:
            middle = list(block.segments)
        with self.blocks_col:
            if not state.current_id:
                ui.label(
                    "This page has no slide-id — add \\ssid in the source to narrate it."
                ).classes("ss-diag ss-diag-warn")
                return
            # the incoming transition is the boundary with the previous slide, so
            # it mirrors that slide's "out" — show the effective value, not a stale
            # per-block field that could disagree with the previous slide
            self._transition_row("in", state.incoming_transition, disabled)
            if has_speech:
                self._silence_row("start", start_val, disabled)
            speech_i = 0
            for i, seg in enumerate(middle):
                if seg.is_speech:
                    self.seg_collectors.append(self._utterance_card(i, seg, disabled, speech_i))
                    speech_i += 1
                else:
                    self.seg_collectors.append(self._pause_card(i, seg, disabled))
            if not middle and not has_speech:
                ui.label("(empty — add a line or a pause above)").classes("ss-diag ss-diag-info")
            if has_speech:
                self._silence_row("end", end_val, disabled)
            self._transition_row("out", block.transition_out, disabled)
        self.sync_gen_buttons()

    def _collect_middle(self) -> list[Segment]:
        """The utterance/pause cards (no edge silence fields)."""
        return [c() for c in self.seg_collectors]

    def _materialize(self, middle: list[Segment]) -> list[Segment]:
        """Bracket *middle* with the start/end silence fields when it has speech.

        A speech slide materializes its edge silences (the implicit deck default
        becomes an explicit ``pause``); a pause-only slide keeps its lone hold.
        """
        if self.silence_getters and any(s.is_speech for s in middle):
            start = self.silence_getters["start"]() if "start" in self.silence_getters else None
            end = self.silence_getters["end"]() if "end" in self.silence_getters else None
            return bracket_silences(middle, start, end)
        return middle

    def collect(self) -> tuple[list[Segment], Transition, Transition]:
        segs = self._materialize(self._collect_middle())
        getters = self.transition_getters
        tin = getters["in"]() if "in" in getters else Transition()
        tout = getters["out"]() if "out" in getters else Transition()
        return segs, tin, tout

    def _apply_structure(self, segs: list[Segment], tin: Transition, tout: Transition) -> None:
        """Commit an add/delete/move — the loaded track no longer matches the deck."""
        slide_id = self.view.state.current_id
        if self.view.state.replace_block(segs, transition_in=tin, transition_out=tout):
            self.view.player.stop_playback()
            # a structural commit flushes any typed-but-unblurred utterance, so it
            # must schedule auto-build too — otherwise text saved this way (type a
            # line, then add/delete/reorder a block) never gets generated.
            self.view.schedule_auto_build(slide_id)
            self.view.render()

    def _collect_edits(self) -> tuple[list[Segment], Transition, Transition]:
        """The middle cards + transitions, for a structural edit (add/delete/move).

        Edits act on the middle list — the edge silences are fixed fields, not
        reorderable cards — and are re-bracketed by :meth:`_materialize` on apply.
        """
        getters = self.transition_getters
        tin = getters["in"]() if "in" in getters else Transition()
        tout = getters["out"]() if "out" in getters else Transition()
        return self._collect_middle(), tin, tout

    def add_segment(self, kind: str) -> None:
        middle, tin, tout = self._collect_edits()
        middle.append(Segment.speech("") if kind == "speech" else Segment.pause(1.0))
        self._apply_structure(self._materialize(middle), tin, tout)

    def _delete_segment(self, index: int) -> None:
        middle, tin, tout = self._collect_edits()
        if 0 <= index < len(middle):
            del middle[index]
        self._apply_structure(self._materialize(middle), tin, tout)

    def _move_segment(self, index: int, delta: int) -> None:
        middle, tin, tout = self._collect_edits()
        j = index + delta
        if 0 <= index < len(middle) and 0 <= j < len(middle):
            middle[index], middle[j] = middle[j], middle[index]
            self._apply_structure(self._materialize(middle), tin, tout)

    def save_current(self) -> bool:
        """Flush the open editor widgets to disk without rebuilding the cards."""
        if not self.seg_collectors and "in" not in self.transition_getters:
            return False  # nothing built (e.g. unmarked page)
        segs, tin, tout = self.collect()
        slide_id = self.view.state.current_id
        changed = self.view.state.replace_block(segs, transition_in=tin, transition_out=tout)
        if changed:
            # The dirty flags mean "unsaved text the cached clip no longer
            # matches". Saving settles that question: from here the cache flags
            # (recomputed against the saved text) are the truth on their own.
            # Leaving them set kept every touched utterance amber for the rest of
            # the visit — including right after auto-build regenerated its audio —
            # since this path deliberately doesn't rebuild the cards.
            self._dirty_speech.clear()
            self.view.show_saved_flash()
            self.view.render_side()
            self.view.schedule_auto_build(slide_id)
            self.sync_gen_buttons()
        return changed

    def commit(self) -> None:
        self.save_current()

    def commit_audible(self) -> None:
        """Commit a knob that changes what plays (pause length, voice, pace,
        transition): once the block differs, a loaded track is stale."""
        if self.save_current():
            self.view.player.stop_playback()

    def _mark_text_dirty(self, speech_index: int, value: str, original: str) -> None:
        """Track whether a live utterance edit diverges from its cached text.

        Called per keystroke: a diverging edit makes any generated clip stale, so
        flip its badge to amber right away; typing back to the original (undo)
        clears the flag and restores the green badge — all without a save.
        """
        if (value or "") != (original or ""):
            self._dirty_speech.add(speech_index)
        else:
            self._dirty_speech.discard(speech_index)
        self.sync_gen_buttons()

    def sync_gen_buttons(self) -> None:
        """Each utterance's generate button doubles as its audio indicator:
        amber wave = no audio yet (or an unsaved edit), green refresh = generated
        and up to date, and a spinner while a background job for that clip is
        queued or running."""
        if not self.seg_gen_controls:
            return
        view = self.view
        state = view.state
        flags = state.speech_cached_flags()
        meta = state.current_clip_meta()  # si -> (audio seconds, file bytes)
        speeches = state.current_block.speech_segments
        for btn, tip, si in self.seg_gen_controls:
            handle = view.jobs.handle_for(state.current_id, si)
            if handle is not None and handle.status in ("queued", "running"):
                btn.props("loading color=primary")
                tip.set_text("Generating…")
                btn.set_enabled(False)
                continue
            btn.props(remove="loading")
            dirty = si in self._dirty_speech  # unsaved edit: the cached take is stale
            cached = si < len(flags) and flags[si]
            fresh = cached and not dirty
            btn.props(
                f"icon={'autorenew' if fresh else 'graphic_eq'} "
                f"color={'positive' if fresh else 'warning'}"
            )
            if dirty:
                tip.set_text("Edited · click to regenerate")
            elif cached:
                tip.set_text(f"Generated{_clip_meta_suffix(meta.get(si))} · click for a fresh take")
            else:
                tip.set_text("No audio yet · click to generate")
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

    def __init__(self, state: EditorState, entry: DeckEntry | None = None) -> None:
        self.state = state
        self.registry = registry_for(state.pdf_path)
        # The library entry this page is showing. Built from the state when the
        # caller didn't supply one (the dev server and test harness enter through
        # build_editor with a bare path).
        self.entry = entry or self.registry.register(
            state.pdf_path, sidecar_path=state.sidecar_path
        )
        self.busy = False  # one action (synth/export/preview build) at a time
        self._flash_token = 0  # keeps an old fade timer from wiping a newer message
        self.thumb_cards: list[tuple[Any, Any, Any]] = []  # (card, dot, audio-missing badge)
        self._auto_build_timers: dict[str, Any] = {}  # per-slide debounce timers
        # (done, total) while the whole-deck preview track is being assembled, else
        # None. Written from the io_bound worker thread, polled by the progress
        # timer — a plain tuple write is atomic, so no lock is needed.
        self.assembling: tuple[int, int] | None = None

    def build(self) -> None:
        """Build the widget tree, attach the components, and wire all events."""
        state = self.state
        try:
            aspect = page_aspect(state.pdf_path)
        except Exception:  # never let a malformed page block the editor
            aspect = 16 / 9
        apply_theme(aspect=aspect, extras=HEAD_RESIZE + HEAD_MORPH)

        # --- header: wordmark · deck · save flash · error pill ---
        with ui.header().classes("ss-header items-center justify-between no-wrap"):
            with ui.row().classes("items-center gap-3 no-wrap"):
                wordmark()
                self._build_deck_switcher()
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
                        stop_btn.mark("stop").tooltip("Stop / cancel building")
                        speed_btn = ui.button("1×").props("flat dense no-caps").classes("ss-speed")
                        speed_btn.mark("speed").tooltip(
                            "Playback speed (preview only — no re-synth)"
                        )
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
                # Background-generation progress: a deck-wide count bar (A), an
                # estimated within-clip bar (C), and an elapsed/estimate line (B).
                # The ✕ beside the bar cancels every queued/running clip at once.
                with ui.row().classes("w-full items-center no-wrap gap-1"):
                    self.gen_bar = (
                        ui.linear_progress(value=0.0, show_value=False)
                        .props("rounded size=8px")
                        .classes("grow")
                    )
                    self.gen_bar.mark("gen-progress")
                    self.gen_cancel_btn = ui.button(
                        icon="close", on_click=self.cancel_all_generation
                    )
                    self.gen_cancel_btn.props("flat round dense size=xs color=grey-6")
                    self.gen_cancel_btn.mark("gen-cancel").tooltip("Cancel all generation")
                self.gen_clip_bar = (
                    ui.linear_progress(value=0.0, show_value=False)
                    .props("rounded size=4px instant-feedback")
                    .classes("w-full")
                )
                self.gen_status = ui.label().classes("ss-diag ss-diag-info ss-mono")
                self.gen_status.mark("gen-progress-status")
                self.gen_bar.visible = False
                self.gen_cancel_btn.visible = False
                self.gen_clip_bar.visible = False
                self.gen_status.visible = False
                tray_box = ui.column().classes("w-full gap-1")
                tray_box.mark("orphan-tray")
                tray_box.visible = False
                ui.space()
                ui.label("Engine").classes("ss-section")
                self.engine_select = (
                    ui.select(state.backend_options(), value=state.active_backend)
                    .props("dense outlined")
                    .classes("w-full ss-mono")
                )
                self.engine_select.mark("engine-select")
                self.engine_select.tooltip(
                    "Generate / preview / export with this engine — for this session only "
                    "(not saved to the deck)"
                )
                self.engine_select.on_value_change(lambda e: self._on_engine_change(str(e.value)))
                self.voices_btn = ui.button("Voices…", icon="record_voice_over").classes("w-full")
                self.voices_btn.props("flat no-caps dense").mark("edit-voices")
                self.voices_btn.tooltip(
                    "Name voices and map each to a per-engine voice — saved in the deck, "
                    "so the same script narrates under any engine"
                )
                self.voices_btn.on_click(self.open_voices_dialog)
                auto_build = ui.checkbox("Auto-generate as I edit").classes("ss-autobuild")
                auto_build.props("dense").mark("auto-build")
                # Always start a session with auto-generate off, even if a previous
                # session left it on — generation is opt-in each time you open the deck.
                app.storage.general["auto_build"] = False
                auto_build.bind_value(app.storage.general, "auto_build")
                self.auto_build = auto_build
                self._sync_auto_build_gate()
                auto_build.on_value_change(lambda e: self._on_auto_build_toggle(bool(e.value)))
                single_trans = ui.checkbox("Play transitions in single-slide preview")
                single_trans.props("dense").mark("single-slide-transitions")
                single_trans.tooltip(
                    "When on, playing one slide animates its in/out transitions; "
                    "off (default) plays just that slide's narration"
                )
                # Off each session — proofing one slide's audio shouldn't morph by
                # default; the whole-deck preview always plays transitions regardless.
                app.storage.general["single_slide_transitions"] = False
                single_trans.bind_value(app.storage.general, "single_slide_transitions")
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
            self.engine_label = ui.label(f"engine {state.active_backend}").classes(
                "ss-mono ss-foot"
            )
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
            speed_btn=speed_btn,
        )
        self.layout = PaneLayout(strip_split, console_split, strip_toggle, console_toggle)
        self.client = ui.context.client  # background tasks must re-enter the page's slot stack

        # background generation: keep the editor live while clips render
        self.jobs = JobQueue(
            deck_provider=state.jobs_context,
            synth=lambda targets, force: state.synth_targets(targets, force=force),
            is_paid=lambda: state.tts_is_paid,
            current_index=lambda: state.index,  # generate nearest-to-current first
            on_change=self._on_jobs_changed,
            on_error=self._on_job_error,
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
        speed_btn.on_click(lambda: self.player.cycle_speed())
        gen_all_btn = self.gen_all_btn
        gen_all_btn.on_click(self.enqueue_missing)
        export_btn.on_click(lambda: self.run_action(export_btn, self._export_work))

        ui.timer(SOURCE_POLL_INTERVAL_S, self._poll_sources)
        ui.timer(0.5, self._render_gen_progress)  # live elapsed/estimate while generating

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

    # ---- deck switching --------------------------------------------------
    def _page_task(self, coro: Coroutine[Any, Any, None]) -> None:
        """Run *coro* as a background task inside this page's slot stack.

        A task spawned from a keyboard handler starts with an empty slot stack,
        so anything it builds (the palette, a confirm dialog) would have nowhere
        to attach; re-entering the client fixes that for the whole task.
        """

        async def run() -> None:
            with self.client:
                await coro

        background_tasks.create(run())

    def _build_deck_switcher(self) -> None:
        """Header control: previous/next deck plus the current deck's name.

        The name is a button rather than a label so switching is discoverable
        without knowing the shortcut; the arrows are the sequential-audit path.
        """
        entry = self.entry
        alone = len(self.registry.entries()) < 2
        prev_btn = ui.button(icon="chevron_left").props("flat round dense size=sm")
        prev_btn.mark("deck-prev").tooltip("Deck back (Alt+←)")
        prev_btn.set_enabled(not alone)
        prev_btn.on_click(lambda: self.step_deck(-1))

        label = f"{entry.section} / {entry.name}" if entry.section else entry.name
        deck_btn = ui.button(label, icon="expand_more").props("flat dense no-caps")
        deck_btn.classes("ss-chip ss-mono ss-deck-btn").mark("deck-switcher")
        deck_btn.tooltip("Switch deck (Ctrl+K)")
        deck_btn.on_click(self.open_switcher)

        next_btn = ui.button(icon="chevron_right").props("flat round dense size=sm")
        next_btn.mark("deck-next").tooltip("Deck forward (Alt+→)")
        next_btn.set_enabled(not alone)
        next_btn.on_click(lambda: self.step_deck(1))

    async def step_deck(self, delta: int) -> None:
        """Move *delta* decks along the library order (wrapping)."""
        target = self.registry.neighbour(self.entry.token, delta)
        if target is not None and target.token != self.entry.token:
            await self.switch_to(target)

    async def open_switcher(self) -> None:
        """Type-to-filter palette over every deck in the library."""
        self.registry.rescan()  # a deck added since launch should show up
        entries = self.registry.entries()
        matches: list[DeckEntry] = list(entries)
        cursor = 0

        with ui.dialog() as dialog, ui.card().classes("ss-palette"):
            search = ui.input(placeholder="Jump to deck…").props("autofocus dense borderless")
            search.classes("ss-palette-input ss-mono w-full").mark("switcher-input")
            results = ui.column().classes("ss-palette-list gap-0 w-full")

            def render() -> None:
                results.clear()
                with results:
                    if not matches:
                        ui.label("No deck matches").classes("ss-palette-empty ss-mono")
                        return
                    for i, entry in enumerate(matches):
                        row = ui.row().classes("ss-palette-row items-baseline gap-2 no-wrap")
                        if i == cursor:
                            row.classes(add="ss-palette-active")
                        if entry.token == self.entry.token:
                            row.classes(add="ss-palette-current")
                        with row:
                            ui.label(entry.section or "·").classes("ss-palette-section ss-mono")
                            ui.label(entry.name).classes("ss-palette-name ss-mono")
                        row.mark(f"switcher-row-{i}")
                        row.on("click", lambda _e=None, x=entry: dialog.submit(x))

            def refilter() -> None:
                nonlocal matches, cursor
                matches = _filter_decks(entries, search.value or "")
                cursor = 0
                render()

            def move(delta: int) -> None:
                nonlocal cursor
                if matches:
                    cursor = (cursor + delta) % len(matches)
                    render()

            search.on_value_change(lambda _e: refilter())
            search.on("keydown.down", lambda: move(1))
            search.on("keydown.up", lambda: move(-1))
            search.on("keydown.enter", lambda: dialog.submit(matches[cursor]) if matches else None)
            search.on("keydown.escape", lambda: dialog.submit(None))
            render()

        chosen = await dialog
        if chosen is not None and chosen.token != self.entry.token:
            await self.switch_to(chosen)

    async def switch_to(self, entry: DeckEntry) -> None:
        """Leave for *entry*: save first, ask about live generation, then navigate."""
        self.blocks.save_current()  # the focused field's text must not vanish
        if not await self._confirm_leaving_generation(entry):
            return
        self.player.stop_playback()
        ui.navigate.to(deck_url(entry.token))

    async def _confirm_leaving_generation(self, entry: DeckEntry) -> bool:
        """True to proceed. Prompts when clips are still generating for this deck.

        Completed clips are already in the content-addressed cache and returning
        re-enqueues the rest, so the real cost is the one in-flight clip — but on
        a paid engine that clip is money, so the prompt is worth its keystroke.
        """
        global _skip_switch_prompt
        outstanding = self.jobs.outstanding()
        if outstanding == 0 or _skip_switch_prompt:
            return True
        clips = "1 clip is" if outstanding == 1 else f"{outstanding} clips are"
        with ui.dialog() as dialog, ui.card().classes("ss-confirm"):
            ui.label(f"{clips} still generating").classes("ss-confirm-title")
            ui.label(
                f"Leaving for {entry.name} stops them. Audio already generated is kept, "
                "and coming back picks up where this left off."
            ).classes("ss-confirm-body")
            skip = ui.checkbox("Don't ask again while the editor is open")
            skip.mark("switch-skip")
            with ui.row().classes("w-full justify-end gap-2"):
                stay = ui.button("Stay").props("flat")
                stay.mark("switch-stay").on_click(lambda: dialog.submit(False))
                go = ui.button("Switch anyway").props("unelevated")
                go.mark("switch-go").on_click(lambda: dialog.submit(True))
        proceed = await dialog
        if proceed and skip.value:
            _skip_switch_prompt = True
        return bool(proceed)

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
        # Alt+←/→ steps decks; the bare arrows keep stepping slides.
        if e.modifiers.alt:
            delta = nav_direction(e.key)
            if delta:
                self._page_task(self.step_deck(delta))
            return
        if e.modifiers.ctrl and str(e.key).lower() == "k":
            self._page_task(self.open_switcher())
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

    def _flag_model_warmup(self) -> None:
        """Warn once before a generation that must first load a heavy voice model.

        Only fires for a cold heavy engine (Qwen3); light engines report warm, so
        this is a no-op for them. Distinct from per-clip progress — it explains
        the long first pause while the multi-GB model loads.
        """
        if self.state.model_warmup_pending():
            logger.info(
                "[gen] loading the %s voice model — the first clip may take a while; "
                "the rest are quick.",
                self.state.active_backend,
            )

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
        self._flag_model_warmup()
        handles = self.jobs.enqueue(
            {(state.current_id, speech_index)}, force=force, allow_paid=True
        )
        if handles and self.player.playback.loaded_key in ("deck", state.current_id):
            self.player.stop_playback()
        self.blocks.sync_gen_buttons()

    async def enqueue_missing(self) -> None:
        """Queue every uncached clip across the deck — non-blocking background fill.

        On a paid cloud engine this is a batch that would spend credits, so it
        asks for explicit confirmation first (mirroring the play path); declining
        queues nothing.
        """
        self.blocks.save_current()  # flush any open edit before the worker reads disk
        targets = self.state.targets_for_sweep()
        backend = self.state.active_backend
        if not targets:
            logger.info("[gen] nothing to generate — all audio for %s exists", backend)
            self.flash(f"Nothing to generate — all audio for {backend} exists")
            return
        if self.state.tts_is_paid and not await self.confirm_paid_synth(
            len(targets), action_label="Generate"
        ):
            return
        self._flag_model_warmup()
        handles = self.jobs.enqueue(targets, allow_paid=True)
        logger.info("[gen] queued %d clip(s) for %s", len(handles), backend)
        self.flash(f"Generating {len(handles)} clip(s) with {backend}…")
        self.render_side()
        self._render_gen_progress()

    def _on_job_error(self, handle: Any) -> None:
        """Surface a background generation failure — they used to vanish silently.

        Runs from the worker task, so re-enter the page client before flashing.
        """
        try:
            with self.client:
                self.flash(f"Generation failed: {handle.error}", "negative")
                self.render_side()
        except Exception:
            logger.debug("job error flash failed (client gone?)", exc_info=True)

    def _on_jobs_changed(self) -> None:
        """A background job changed state — repaint clip indicators and audio status.

        Runs from the worker task (outside any slot), so re-enter the page client.
        """
        try:
            with self.client:
                self.render_side()
                self._render_gen_progress()
        except Exception:  # the client may have disconnected mid-job
            logger.debug("jobs UI refresh failed (client gone?)", exc_info=True)

    def _render_assemble_progress(self) -> bool:
        """Show the whole-deck assembly bar while the preview track is building.

        Generation runs first (its own bar) and finishes before assembly starts,
        so the two phases are mutually exclusive and share the same widgets.
        Returns True when assembly is active (and the bar now reflects it)."""
        asm = self.assembling
        if asm is None:
            return False
        a_done, a_total = asm
        self.gen_bar.visible = True
        self.gen_status.visible = True
        self.gen_cancel_btn.visible = False  # an in-flight ffmpeg concat isn't cancellable
        self.gen_clip_bar.visible = False
        self.gen_bar.set_value(a_done / a_total if a_total else 0.0)
        self.gen_status.set_text(
            f"Assembling audio  ·  {a_done}/{a_total}" if a_total else "Assembling audio…"
        )
        return True

    def _render_gen_progress(self) -> None:
        """Deck-wide generation progress: a count bar, an estimated within-clip bar,
        and a live elapsed/estimate line. Hidden whenever nothing is generating."""
        done, total = self.jobs.progress()
        running = self.jobs.running_handle()
        if total == 0 or (done >= total and running is None):
            # generation idle — the same bar may be showing assembly instead
            if self._render_assemble_progress():
                return
            for w in (self.gen_bar, self.gen_cancel_btn, self.gen_clip_bar, self.gen_status):
                w.visible = False
            return
        self.gen_bar.visible = True
        self.gen_cancel_btn.visible = True
        self.gen_status.visible = True
        self.gen_bar.set_value(done / total if total else 0.0)
        parts = [f"Generating {min(done + 1, total)}/{total}"]
        clip_fraction: float | None = None
        if running is not None and running.refs:
            sid, si = sorted(running.refs)[0]
            detail = sid
            if running.started_at is not None:
                elapsed = max(0.0, time.monotonic() - running.started_at)
                est = self.state.est_gen_seconds(sid, si)
                detail += f" · {elapsed:.0f}s"
                if est:
                    detail += f" of ~{est:.0f}s"
                    clip_fraction = min(0.97, elapsed / est) if est > 0 else None
            parts.append(detail)
        self.gen_status.set_text("  ·  ".join(parts))
        # The thin second bar estimates progress *within* the running clip.
        self.gen_clip_bar.visible = clip_fraction is not None
        if clip_fraction is not None:
            self.gen_clip_bar.set_value(clip_fraction)

    def cancel_all_generation(self) -> None:
        """Drop every queued clip and stop the running one (the progress-bar ✕)."""
        cleared = self.jobs.cancel_all()
        logger.info("[gen] canceled %d queued/running clip(s)", cleared)
        self.flash(
            f"Canceled generation ({cleared} clip{'s' if cleared != 1 else ''})"
            if cleared
            else "Nothing was generating"
        )
        self._render_gen_progress()
        self.render_side()

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

    def _sync_auto_build_gate(self) -> None:
        """Enable/disable "Auto-generate as I edit" for the active engine.

        Gate = paid only: a paid engine would bill on every save, so it stays off
        there. A free-but-slow engine (Qwen3) is allowed — the queue prioritizes
        the slides nearest where you're working, so editing stays responsive even
        though each clip is slow. Re-run whenever the engine changes.
        """
        cb = self.auto_build
        state = self.state
        if state.tts_is_paid:
            cb.set_value(False)
            cb.disable()
            cb.tooltip("Local engines only — a paid engine would bill on every save")
        else:
            cb.enable()
            tip = "Quietly generate each slide's audio in the background after you edit it"
            if not state.tts_is_realtime:
                tip += " — slow engine, so nearby slides are generated first"
            cb.tooltip(tip)

    def _on_engine_change(self, backend: str) -> None:
        """Switch the generation engine for this session (never written to disk)."""
        if backend not in self.state.backend_options():
            return
        self.state.set_backend(cast(Backend, backend))
        # Switching engines turns auto-generate off: the new engine's audio is all
        # uncached, and silently regenerating the whole deck on switch is rarely wanted.
        self.auto_build.set_value(False)
        self._sync_auto_build_gate()
        self.engine_label.set_text(f"engine {self.state.active_backend}")
        self.player.stop_playback()  # the loaded preview track was the old engine's
        self.render()  # per-engine cache badges, voice pickers, gen-missing count
        self.flash(f"Generating with {backend}")
        # Pre-load a heavy model now (Qwen3) so the first play doesn't stall on it.
        if self.state.model_warmup_pending():
            background_tasks.create(self._warm_engine())

    async def _warm_engine(self) -> None:
        """Background-load the picked engine's heavy model, off the event loop.

        Light engines are warm already, so this only does work for Qwen3. We pin
        the engine we started warming and bail on the UI update if the user has
        since switched away — the (cached) load still benefits a later switch back.
        """
        backend = self.state.active_backend
        self._flag_model_warmup()  # logs "loading the qwen3 voice model…" to the terminal
        try:
            await run.io_bound(self.state.warm_active_engine)
        except Exception:
            logger.exception("model warmup failed")
            return
        logger.info("[gen] %s voice model ready", backend)
        if self.state.active_backend == backend:
            with self.client:
                self.render()  # warmup banner clears now that is_warm() is True

    def open_voices_dialog(self) -> None:
        """Edit the deck's portable voice map: name voices + map each per engine.

        The map and the deck ``default-voice`` are written into the narration
        file's preamble on Save, so the same engine-agnostic script narrates under
        any engine by name. A file voice (a Qwen3 ``.pt``) is shown — and stored —
        relative to the deck. Closing without Save discards the edits.
        """
        state = self.state
        engines = sorted(BACKENDS)
        # (pickable voices, engine default) per engine — a new row's fields start at
        # the default, and engines with a list become a pick-or-type combobox.
        engine_choices = {eng: state.engine_voice_choices(eng) for eng in engines}
        rows: list[dict[str, Any]] = []
        seq = [0]  # monotonic row id for stable test markers (survives deletes)
        no_default = "(engine default)"

        with ui.dialog() as dialog, ui.card().classes("ss-voices-card"):
            ui.label("Voices").classes("ss-section")
            ui.label(
                "Name a voice, then map it to a concrete voice per engine: a Kokoro "
                "voice (e.g. am_michael), an Inworld voice name, or a Qwen3 .pt path "
                "relative to the deck. Leave an engine blank to use its own default. "
                "Saved in the narration file, so the deck narrates under any engine."
            ).classes("ss-hint")
            with ui.row().classes("w-full items-center no-wrap gap-1 ss-voice-head"):
                ui.label("name").classes("ss-mono ss-voice-name ss-foot")
                for eng in engines:
                    ui.label(eng).classes("ss-mono ss-voice-eng ss-foot")
                ui.element("div").classes("ss-voice-trash")
            rows_col = ui.column().classes("w-full gap-1")
            add_btn = ui.button("Add voice", icon="add").props("flat no-caps dense")
            add_btn.mark("voice-add")
            default_select = (
                ui.select([no_default], value=no_default, label="Default voice")
                .props("dense outlined")
                .classes("w-full ss-mono")
            )
            default_select.mark("voice-default")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                save_btn = ui.button("Save").props("no-caps")
                save_btn.mark("voice-save")

        def names() -> list[str]:
            return [n for r in rows if (n := str(r["name"].value).strip())]

        def pending_renames() -> dict[str, str]:
            """Old -> new for every seeded row whose name was edited (live)."""
            out: dict[str, str] = {}
            for r in rows:
                nm = str(r["name"].value).strip()
                orig = r.get("original")
                if orig and nm and orig != nm:
                    out[orig] = nm
            return out

        def refresh_defaults() -> None:
            opts = [no_default, *names()]
            # If the selected default voice was just renamed, follow it rather than
            # dropping the selection back to "(engine default)".
            cur = pending_renames().get(default_select.value, default_select.value)
            keep = cur if cur in opts else no_default
            default_select.set_options(opts, value=keep)

        def remove_row(entry: dict[str, Any]) -> None:
            rows.remove(entry)
            rows_col.remove(entry["row"])
            refresh_defaults()

        def add_row(
            name: str = "",
            voices: dict[str, str] | None = None,
            *,
            prefill: bool = False,
            original: str | None = None,
        ) -> None:
            voices = voices or {}
            rid = seq[0]
            seq[0] += 1
            with rows_col, ui.row().classes("w-full items-center no-wrap gap-1") as row:
                name_in = (
                    ui.input(placeholder="name", value=name)
                    .props("dense outlined")
                    .classes("ss-mono ss-voice-name")
                    .mark(f"voice-name-{rid}")
                )
                engine_ins: dict[str, Any] = {}
                for eng in engines:
                    options, default = engine_choices[eng]
                    # New rows start at the engine default; existing rows keep what
                    # they stored (blank = inherit the engine default at synth time).
                    cur = voices.get(eng) or (default if prefill else "") or ""
                    mark = f"voice-{eng}-{rid}"
                    if options:  # a fixed voice list → pick-or-type combobox
                        opts = [cur, *options] if cur and cur not in options else list(options)
                        engine_ins[eng] = (
                            ui.select(opts, value=cur or None)
                            .props(
                                "dense outlined use-input clearable hide-bottom-space "
                                "new-value-mode=add-unique"
                            )
                            .classes("ss-mono ss-voice-eng")
                            .mark(mark)
                        )
                    else:  # account-specific ids / .pt paths → free text
                        engine_ins[eng] = (
                            ui.input(placeholder=eng, value=cur)
                            .props("dense outlined")
                            .classes("ss-mono ss-voice-eng")
                            .mark(mark)
                        )
                trash = ui.button(icon="delete").props("flat round dense size=sm")
            # *original* is the name this row was seeded with (None for a new row),
            # so Save can tell a rename (same row, changed name) from add/delete.
            entry = {"name": name_in, "voices": engine_ins, "row": row, "original": original}
            rows.append(entry)
            trash.on_click(lambda: remove_row(entry))
            name_in.on_value_change(lambda: refresh_defaults())

        def save() -> None:
            new_map: dict[str, VoiceConfig] = {}
            renames: dict[str, str] = {}
            for r in rows:
                nm = str(r["name"].value).strip()
                if not nm:
                    continue
                # A seeded row whose name changed is a rename — record old -> new so
                # utterance voice: / default-voice references follow it.
                orig = r["original"]
                if orig and orig != nm:
                    renames[orig] = nm
                backend_voices = {
                    eng: v
                    for eng, w in r["voices"].items()
                    if (v := str(w.value or "").strip())  # a cleared combobox reads None
                }
                new_map[nm] = VoiceConfig(name=nm, backend_voices=backend_voices)
            default = default_select.value
            default = None if default == no_default else default
            # Make the default-voice follow a rename even if the select bounced to
            # "(engine default)" mid-typing (per-keystroke in a real browser): if the
            # picked old name was renamed, or the deck's prior default was renamed and
            # nothing else was chosen, point at the new name.
            if default in renames:
                default = renames[default]
            elif default is None and state.deck.default_voice in renames:
                default = renames[state.deck.default_voice]
            changed = state.edit_voices(new_map, default, renames=renames)
            dialog.close()
            if changed:
                self.render()  # voice pickers, placeholders, unmapped warnings relight
                self.flash("Voices saved", "positive")
            else:
                self.flash("No voice changes")

        def add_blank_row() -> None:
            add_row(prefill=True)  # a fresh voice starts at each engine's default
            refresh_defaults()

        add_btn.on_click(add_blank_row)
        save_btn.on_click(save)

        for nm, vc in state.voice_map_for_display().items():
            add_row(nm, vc.backend_voices, original=nm)
        if not rows:
            add_row(prefill=True)  # starter row: each engine pre-set to its default
        refresh_defaults()
        default_select.set_options(
            [no_default, *names()], value=state.deck.default_voice or no_default
        )
        dialog.open()

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

    async def confirm_paid_synth(self, count: int, action_label: str = "Generate & play") -> bool:
        """Popup gate before any paid synthesis. Returns True only on explicit OK.

        Every path that can bill a cloud engine (play, "Generate missing") routes
        through here first, so a paid engine never spends credits unattended.
        """
        # The *session-selected* engine is what bills (and what the paid gate
        # checks) — not the on-disk default, which may still be kokoro.
        backend = self.state.active_backend
        with ui.dialog() as dialog, ui.card():
            ui.label(
                f"{count} segment(s) aren't cached — synthesizing them with "
                f"{backend} will spend API credits."
            )
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                confirm = ui.button(action_label, on_click=lambda: dialog.submit(True))
                confirm.props("no-caps").mark("paid-confirm")
        return bool(await dialog)

    # ---- live reload of deck sources (PDF recompile, sidecar/config edits) ----
    async def _poll_sources(self) -> None:
        if self.busy or self.player._build_task is not None:
            return  # don't yank the deck out from under a synth/export/preview build
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
        # A loaded preview track (its assembled audio and baked-in morph schedule)
        # is now stale — the deck changed under it. Revoke it so the next play
        # rebuilds instead of resuming the old audio/transitions. We only reach
        # here with no build in flight (guarded above), so this can't yank one
        # mid-build; an in-GUI edit already does this via replace_block.
        if self.player.playback.loaded_key is not None:
            self.player.stop_playback()
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
        # An external recompile/sidecar edit can introduce new un-narrated or
        # newly-edited slides. With auto-build on, fill them too — the toggle's
        # one-time sweep only ran when it was switched on, so without this a
        # change from outside would sit ungenerated.
        if self.auto_build_active():
            self._sweep_auto_build()
        self.flash("Deck files changed on disk — reloaded", "info")


def build_editor(
    pdf_path: Path, sidecar_path: Path | None = None, *, entry: DeckEntry | None = None
) -> EditorState:
    """Build the editor UI for *pdf_path* in the current page; return its state.

    *entry* is the library entry being opened, when the caller has one; without
    it the deck is registered on the spot so its media and neighbours resolve.
    """
    state = EditorState(pdf_path, sidecar_path=sidecar_path)
    _serve_media(state)
    _retarget_deck_log(pdf_path)
    EditorView(state, entry).build()
    return state


#: How the run-log was configured on the command line, so a deck switch can
#: re-apply the same choice to the deck it lands on.
_log_prefs: dict[str, Any] = {"override": None, "disabled": False}


def set_log_preferences(*, override: Path | None, disabled: bool) -> None:
    """Remember the CLI's ``--log-file``/``--no-log-file`` choice for later switches."""
    _log_prefs["override"] = override
    _log_prefs["disabled"] = disabled


def _retarget_deck_log(pdf_path: Path) -> None:
    """Point the run-log at the deck now being edited.

    The file handler is attached once per process and re-targeted here, so
    opening deck B stops appending B's lines to deck A's
    ``.slidesonnet/slidesonnet.log``. An explicit ``--log-file`` still wins.
    """
    from slidesonnet.logging_setup import attach_deck_file_logging

    attach_deck_file_logging(
        pdf_path,
        override=cast(Path | None, _log_prefs["override"]),
        disabled=bool(_log_prefs["disabled"]),
    )


def register_pages(registry: DeckRegistry) -> None:
    """Register the library page (``/``) and the per-deck editor page.

    One parameterized route serves every deck: switching decks is a navigation,
    so the page teardown NiceGUI already does (job queue stopped on disconnect,
    timers dropped with the client) is the whole of the cleanup.
    """
    set_registry(registry)

    @ui.page("/")
    def _library() -> None:  # pyright: ignore[reportUnusedFunction]
        from slidesonnet.gui.library_view import build_library

        build_library(registry)

    @ui.page("/d/{token}")
    def _deck(token: str) -> None:  # pyright: ignore[reportUnusedFunction]
        entry = registry.resolve(token)
        if entry is None:  # stale bookmark, or a deck that has since moved away
            ui.navigate.to("/")
            return
        build_editor(entry.pdf_path, entry.sidecar_path, entry=entry)


def run_editor(
    pdf_path: Path | None = None,
    *,
    sidecar_path: Path | None = None,
    root: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
    browser: str | None = None,
    app_window: bool = False,
) -> None:
    """Launch the NiceGUI editor, opening the deck library at ``/`` (blocking).

    *pdf_path* is the deck to highlight in the library (and it is registered even
    when it sits outside *root*); pass ``None`` to open the library alone.
    *root* is the directory the library is scanned from — ``--root``, else the
    directory given to ``edit``, else the cwd. No VCS assumption is made.

    *browser* (or the ``SLIDESONNET_BROWSER`` env var) is a command used to open
    the URL — e.g. ``wslview``, ``"cmd.exe /c start"``, or a browser path; a
    ``{url}`` token in it is replaced with the URL (else the URL is appended).
    Under WSL, ``wslview`` (if installed) is used by default.

    *app_window* opens a chromeless app window via a Chromium browser
    (``<edge|chrome> --app=URL``) — auto-detecting Edge/Chrome (Windows-side
    under WSL). Note: Firefox has no app-window mode.
    """
    scan_root = (root or (pdf_path.parent if pdf_path else Path.cwd())).resolve()
    registry = DeckRegistry(scan_root)
    result = registry.rescan()
    if pdf_path is not None:
        registry.register(pdf_path, sidecar_path=sidecar_path)
    register_pages(registry)

    logger.info(
        "Deck library: %d deck(s) under %s%s",
        len(registry.entries()),
        scan_root,
        " (scan truncated — pass --root to narrow it)" if result.truncated else "",
    )

    url = f"http://{host}:{port}"
    env_browser = os.environ.get("SLIDESONNET_BROWSER")
    wsl = is_wsl()

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

    logger.info("slideSonnet editor running at %s  (Ctrl-C to stop)", url)
    ui.run(host=host, port=port, title="slideSonnet", reload=False, show=show)
