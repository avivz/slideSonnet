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
from typing import Any

from nicegui import app, run, ui
from nicegui.events import KeyEventArguments

from slidesonnet.cache import render_dir
from slidesonnet.gui.state import EditorState, cue_start
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
  position:relative;width:100%;border:1px solid var(--ss-line);border-radius:8px;
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
.ss-audio{flex:1 1 0;min-width:0;height:36px;color-scheme:dark}
.ss-console{
  width:100%;height:100%;overflow-y:auto;padding:16px;
  background:var(--ss-surface)}
.ss-section{
  font-size:10px;font-weight:600;letter-spacing:.18em;text-transform:uppercase;
  color:var(--ss-dim);margin-top:4px}
.ss-id{font-size:15px;font-weight:600;color:var(--ss-accent)}
.ss-voice{width:200px}
.ss-body{flex:1 1 0;min-height:0;width:100%;display:flex;flex-direction:column}
.ss-body .q-field__inner,.ss-body .q-field__control,
.ss-body .q-field__control-container{height:100%}
.ss-body textarea{height:100%!important;resize:none;line-height:1.7;font-size:16.5px}
.q-field--filled .q-field__control{background:var(--ss-raised)!important;border-radius:8px}
.ss-diag{font-family:"IBM Plex Mono",monospace;font-size:11px;line-height:1.4}
.ss-diag-err{color:var(--ss-err)}
.ss-diag-warn{color:var(--ss-warn)}
.ss-diag-info{color:var(--ss-dim)}
.ss-diag-ok{color:var(--ss-ok)}
.ss-export{color:#0c1117!important;font-weight:600}
.ss-pace .q-btn{color:var(--ss-dim)}
.ss-pace .q-btn.bg-primary{color:#0c1117!important;font-weight:600}
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
            strip_toggle = ui.button(icon="view_sidebar").props("flat round dense")
            strip_toggle.mark("toggle-strip").tooltip("Show/hide filmstrip")
            console_toggle = ui.button(icon="view_sidebar").props("flat round dense")
            console_toggle.classes("ss-flip").mark("toggle-console").tooltip("Show/hide console")

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
                    voice = (
                        ui.input(
                            label="Voice",
                            placeholder="default",
                            autocomplete=sorted(state.config.voices),
                        )
                        .classes("ss-voice ss-mono")
                        .props("filled dense")
                    )
                    pace = (
                        ui.toggle(["slow", "normal", "fast"], value="normal")
                        .classes("ss-pace")
                        .props("no-caps dense unelevated toggle-color=primary")
                    )
                body = (
                    ui.textarea(placeholder="Speak this slide…  use [pause 1.5] for silence")
                    .classes("ss-mono ss-body")
                    .props("filled")
                )
                with ui.row().classes("w-full items-center no-wrap gap-1"):
                    prev_btn = ui.button(icon="chevron_left").props("flat round dense")
                    prev_btn.mark("Previous").tooltip("Back (←)")
                    page_label = ui.label().classes("ss-counter ss-mono")
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
                    audio = ui.audio("").props("controls").classes("ss-audio")
                    audio.visible = False

        with console_split.after, ui.column().classes("ss-console gap-3 no-wrap"):
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label("Checks").classes("ss-section")
                collapse_console = ui.button(icon="chevron_right").props("flat round dense size=sm")
                collapse_console.mark("collapse-console").tooltip("Collapse console")
            diag_box = ui.column().classes("w-full gap-1")
            ui.space()
            gen_btn = ui.button("Generate", icon="graphic_eq").classes("w-full")
            gen_btn.props("outline no-caps")
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
        ui.label("← → slides · drag dividers · saves automatically").classes("ss-mono ss-foot")

    # ---- rendering helpers ----
    cues: list[tuple[float, str]] = []
    busy = False
    playing = False  # deck-preview audio is rolling (nav seeks instead of just flipping)

    def render() -> None:
        page_label.set_text(f"Slide {state.index + 1} / {state.page_count}")
        if state.error_count:
            err_badge.set_text(f"⛔ {state.error_count} errors")
            err_badge.classes(remove="ss-pill-ok", add="ss-pill-err")
        else:
            err_badge.set_text("✓ no errors")
            err_badge.classes(remove="ss-pill-err", add="ss-pill-ok")
        id_label.set_text(state.current_id)
        body.value = state.body_text
        voice.value = state.voice
        pace.value = state.pace
        try:
            img = state.current_image()
            if img is not None:
                slide_img.set_source(_media_url(state, img))
        except Exception as exc:  # rasterize may fail without pdftoppm
            logger.warning("image render failed: %s", exc)
        for i, (card, dot) in enumerate(thumb_cards):
            if i == state.index:
                card.classes(add="ss-active")
            else:
                card.classes(remove="ss-active")
            dot.classes(remove=_ALL_DOTS, add=f"ss-dot-{state.status_for(state.deck.pages[i])}")
        _scroll_strip()
        _render_diagnostics()

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
                ui.label("all good").classes("ss-diag ss-diag-ok")
            for d in diags:
                css = {"error": "ss-diag-err", "warning": "ss-diag-warn"}.get(
                    d.severity, "ss-diag-info"
                )
                ui.label(f"{d.severity}: {d.message}").classes(f"ss-diag {css}")

    def save_current() -> None:
        state.save(body.value or "", voice=voice.value or "", pace=pace.value or "normal")
        saved_flash.classes(remove="opacity-0")
        ui.timer(1.2, lambda: saved_flash.classes(add="opacity-0"), once=True)

    # ---- navigation (each saves first) ----
    def _jump(index: int) -> None:
        save_current()
        state.go(index)
        if cues and playing:  # deck preview rolling: seek the track to this slide's cue
            start = cue_start(cues, state.current_id)
            if start is not None:
                audio.seek(start)
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

    def _on_resize(e: Any) -> None:
        width = float(e.args)
        open_now = {k: float(s.value or 0.0) > 2.0 for k, (s, _d, _c) in panes.items()}
        to_collapse, to_restore = responsive.update(width, open_now)
        for key in to_collapse:
            _set_pane(key, open_pane=False)
        for key in to_restore:
            _set_pane(key, open_pane=True)
        for _key, (splitter, _d, cls) in panes.items():
            if responsive.narrow:
                splitter.classes(add=cls)
            else:
                splitter.classes(remove=cls)
        _sync_pane_toggles()

    ui.on("ss_resize", _on_resize)

    def _on_key(e: KeyEventArguments) -> None:
        if not e.action.keydown:
            return
        if e.key.arrow_left:
            _go(-1)
        elif e.key.arrow_right:
            _go(1)

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
        n = state.synth_current()
        return f"Synthesized {n} new clip(s) for {state.current_id}"

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

    async def _preview(btn: Any, whole_deck: bool) -> None:
        nonlocal busy, cues
        if busy:
            return
        busy = True
        save_current()
        btn.props("loading")
        try:
            if state.tts_is_paid:
                count = (
                    state.uncached_total() if whole_deck else state.uncached_count(state.current_id)
                )
                if count and not await _confirm_paid_synth(count):
                    return
            preview = await run.io_bound(
                state.preview_deck if whole_deck else state.preview_current
            )
            cues = preview.cues if whole_deck else []
            audio.set_source(_media_url(state, preview.track))
            audio.visible = True
            audio.play()
            ui.notify(f"Preview ready ({preview.total_duration:.1f}s)", type="positive")
        except Exception as exc:
            logger.exception("preview failed")
            ui.notify(f"Error: {exc}", type="negative")
        finally:
            busy = False
            btn.props(remove="loading")
            render()

    # cue-driven image flip during deck preview
    def _on_timeupdate(e: Any) -> None:
        if not cues:
            return
        t = float(e.args) if e.args is not None else 0.0
        current = cues[0][1]
        for start, sid in cues:
            if t + 1e-6 >= start:
                current = sid
            else:
                break
        if current in state.deck.pages:
            idx = state.deck.pages.index(current)
            if idx != state.index:
                state.index = idx
                render()

    def _set_playing(value: bool) -> None:
        nonlocal playing
        playing = value

    audio.on("timeupdate", _on_timeupdate, args=["target.currentTime"])
    audio.on("play", lambda: _set_playing(True))
    audio.on("pause", lambda: _set_playing(False))
    audio.on("ended", lambda: _set_playing(False))
    prev_btn.on_click(lambda: _go(-1))
    next_btn.on_click(lambda: _go(1))
    play_one.on_click(lambda: _preview(play_one, False))
    play_all.on_click(lambda: _preview(play_all, True))
    stop_btn.on_click(lambda: audio.pause())
    gen_btn.on_click(lambda: _run(gen_btn, _generate_one))
    gen_all_btn.on_click(lambda: _run(gen_all_btn, _generate_all))
    export_btn.on_click(lambda: _run(export_btn, _export_work))

    # ---- live reload of deck sources (PDF recompile, sidecar/config edits) ----
    async def _poll_sources() -> None:
        if busy:  # don't yank the deck out from under a synth/export
            return
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

    body.on("blur", lambda: save_current())
    strip_toggle.on_click(lambda: _toggle_pane(strip_split, "strip", 150.0))
    console_toggle.on_click(lambda: _toggle_pane(console_split, "console", 264.0))
    collapse_strip.on_click(lambda: _toggle_pane(strip_split, "strip", 150.0))
    collapse_console.on_click(lambda: _toggle_pane(console_split, "console", 264.0))
    strip_split.on_value_change(lambda _e: _sync_pane_toggles())
    console_split.on_value_change(lambda _e: _sync_pane_toggles())
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
