"""NiceGUI narration editor: page nav, editing, per-slide TTS, preview, export.

The whole-deck preview plays a single pre-rendered track (silences baked in)
and flips the slide image on cue-sheet boundaries, so the preview is
sample-accurate to the exported video.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from nicegui import app, background_tasks, run, ui
from nicegui.events import KeyEventArguments

from slidesonnet.cache import render_dir
from slidesonnet.gui.state import EditorState, cue_start
from slidesonnet.narration.model import Pace, Segment, Transition
from slidesonnet.pdf.reader import page_aspect

logger = logging.getLogger(__name__)

_MEDIA_URL = "/ssmedia"
_served: set[str] = set()


def is_wsl() -> bool:
    """True when running under Windows Subsystem for Linux."""
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def browser_invocation(
    browser: str | None,
    *,
    env_browser: str | None = None,
    wsl: bool = False,
    wslview: str | None = None,
) -> tuple[list[str] | None, bool]:
    """Decide how to open the editor URL.

    Returns ``(opener, use_nicegui_show)``:
    - ``opener`` is a command (argv list) we launch ourselves with the URL
      (substituted for ``{url}`` if present, else appended), or ``None`` if we
      won't open a browser ourselves.
    - ``use_nicegui_show`` is whether to let NiceGUI open its default browser.

    An explicit ``--browser`` / ``SLIDESONNET_BROWSER`` wins. Under WSL we prefer
    ``wslview`` (opens the *Windows* default browser) and otherwise refuse to
    launch a Linux browser — just print the URL. On a normal desktop we let
    NiceGUI handle it.
    """
    chosen = browser or env_browser
    if chosen:
        return shlex.split(chosen), False
    if wsl:
        return ([wslview] if wslview else None), False
    return None, True


def apply_url(cmd: list[str], url: str) -> list[str]:
    """Substitute *url* for a ``{url}`` token in *cmd*, or append it if absent."""
    if any("{url}" in tok for tok in cmd):
        return [tok.replace("{url}", url) for tok in cmd]
    return [*cmd, url]


# Common Windows install paths for Chromium browsers (seen from WSL under /mnt/c).
_WINDOWS_CHROMIUM = [
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
]
# Linux/native Chromium executables (for --app on a non-WSL desktop).
_LINUX_CHROMIUM = ["google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave"]


def find_chromium(
    *,
    wsl: bool,
    exists: Callable[[str], bool],
    which: Callable[[str], str | None],
) -> str | None:
    """Locate a Chromium-based browser executable for app-window mode.

    Under WSL, look for Edge/Chrome under ``/mnt/c``; otherwise search PATH.
    Returns the executable path, or ``None`` if none is found.
    """
    if wsl:
        return next((p for p in _WINDOWS_CHROMIUM if exists(p)), None)
    for name in _LINUX_CHROMIUM:
        found = which(name)
        if found:
            return found
    return None


def app_invocation(
    browser: str | None,
    *,
    env_browser: str | None = None,
    wsl: bool = False,
    exists: Callable[[str], bool] = os.path.exists,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str] | None:
    """Build a chromeless app-window command (`<chromium> --app={url}`).

    Uses an explicit ``--browser``/env executable if given (shlex-split, so it
    may carry args), else auto-detects Edge/Chrome (kept as a single token since
    Windows paths contain spaces). Returns the argv (with a ``{url}`` placeholder)
    or ``None`` if no Chromium browser could be found.
    """
    explicit = browser or env_browser
    if explicit:
        base = shlex.split(explicit)
    else:
        exe = find_chromium(wsl=wsl, exists=exists, which=which)
        if not exe:
            return None
        base = [exe]
    return [*base, "--app={url}"]


def dev_invocation(
    pdf_path: Path,
    *,
    sidecar_path: Path | None,
    host: str,
    port: int,
    browser: str | None = None,
    app_window: bool = False,
    no_browser: bool = False,
) -> tuple[list[str], dict[str, str]]:
    """Argv + extra env to launch the auto-reload dev server (``edit --dev``).

    NiceGUI's reload mode re-imports its entry module in a child process, so it
    needs a ``python -m``-runnable module (``slidesonnet.gui.devserver``) rather
    than the console-script entry point; parameters travel via environment.
    """
    env = {
        "SLIDESONNET_DEV_PDF": str(pdf_path.resolve()),
        "SLIDESONNET_DEV_HOST": host,
        "SLIDESONNET_DEV_PORT": str(port),
    }
    if sidecar_path is not None:
        env["SLIDESONNET_DEV_SIDECAR"] = str(sidecar_path.resolve())
    if browser:
        env["SLIDESONNET_DEV_BROWSER"] = browser
    if app_window:
        env["SLIDESONNET_DEV_APP"] = "1"
    if no_browser:
        env["SLIDESONNET_DEV_NO_BROWSER"] = "1"
    return [sys.executable, "-m", "slidesonnet.gui.devserver"], env


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


def _media_url(state: EditorState, path: Path) -> str:
    rel = path.resolve().relative_to(render_dir(state.pdf_path).resolve())
    return f"{_MEDIA_URL}/{rel.as_posix()}"


def _serve_media(state: EditorState) -> None:
    rdir = render_dir(state.pdf_path)
    (rdir / "pages").mkdir(parents=True, exist_ok=True)
    key = str(rdir)
    if key in _served:
        return
    app.add_media_files(_MEDIA_URL, rdir)
    _served.add(key)


# ---------------------------------------------------------------------------
# look & feel: a dark studio theme — cool graphite surfaces, electric-blue
# accents, IBM Plex Mono for everything machine-flavored; filmstrip + stage
# + console.
# ---------------------------------------------------------------------------

_FONTS_HTML = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
    "?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800"
    "&family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600"
    '&display=swap">'
)

_NOISE_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence "
    "type='fractalNoise' baseFrequency='0.8' numOctaves='2'/%3E%3C/filter%3E"
    "%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"
)

_CSS = """
:root{
  --ss-bg:#0e1116; --ss-surface:#151a22; --ss-raised:#1e2531;
  --ss-line:#2b3442; --ss-text:#e8ecf3; --ss-dim:#8a94a6;
  --ss-accent:#5db3f0; --ss-accent-deep:#2f7fc4;
  --ss-err:#ff6b6b; --ss-warn:#ffc857; --ss-ok:#7ee08a;
}
body{
  background:
    radial-gradient(1100px 520px at 72% -10%, rgba(93,179,240,.06), transparent 60%),
    var(--ss-bg) !important;
  font-family:"IBM Plex Sans",sans-serif;
}
.nicegui-content{padding:0}
.ss-mono,.ss-mono textarea,.ss-mono input{
  font-family:"IBM Plex Mono",ui-monospace,monospace}
.ss-wordmark{
  font-family:"Bricolage Grotesque",sans-serif;font-size:19px;font-weight:800;
  letter-spacing:.01em;color:var(--ss-text)}
.ss-accent{color:var(--ss-accent)}
.ss-header{
  background:rgba(21,26,34,.92)!important;border-bottom:1px solid var(--ss-line);
  backdrop-filter:blur(10px);padding:0 18px;height:52px}
.ss-footer{
  background:var(--ss-surface)!important;border-top:1px solid var(--ss-line);
  height:28px;padding:0 18px;display:flex;align-items:center}
.ss-foot{font-size:11px;color:var(--ss-dim)}
.ss-chip{
  font-size:11px;color:var(--ss-dim);border:1px solid var(--ss-line);
  border-radius:999px;padding:2px 10px;background:var(--ss-raised)}
.ss-saved{
  font-family:"IBM Plex Mono",monospace;font-size:11px;font-weight:600;
  color:var(--ss-ok);transition:opacity .6s}
.ss-pill{
  font-family:"IBM Plex Mono",monospace;font-size:11px;font-weight:600;
  border-radius:999px;padding:3px 10px;border:1px solid transparent}
.ss-pill-ok{color:var(--ss-ok);border-color:rgba(139,217,124,.35)}
.ss-pill-err{
  color:var(--ss-err);border-color:rgba(255,101,82,.45);
  background:rgba(255,101,82,.08)}
.ss-pill-warn{
  color:var(--ss-warn);border-color:rgba(217,162,60,.45);
  background:rgba(217,162,60,.08)}
.ss-body textarea::placeholder{color:var(--ss-dim);opacity:.55;font-style:italic}
.ss-main{height:calc(100vh - 80px)}
.ss-split{position:relative}
.ss-split > .q-splitter__separator{background:var(--ss-line)}
.ss-split > .q-splitter__separator:hover{background:var(--ss-accent-deep)}
.ss-split > .q-splitter__panel{overflow:hidden}
.ss-grip{
  font-size:13px;color:var(--ss-dim);background:var(--ss-raised);
  border:1px solid var(--ss-line);border-radius:6px;padding:8px 0}
.ss-side{width:100%;height:100%;background:var(--ss-surface)}
.ss-side-head{padding:8px 6px 0 12px;flex-shrink:0}
.ss-side-head .q-btn{color:var(--ss-dim)}
.ss-strip{
  width:100%;flex:1 1 0;min-height:0;overflow-y:auto;padding:8px 10px 12px;
  background:var(--ss-surface)}
.ss-strip::-webkit-scrollbar{width:6px}
.ss-strip::-webkit-scrollbar-thumb{background:var(--ss-line);border-radius:3px}
.ss-thumb{
  position:relative;width:100%;flex-shrink:0;border:1px solid var(--ss-line);border-radius:8px;
  overflow:hidden;cursor:pointer;background:var(--ss-raised);
  transition:border-color .15s,transform .15s,box-shadow .15s}
.ss-thumb:hover{border-color:var(--ss-accent-deep);transform:translateY(-1px)}
.ss-thumb.ss-active{
  border-color:var(--ss-accent);
  box-shadow:0 0 0 1px var(--ss-accent),0 6px 18px rgba(93,179,240,.16)}
.ss-thumb-fallback{
  display:block;padding:18px 8px;font-size:10px;color:var(--ss-dim);
  text-align:center;word-break:break-all}
.ss-thumb-num{
  position:absolute;bottom:5px;left:6px;font-family:"IBM Plex Mono",monospace;
  font-size:10px;font-weight:600;color:var(--ss-dim);
  background:rgba(20,17,15,.85);padding:0 5px;border-radius:4px}
.ss-dot{position:absolute;top:6px;right:6px;width:9px;height:9px;border-radius:50%}
.ss-dot-ready{background:var(--ss-ok)}
.ss-dot-warning{background:var(--ss-warn)}
.ss-dot-error{background:var(--ss-err);box-shadow:0 0 8px var(--ss-err)}
.ss-dot-empty{background:transparent;border:1.5px solid var(--ss-dim)}
.ss-stage{width:100%;height:100%;padding:16px 24px 10px;align-items:center}
.ss-stage-inner{
  height:100%;
  width:min(100%, max(620px, calc((100vh - 230px) * .6667 * var(--ss-ar, 1.7778))))}
.ss-stage-view{
  flex:2 1 0;min-height:0;width:100%;
  display:flex;justify-content:center}
.ss-stage-img{width:100%;height:100%}
.ss-stage-img img{border-radius:6px}
.ss-counter{font-size:12px;color:var(--ss-dim);padding:0 8px;min-width:96px;text-align:center}
.ss-vsep{width:1px;height:20px;background:var(--ss-line);margin:0 8px}
.ss-audio{display:none}  /* invisible sound pipe — the transport buttons are the UI */
.ss-seek{flex:1 1 0;min-width:60px}
.ss-time{font-size:11px;color:var(--ss-dim);white-space:nowrap}
/* unattached-narration tray: a distinct warning-tinted panel so it stands out
   from the plain console sections around it */
.ss-tray{background:rgba(255,200,87,.07);border:1px solid rgba(255,200,87,.32);
  border-left:3px solid var(--ss-warn);border-radius:8px;padding:10px 12px}
.ss-tray-icon{color:var(--ss-warn);font-size:18px}
.ss-tray-title{font-size:12px;font-weight:600;letter-spacing:.04em;color:var(--ss-warn)}
.ss-tray-hint{font-size:11px;color:var(--ss-dim);line-height:1.4}
.ss-orphan{border:1px solid var(--ss-line);border-radius:6px;padding:6px 8px;
  background:var(--ss-surface)}
.ss-orphan-id{font-size:12px;font-weight:600;color:var(--ss-warn);
  font-family:"IBM Plex Mono",monospace}
.ss-orphan-text{font-size:12.5px;color:var(--ss-text);line-height:1.5;
  white-space:pre-wrap;word-break:break-word;user-select:text;cursor:text}
.ss-console{
  width:100%;height:100%;overflow-y:auto;padding:16px;
  background:var(--ss-surface)}
.ss-section{
  font-size:10px;font-weight:600;letter-spacing:.18em;text-transform:uppercase;
  color:var(--ss-dim);margin-top:4px}
.ss-id{font-size:15px;font-weight:600;color:var(--ss-accent)}
/* structured block editor: a scrollable column of utterance + pause cards */
.ss-blocks{flex:1 1 0;min-height:0;overflow-y:auto;padding-right:4px}
.ss-card{
  background:var(--ss-raised);border-radius:8px;padding:8px 10px;gap:4px;
  box-shadow:none;border:1px solid var(--ss-line)}
.ss-utext{flex:1 1 0;min-width:0}
.ss-utext textarea{line-height:1.6;font-size:15.5px;resize:none}
.ss-utt-opts{margin-top:2px}
.ss-uvoice{flex:0 0 162px}
.ss-upace{flex:0 0 122px}
.ss-udirect{flex:1 1 0;min-width:0}
/* the option-row widgets sit on a darker fill with a hairline so they read as
   editable fields instead of blending into the card */
.ss-utt-opts .q-field--filled .q-field__control{
  background:var(--ss-surface)!important;border:1px solid var(--ss-line)}
.ss-utt-opts .q-field--filled .q-field__control:hover{border-color:var(--ss-dim)}
.ss-utt-opts .q-field__native::placeholder,
.ss-utt-opts input::placeholder{color:var(--ss-dim);opacity:.45;font-style:italic}
.ss-seg-controls{flex:0 0 auto}
.ss-pause{border-style:dashed}
.ss-pause-icon{color:var(--ss-dim)}
.ss-pause-secs{width:96px}
.ss-transition{padding:2px 2px}
.ss-trans-label{font-size:10px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ss-dim);flex:0 0 auto}
.ss-trans-secs{width:84px}
.q-field--filled .q-field__control{background:var(--ss-raised)!important;border-radius:8px}
.ss-diag{font-family:"IBM Plex Mono",monospace;font-size:11px;line-height:1.4}
.ss-diag-err{color:var(--ss-err)}
.ss-diag-warn{color:var(--ss-warn)}
.ss-diag-info{color:var(--ss-dim)}
.ss-diag-ok{color:var(--ss-ok)}
.ss-export{color:#0c1117!important;font-weight:600}
textarea,input{caret-color:var(--ss-accent)}
.ss-flip{transform:scaleX(-1)}
/* narrow-window mode: opened side panes float over the stage instead of squeezing it */
.ss-overlay-left > .q-splitter__before{
  position:absolute;left:0;top:0;bottom:0;height:100%;z-index:40;
  box-shadow:10px 0 28px rgba(0,0,0,.5)}
.ss-overlay-right > .q-splitter__after{
  position:absolute;right:0;top:0;bottom:0;height:100%;z-index:40;
  box-shadow:-10px 0 28px rgba(0,0,0,.5)}
.ss-overlay-left > .q-splitter__separator,
.ss-overlay-right > .q-splitter__separator{display:none}
"""

_RESIZE_JS = """
<script>
(function () {
  let t;
  function report() {
    if (window.emitEvent) emitEvent('ss_resize', window.innerWidth);
  }
  window.addEventListener('resize', function () {
    clearTimeout(t);
    t = setTimeout(report, 150);
  });
  window.addEventListener('load', function () { setTimeout(report, 300); });
})();
</script>
"""

_GRAIN = (
    "body::after{content:'';position:fixed;inset:0;pointer-events:none;"
    f'z-index:1;opacity:.028;background-image:url("{_NOISE_SVG}")}}'
)

_ALL_DOTS = "ss-dot-error ss-dot-warning ss-dot-ready ss-dot-empty"


def build_editor(pdf_path: Path, sidecar_path: Path | None = None) -> EditorState:
    """Build the editor UI for *pdf_path* in the current page; return its state."""
    state = EditorState(pdf_path, sidecar_path=sidecar_path)
    _serve_media(state)

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
    ui.add_head_html(_FONTS_HTML + "<style>" + _CSS + _GRAIN + ar_css + "</style>" + _RESIZE_JS)

    # --- header: wordmark · deck · save flash · error pill ---
    with ui.header().classes("ss-header items-center justify-between no-wrap"):
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.html('<span class="ss-wordmark">slide<span class="ss-accent">Sonnet</span></span>')
            ui.label(pdf_path.name).classes("ss-chip ss-mono")
        with ui.row().classes("items-center gap-3 no-wrap"):
            saved_flash = ui.label("● saved").classes("ss-saved opacity-0")
            err_badge = ui.label().classes("ss-pill")
            # material's view_sidebar glyph puts the sidebar on the RIGHT; flip for the left pane
            strip_toggle = ui.button(icon="view_sidebar").props("flat round dense")
            strip_toggle.classes("ss-flip").mark("toggle-strip").tooltip("Show/hide filmstrip")
            console_toggle = ui.button(icon="view_sidebar").props("flat round dense")
            console_toggle.mark("toggle-console").tooltip("Show/hide console")

    # --- body: filmstrip | stage | console — draggable, collapsible panes ---
    strip_split = (
        ui.splitter(value=150, limits=(0, 400)).props("unit=px").classes("ss-main w-full ss-split")
    )
    strip_split.mark("split-strip")
    with strip_split.separator:
        ui.icon("drag_indicator").classes("ss-grip")

    thumb_cards: list[tuple[Any, Any]] = []
    with strip_split.before, ui.column().classes("ss-side no-wrap gap-0"):
        with ui.row().classes("ss-side-head w-full items-center justify-between no-wrap"):
            ui.label("Slides").classes("ss-section")
            collapse_strip = ui.button(icon="chevron_left").props("flat round dense size=sm")
            collapse_strip.mark("collapse-strip").tooltip("Collapse filmstrip")
        strip_col = ui.column().classes("ss-strip gap-2")

    def _build_strip() -> None:
        """(Re)build the filmstrip; thumbnails degrade to id tiles without pdftoppm."""
        images: list[Path] = []
        try:
            images = state.ensure_images()
        except Exception as exc:
            logger.warning("thumbnail render failed: %s", exc)
        thumb_cards.clear()
        strip_col.clear()
        with strip_col:
            for i, sid in enumerate(state.deck.pages):
                with ui.element("div").classes("ss-thumb").mark(f"thumb-{i}") as card:
                    if i < len(images):
                        ui.image(_media_url(state, images[i])).classes("w-full")
                    else:
                        ui.label(sid or f"page {i + 1}").classes("ss-thumb-fallback ss-mono")
                    dot = ui.element("div").classes("ss-dot")
                    ui.label(str(i + 1)).classes("ss-thumb-num")
                card.on("click", lambda _e=None, i=i: _jump(i))
                thumb_cards.append((card, dot))

    _build_strip()

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
                with ui.element("div").classes("ss-stage-view"):
                    slide_img = ui.image().classes("ss-stage-img").props('fit="contain" no-spinner')
                with ui.row().classes("w-full items-center no-wrap gap-3"):
                    id_label = ui.label().classes("ss-id ss-mono")
                    ui.space()
                    add_line_btn = ui.button(
                        "Line", icon="add", on_click=lambda: _add_segment("speech")
                    )
                    add_line_btn.props("flat dense no-caps").mark("add-utterance")
                    add_line_btn.tooltip("Add a spoken line")
                    add_pause_btn = ui.button(
                        "Pause", icon="hourglass_empty", on_click=lambda: _add_segment("pause")
                    )
                    add_pause_btn.props("flat dense no-caps").mark("add-pause")
                    add_pause_btn.tooltip("Add a silent pause")
                blocks_col = ui.column().classes("ss-blocks no-wrap gap-2 w-full")
                with ui.row().classes("w-full items-center no-wrap gap-1"):
                    prev_btn = ui.button(icon="chevron_left").props("flat round dense")
                    prev_btn.mark("Previous").tooltip("Back (←)")
                    page_label = ui.label().classes("ss-counter ss-mono")
                    next_btn = ui.button(icon="chevron_right").props("flat round dense")
                    next_btn.mark("Next").tooltip("Forward (→)")
                    ui.element("div").classes("ss-vsep")
                    gen_btn = ui.button(icon="graphic_eq").props("flat round dense")
                    gen_btn.mark("gen-slide")
                    with gen_btn:  # one tooltip, retext-ed when the button flips mode
                        gen_tip = ui.tooltip("Generate this slide's audio")
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
                collapse_console = ui.button(icon="chevron_right").props("flat round dense size=sm")
                collapse_console.mark("collapse-console").tooltip("Collapse console")
            diag_box = ui.column().classes("w-full gap-1")
            ui.label("Audio · this slide").classes("ss-section")
            audio_status = ui.label().classes("ss-diag ss-diag-info")
            tray_box = ui.column().classes("w-full gap-1")
            tray_box.mark("orphan-tray")
            tray_box.visible = False
            ui.space()
            gen_all_btn = ui.button("Generate all", icon="library_music").classes("w-full")
            gen_all_btn.props("flat no-caps")
            export_btn = ui.button("Export video", icon="movie").classes("w-full ss-export")
            export_btn.props("unelevated no-caps color=primary")

    # --- footer: engine · sidecar · hints ---
    with ui.footer().classes("ss-footer no-wrap"):
        ui.label(f"engine {state.config.tts.backend}").classes("ss-mono ss-foot")
        ui.element("div").classes("ss-vsep")
        ui.label(state.sidecar_path.name).classes("ss-mono ss-foot")
        ui.space()
        ui.label("←→ or ↑↓ slides · drag dividers · saves automatically").classes("ss-mono ss-foot")

    # ---- rendering helpers ----
    cues: list[tuple[float, str]] = []
    busy = False
    playback = PlaybackController()
    track_duration = 0.0
    scrubbing = False  # user is dragging the seek handle; don't fight them
    # collectors for the structured block editor, refreshed by _render_blocks()
    seg_collectors: list[Callable[[], Segment]] = []
    transition_getters: dict[str, Callable[[], Transition]] = {}

    def _pace_value(v: str | None) -> Pace | None:
        return None if v in (None, "", "normal") else v  # type: ignore[return-value]

    def render() -> None:
        _render_side()
        _render_blocks()

    def _render_side() -> None:
        """Everything but the block editor — safe to call on a silent commit."""
        page_label.set_text(f"Slide {state.index + 1} / {state.page_count}")
        if state.error_count:
            err_badge.set_text(f"⛔ {state.error_count} errors")
            err_badge.classes(remove="ss-pill-ok", add="ss-pill-err")
        else:
            err_badge.set_text("✓ no errors")
            err_badge.classes(remove="ss-pill-err", add="ss-pill-ok")
        id_label.set_text(state.current_id or "(no slide id)")
        editable = bool(state.current_id)
        add_line_btn.set_enabled(editable)
        add_pause_btn.set_enabled(editable)
        try:
            img = state.current_image()
            if img is not None:
                slide_img.set_source(_media_url(state, img))
        except Exception as exc:  # rasterize may fail without pdftoppm
            logger.warning("image render failed: %s", exc)
        for i, (card, dot) in enumerate(thumb_cards):
            if i >= len(state.deck.pages):
                break  # strip is briefly stale after a recompile; poll rebuilds it
            if i == state.index:
                card.classes(add="ss-active")
            else:
                card.classes(remove="ss-active")
            dot.classes(remove=_ALL_DOTS, add=f"ss-dot-{state.status_for(state.deck.pages[i])}")
        _scroll_strip()
        _render_diagnostics()
        _render_audio_status()
        _render_orphan_tray()
        _sync_transport()

    # ---- structured block editor (utterances, pauses, transitions) ----------
    def _transition_row(which: str, transition: Transition, disabled: bool) -> None:
        label = "Transition in" if which == "in" else "Transition out"
        with ui.row().classes("w-full items-center no-wrap gap-2 ss-transition"):
            ui.label(label).classes("ss-trans-label ss-mono")
            kind = (
                ui.toggle(["cut", "crossfade"], value=transition.kind)
                .props("dense no-caps unelevated")
                .mark(f"trans-{which}")
            )
            secs = (
                ui.number(value=transition.seconds or 0.5, min=0, step=0.1, format="%.1f")
                .props("dense filled")
                .classes("ss-trans-secs")
            )
            secs.bind_visibility_from(kind, "value", backward=lambda v: v == "crossfade")
            if disabled:
                kind.disable()
                secs.disable()
            kind.on_value_change(lambda: _commit())
            secs.on("blur", lambda: _commit())

        def collect() -> Transition:
            k: str = kind.value or "cut"
            seconds = float(secs.value or 0.0) if k == "crossfade" else 0.0
            return Transition(kind=k, seconds=seconds)  # type: ignore[arg-type]

        transition_getters[which] = collect

    def _reorder_controls(index: int, disabled: bool) -> None:
        """Up/down reorder arrows — placed on the *left* of a card."""
        up = ui.button(icon="keyboard_arrow_up", on_click=lambda: _move_segment(index, -1))
        up.props("flat round dense size=sm").mark(f"seg-up-{index}").tooltip("Move up")
        down = ui.button(icon="keyboard_arrow_down", on_click=lambda: _move_segment(index, 1))
        down.props("flat round dense size=sm").mark(f"seg-down-{index}").tooltip("Move down")
        if disabled:
            up.disable()
            down.disable()

    def _delete_control(index: int, disabled: bool) -> None:
        """Destructive delete — placed on the *right*, far from the reorder arrows."""
        trash = ui.button(icon="delete", on_click=lambda: _delete_segment(index))
        trash.props("flat round dense size=sm color=negative").mark(f"seg-del-{index}")
        trash.tooltip("Delete this block")
        if disabled:
            trash.disable()

    def _utterance_card(index: int, seg: Segment, disabled: bool) -> Callable[[], Segment]:
        with ui.card().classes("ss-card ss-utterance w-full").mark(f"utterance-{index}"):
            with ui.row().classes("w-full items-start no-wrap gap-1"):
                with ui.column().classes("gap-0 ss-seg-controls"):
                    _reorder_controls(index, disabled)
                text = (
                    ui.textarea(value=seg.text, placeholder="Spoken words…")
                    .props("filled autogrow dense")
                    .classes("ss-mono ss-utext")
                    .mark(f"utext-{index}")
                )
                with ui.column().classes("gap-0 ss-seg-controls"):
                    _delete_control(index, disabled)
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
                        "filled dense options-dense clearable hide-bottom-space "
                        'title="Voice (type to filter; clear for the deck default)"'
                    )
                    .classes("ss-mono ss-uvoice")
                    .mark(f"uvoice-{index}")
                )
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
            text.on("blur", lambda: _commit())
            voice.on_value_change(lambda: _commit())
            pace.on_value_change(lambda: _commit())
            direct.on("blur", lambda: _commit())

        def collect() -> Segment:
            return Segment.speech(
                text.value or "",
                voice=(voice.value or "").strip() or None,
                pace=_pace_value(pace.value),
                direction=(direct.value or "").strip() or None,
            )

        return collect

    def _pause_card(index: int, seg: Segment, disabled: bool) -> Callable[[], Segment]:
        with ui.card().classes("ss-card ss-pause w-full").mark(f"pause-{index}"):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                with ui.row().classes("gap-0 no-wrap ss-seg-controls"):
                    _reorder_controls(index, disabled)
                ui.icon("hourglass_empty").classes("ss-pause-icon")
                secs = (
                    ui.number(value=seg.seconds, min=0, step=0.1, format="%.1f", suffix="s")
                    .props("filled dense")
                    .classes("ss-pause-secs")
                    .mark(f"pause-secs-{index}")
                )
                ui.label("silence").classes("ss-diag ss-diag-info")
                ui.space()
                _delete_control(index, disabled)
            if disabled:
                secs.disable()
            secs.on("blur", lambda: _commit())

        def collect() -> Segment:
            return Segment.pause(max(0.0, float(secs.value or 0.0)))

        return collect

    def _render_blocks() -> None:
        blocks_col.clear()
        seg_collectors.clear()
        transition_getters.clear()
        block = state.current_block
        disabled = not state.current_id
        with blocks_col:
            if not state.current_id:
                ui.label(
                    "This page has no slide-id — add \\ssid in the source to narrate it."
                ).classes("ss-diag ss-diag-warn")
                return
            _transition_row("in", block.transition_in, disabled)
            for i, seg in enumerate(block.segments):
                if seg.is_speech:
                    seg_collectors.append(_utterance_card(i, seg, disabled))
                else:
                    seg_collectors.append(_pause_card(i, seg, disabled))
            if not block.segments:
                ui.label("(empty — add a line or a pause above)").classes("ss-diag ss-diag-info")
            _transition_row("out", block.transition_out, disabled)

    def _collect() -> tuple[list[Segment], Transition, Transition]:
        segs = [c() for c in seg_collectors]
        tin = transition_getters["in"]() if "in" in transition_getters else Transition()
        tout = transition_getters["out"]() if "out" in transition_getters else Transition()
        return segs, tin, tout

    def _add_segment(kind: str) -> None:
        segs, tin, tout = _collect()
        segs.append(Segment.speech("") if kind == "speech" else Segment.pause(1.0))
        if state.replace_block(segs, transition_in=tin, transition_out=tout):
            render()

    def _delete_segment(index: int) -> None:
        segs, tin, tout = _collect()
        if 0 <= index < len(segs):
            del segs[index]
        if state.replace_block(segs, transition_in=tin, transition_out=tout):
            render()

    def _move_segment(index: int, delta: int) -> None:
        segs, tin, tout = _collect()
        j = index + delta
        if 0 <= index < len(segs) and 0 <= j < len(segs):
            segs[index], segs[j] = segs[j], segs[index]
            if state.replace_block(segs, transition_in=tin, transition_out=tout):
                render()

    def _render_orphan_tray() -> None:
        """Narration whose slide vanished in a recompile: keep it visible and actionable."""
        tray_box.clear()
        orphans = state.orphan_blocks()
        tray_box.visible = bool(orphans)
        if not orphans:
            return
        with tray_box, ui.column().classes("ss-tray w-full gap-2 no-wrap"):
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
                        copy.on_click(lambda text=full: _copy_text(text))
                        trash = ui.button(icon="delete").props("flat round dense size=sm")
                        trash.mark(f"delete-{block.slide_id}").tooltip("Delete this narration")
                        trash.on_click(lambda sid=block.slide_id: _delete_orphan_dialog(sid))
                    # full text, selectable so it can always be copied by hand
                    ui.label(full).classes("ss-orphan-text").mark(f"orphan-text-{block.slide_id}")
                    with ui.row().classes("w-full items-center no-wrap gap-1"):
                        here = ui.button(
                            "Append here",
                            icon="south",
                            on_click=lambda sid=block.slide_id: _append_orphan_here(sid),
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
                        attach.on_click(lambda sid=block.slide_id: _attach_orphan_dialog(sid))

    def _copy_text(text: str) -> None:
        ui.clipboard.write(text)
        ui.notify("Copied narration text", type="info")

    def _append_orphan_here(orphan_id: str) -> None:
        target = state.current_id
        try:
            state.append_orphan_to_current(orphan_id)
        except ValueError as exc:
            ui.notify(str(exc), type="warning")
            return
        ui.notify(f"Appended '@{orphan_id}' to '{target}'", type="positive")
        render()

    def _attach_orphan_dialog(orphan_id: str) -> None:
        candidates = state.unnarrated_pages()
        if not candidates:
            ui.notify("No un-narrated slide to attach to", type="warning")
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Attach narration '@{orphan_id}' to which slide?")
            target = ui.select(candidates, value=candidates[0]).classes("w-full")
            target.mark("attach-target")

            def _do_attach() -> None:
                dialog.close()
                try:
                    state.attach_orphan(orphan_id, str(target.value))
                except ValueError as exc:
                    ui.notify(str(exc), type="warning")
                    return
                ui.notify(f"Narration attached to '{target.value}'", type="positive")
                render()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Attach", on_click=_do_attach).props("no-caps").mark("attach-confirm")
        dialog.open()

    def _delete_orphan_dialog(orphan_id: str) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(
                f"Delete the unattached narration '@{orphan_id}'? "
                "This removes its text from the sidecar."
            )

            def _do_delete() -> None:
                dialog.close()
                try:
                    state.delete_orphan(orphan_id)
                except ValueError as exc:
                    ui.notify(str(exc), type="warning")
                    return
                ui.notify(f"Deleted narration '@{orphan_id}'", type="info")
                render()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                delete_btn = ui.button("Delete", on_click=_do_delete).props(
                    "no-caps color=negative"
                )
                delete_btn.mark("delete-confirm")
        dialog.open()

    def _render_audio_status() -> None:
        total = len(state.current_block.speech_segments)
        audio_status.classes(remove="ss-diag-ok ss-diag-warn ss-diag-info")
        if total == 0:
            audio_status.set_text("no speech on this slide")
            audio_status.classes(add="ss-diag-info")
            return
        done = total - state.uncached_count(state.current_id)
        audio_status.set_text(f"{done} of {total} generated")
        audio_status.classes(add="ss-diag-ok" if done == total else "ss-diag-warn")

    def _scroll_strip() -> None:
        card = thumb_cards[state.index][0]
        try:  # best-effort; no JS client in tests
            ui.run_javascript(
                f"document.getElementById('c{card.id}')"
                "?.scrollIntoView({block: 'nearest', behavior: 'smooth'})"
            )
        except Exception:
            pass

    def _render_diagnostics() -> None:
        diag_box.clear()
        with diag_box:
            diags = state.diagnostics_for_current()
            if not diags:
                ui.label("no issues on this slide").classes("ss-diag ss-diag-ok")
            for d in diags:
                css = {"error": "ss-diag-err", "warning": "ss-diag-warn"}.get(
                    d.severity, "ss-diag-info"
                )
                ui.label(f"{d.severity}: {d.message}").classes(f"ss-diag {css}")

    def save_current() -> None:
        """Flush the open editor widgets to disk without rebuilding the cards."""
        if not seg_collectors and "in" not in transition_getters:
            return  # nothing built (e.g. unmarked page)
        segs, tin, tout = _collect()
        if state.replace_block(segs, transition_in=tin, transition_out=tout):
            saved_flash.classes(remove="opacity-0")
            ui.timer(1.2, lambda: saved_flash.classes(add="opacity-0"), once=True)
            _render_side()

    def _commit() -> None:
        save_current()

    # ---- navigation (each saves first) ----
    def _jump(index: int) -> None:
        save_current()
        moved = max(0, min(index, state.page_count - 1)) != state.index
        state.go(index)
        action = playback.nav_action() if moved else "none"
        if action == "seek" and cues:  # deck track loaded: follow to this slide's cue
            start = cue_start(cues, state.current_id)
            if start is not None:
                audio.seek(start)
        elif action == "clear":  # a single-slide track belongs to its slide — reset
            _stop_playback()
        render()

    def _go(delta: int) -> None:
        _jump(state.index + delta)

    # ---- sidebar collapse/restore ----
    remembered = {"strip": 0.0, "console": 0.0}

    def _sync_pane_toggles() -> None:
        for splitter, btn in ((strip_split, strip_toggle), (console_split, console_toggle)):
            is_open = float(splitter.value or 0.0) > 2.0
            btn.props(f"color={'primary' if is_open else 'grey-7'}")

    def _toggle_pane(splitter: Any, key: str, default: float) -> None:
        width, remembered[key] = toggled_width(
            float(splitter.value or 0.0), remembered[key], default=default
        )
        splitter.value = width
        _sync_pane_toggles()

    # ---- narrow windows: auto-collapse panes; opened panes overlay the stage ----
    responsive = ResponsivePanes()
    panes: dict[str, tuple[Any, float, str]] = {
        "strip": (strip_split, 150.0, "ss-overlay-left"),
        "console": (console_split, 264.0, "ss-overlay-right"),
    }

    def _set_pane(key: str, *, open_pane: bool) -> None:
        splitter, default, _cls = panes[key]
        current = float(splitter.value or 0.0)
        if open_pane and current <= 2.0:
            splitter.value = remembered[key] if remembered[key] > 2.0 else default
        elif not open_pane and current > 2.0:
            remembered[key] = current
            splitter.value = 0.0

    last_width = {"px": 0.0}

    def _apply_limits() -> None:
        """Cap drag limits so panes can't push the stage below its minimum."""
        width = last_width["px"]
        if not width:
            return
        if responsive.narrow:  # overlay mode: panes float over the stage, no cap needed
            strip_split.props(f"limits=[0,{_STRIP_MAX:.0f}]")
            console_split.props(f"limits=[0,{_CONSOLE_MAX:.0f}]")
            return
        avail = max(0.0, width - _STAGE_RESERVE)
        strip_w = float(strip_split.value or 0.0)
        console_w = float(console_split.value or 0.0)
        strip_split.props(f"limits=[0,{min(_STRIP_MAX, max(0.0, avail - console_w)):.0f}]")
        console_split.props(f"limits=[0,{min(_CONSOLE_MAX, max(0.0, avail - strip_w)):.0f}]")

    def _on_resize(e: Any) -> None:
        width = float(e.args)
        last_width["px"] = width
        open_now = {k: float(s.value or 0.0) > 2.0 for k, (s, _d, _c) in panes.items()}
        to_collapse, to_restore = responsive.update(width, open_now)
        for key in to_collapse:
            _set_pane(key, open_pane=False)
        for key in to_restore:
            _set_pane(key, open_pane=True)
        if not responsive.narrow:  # stretched panes yield before the stage shrinks
            strip_w, console_w = clamp_panel_widths(
                width, float(strip_split.value or 0.0), float(console_split.value or 0.0)
            )
            strip_split.value = strip_w
            console_split.value = console_w
        for _key, (splitter, _d, cls) in panes.items():
            if responsive.narrow:
                splitter.classes(add=cls)
            else:
                splitter.classes(remove=cls)
        _apply_limits()
        _sync_pane_toggles()

    ui.on("ss_resize", _on_resize)

    def _on_key(e: KeyEventArguments) -> None:
        if not e.action.keydown:
            return
        delta = nav_direction(e.key)
        if delta:
            _go(delta)

    # ---- actions (saved first, run off the event loop, one at a time) ----
    async def _run(btn: Any, work: Callable[[], str]) -> None:
        nonlocal busy
        if busy:
            return
        busy = True
        save_current()
        btn.props("loading")
        try:
            ui.notify(await run.io_bound(work), type="positive")
        except NotImplementedError as exc:
            ui.notify(str(exc), type="warning")
        except Exception as exc:  # surface backend errors without crashing the UI
            logger.exception("action failed")
            ui.notify(f"Error: {exc}", type="negative")
        finally:
            busy = False
            btn.props(remove="loading")
            render()

    def _generate_one() -> str:
        # Fully cached → the button is a re-generate affordance: force a fresh take.
        force = state.current_block.has_speech and state.uncached_count(state.current_id) == 0
        n = state.synth_current(force=force)
        verb = "Re-generated" if force else "Synthesized"
        return f"{verb} {n} clip(s) for {state.current_id}"

    def _generate_all() -> str:
        n = state.synth_all()
        return f"Synthesized {n} new clip(s) across the deck"

    def _export_work() -> str:
        out = state.pdf_path.with_suffix(".mp4")
        result = state.export(out)
        return f"Exported {out.name} ({result.duration:.1f}s)"

    async def _confirm_paid_synth(count: int) -> bool:
        backend = state.config.tts.backend
        with ui.dialog() as dialog, ui.card():
            ui.label(
                f"{count} segment(s) aren't cached — synthesizing them with "
                f"{backend} will spend API credits."
            )
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button("Generate & play", on_click=lambda: dialog.submit(True)).props("no-caps")
        return bool(await dialog)

    def _sync_transport() -> None:
        """Play buttons mirror the player: the loaded track's button shows pause.

        Play grays out when the slide has no speech. Generate stays live whenever
        there's speech: with uncached segments it generates; once everything is
        cached it flips to a re-generate affordance (fresh take / refresh cache).
        """
        one_active = playback.playing and playback.loaded_key == state.current_id
        play_one.props(f"icon={'pause' if one_active else 'play_arrow'}")
        deck_active = playback.playing and playback.loaded_key == "deck"
        play_all.props(f"icon={'pause' if deck_active else 'playlist_play'}")
        has_speech = state.current_block.has_speech
        play_one.set_enabled(has_speech)
        regenerate = has_speech and state.uncached_count(state.current_id) == 0
        gen_btn.set_enabled(has_speech)
        gen_btn.props(f"icon={'autorenew' if regenerate else 'graphic_eq'}")
        gen_tip.set_text(
            "Re-generate this slide's audio" if regenerate else "Generate this slide's audio"
        )

    def _fmt_clock(t: float) -> str:
        s = max(0, int(t))
        return f"{s // 60}:{s % 60:02d}"

    def _sync_clock(t: float) -> None:
        if track_duration <= 0:
            return
        if not scrubbing:
            pos_slider.value = min(1.0, t / track_duration)
        time_label.set_text(f"{_fmt_clock(t)} / {_fmt_clock(track_duration)}")

    def _stop_playback() -> None:
        nonlocal cues, track_duration
        playback.stop()  # cancels a pending play too — Stop always wins
        audio.pause()
        cues = []
        track_duration = 0.0
        pos_slider.value = 0.0
        pos_slider.props("disable")
        time_label.set_text("")
        _sync_transport()

    def _request_preview(btn: Any, whole_deck: bool) -> None:
        """Claim the player synchronously at click time, then build off the loop.

        Claiming the token here (not inside the task) means a Stop click that
        lands before the build even starts still cancels it.
        """
        nonlocal busy
        if not whole_deck and not state.current_block.has_speech:
            ui.notify("This slide has no narration to play", type="info")
            return
        key = "deck" if whole_deck else state.current_id
        action = playback.press_action(key)
        if action == "pause":
            audio.pause()
            playback.set_playing(False)  # optimistic; the browser event confirms
            _sync_transport()
            return
        if action == "resume":
            audio.play()
            playback.set_playing(True)
            _sync_transport()
            return
        if busy:
            return
        busy = True
        token = playback.begin(deck=whole_deck)
        audio.pause()  # a rolling preview yields to the new request right away
        playback.set_playing(False)
        _sync_transport()
        background_tasks.create(_preview(btn, whole_deck, token))

    client = ui.context.client  # background tasks must re-enter the page's slot stack

    async def _preview(btn: Any, whole_deck: bool, token: int) -> None:
        nonlocal busy, cues, track_duration
        with client:
            save_current()
            btn.props("loading")
        try:
            if state.tts_is_paid:
                count = (
                    state.uncached_total() if whole_deck else state.uncached_count(state.current_id)
                )
                with client:
                    if count and not await _confirm_paid_synth(count):
                        return
            preview = await run.io_bound(
                state.preview_deck if whole_deck else state.preview_current
            )
            with client:
                if not playback.may_start(token):  # user pressed Stop while building
                    ui.notify("Preview stopped", type="info")
                    return
                cues = preview.cues if whole_deck else []
                # every preview renders to the same track path — vary the URL so
                # the browser refetches instead of replaying the previous audio
                audio.set_source(f"{_media_url(state, preview.track)}?v={token}")
                playback.mark_loaded("deck" if whole_deck else state.current_id)
                track_duration = preview.total_duration
                pos_slider.value = 0.0
                pos_slider.props(remove="disable")
                _sync_clock(0.0)
                audio.play()
                playback.set_playing(True)  # optimistic; the browser event confirms
                _sync_transport()
                ui.notify(f"Preview ready ({preview.total_duration:.1f}s)", type="positive")
        except Exception as exc:
            logger.exception("preview failed")
            with client:
                ui.notify(f"Error: {exc}", type="negative")
        finally:
            busy = False
            with client:
                btn.props(remove="loading")
                render()

    # clock/scrubber sync + cue-driven image flip during deck preview
    def _on_timeupdate(e: Any) -> None:
        t = float(e.args) if e.args is not None else 0.0
        _sync_clock(t)
        if not cues:
            return
        current = cues[0][1]
        for start, sid in cues:
            if t + 1e-6 >= start:
                current = sid
            else:
                break
        if current in state.deck.pages:
            idx = state.deck.pages.index(current)
            if idx != state.index:
                save_current()  # don't clobber narration typed during playback
                state.index = idx
                render()

    def _on_player_state(playing: bool) -> None:
        playback.set_playing(playing)
        _sync_transport()

    def _on_scrub_pan(e: Any) -> None:
        nonlocal scrubbing
        scrubbing = e.args == "start"

    def _on_scrub(e: Any) -> None:
        if track_duration > 0:
            audio.seek(float(e.args) * track_duration)

    # NiceGUI's `args` filter only reaches top-level event keys, so a real
    # browser can't deliver `event.target.currentTime` that way (the handler
    # would receive an empty dict). Transform client-side and emit the number.
    audio.on("timeupdate", _on_timeupdate, js_handler="(e) => emit(e.target.currentTime)")
    audio.on("play", lambda: _on_player_state(True))
    audio.on("pause", lambda: _on_player_state(False))
    audio.on("ended", lambda: _on_player_state(False))
    pos_slider.on("pan", _on_scrub_pan)
    pos_slider.on("change", _on_scrub)  # fires on release: one seek per scrub
    prev_btn.on_click(lambda: _go(-1))
    next_btn.on_click(lambda: _go(1))
    play_one.on_click(lambda: _request_preview(play_one, False))
    play_all.on_click(lambda: _request_preview(play_all, True))
    stop_btn.on_click(lambda: _stop_playback())
    gen_btn.on_click(lambda: _run(gen_btn, _generate_one))
    gen_all_btn.on_click(lambda: _run(gen_all_btn, _generate_all))
    export_btn.on_click(lambda: _run(export_btn, _export_work))

    # ---- live reload of deck sources (PDF recompile, sidecar/config edits) ----
    async def _poll_sources() -> None:
        if busy:  # don't yank the deck out from under a synth/export
            return
        changes = await run.io_bound(state.external_changes)
        if not changes:
            return
        if "sidecar" not in changes:
            # a recompile is landing: flush typing first, so narration for a
            # dropped slide survives as an unattached block instead of vanishing.
            # (never on sidecar changes — that would clobber the external edit)
            save_current()
        if not await run.io_bound(state.poll_sources):
            return
        try:
            await run.io_bound(state.ensure_images)  # rasterize off the event loop
        except Exception:
            pass  # _build_strip degrades to id tiles
        _build_strip()
        render()
        ui.notify("Deck files changed on disk — reloaded", type="info")

    ui.timer(1.0, _poll_sources)

    strip_toggle.on_click(lambda: _toggle_pane(strip_split, "strip", 150.0))
    console_toggle.on_click(lambda: _toggle_pane(console_split, "console", 264.0))
    collapse_strip.on_click(lambda: _toggle_pane(strip_split, "strip", 150.0))
    collapse_console.on_click(lambda: _toggle_pane(console_split, "console", 264.0))

    def _on_pane_drag() -> None:
        _apply_limits()
        _sync_pane_toggles()

    strip_split.on_value_change(lambda _e: _on_pane_drag())
    console_split.on_value_change(lambda _e: _on_pane_drag())
    ui.keyboard(on_key=_on_key)

    render()
    _sync_pane_toggles()
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
            app.on_startup(lambda o=app_opener: _launch_browser(o, url))
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
            app.on_startup(lambda o=opener: _launch_browser(o, url))
        elif not show and wsl:
            logger.info(
                "WSL detected and no browser configured — open %s in your Windows browser "
                "(install 'wslview', or pass --browser / --app to auto-open).",
                url,
            )

    print(f"slideSonnet editor running at {url}  (Ctrl-C to stop)")
    ui.run(host=host, port=port, title="slideSonnet", reload=False, show=show)


def _launch_browser(opener: list[str], url: str) -> None:
    """Open *url* with the configured command, swallowing launch errors."""
    cmd = apply_url(opener, url)
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        logger.warning("Could not launch browser %r: %s — open %s manually.", cmd, exc, url)
