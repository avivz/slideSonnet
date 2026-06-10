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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nicegui import app, ui

from slidesonnet.cache import render_dir
from slidesonnet.gui.state import EditorState

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


def build_editor(pdf_path: Path, sidecar_path: Path | None = None) -> EditorState:
    """Build the editor UI for *pdf_path* in the current page; return its state."""
    state = EditorState(pdf_path, sidecar_path=sidecar_path)
    _serve_media(state)

    ui.add_head_html("<style>.ss-mono textarea{font-family:ui-monospace,monospace}</style>")

    with ui.header().classes("items-center justify-between"):
        ui.label(f"slideSonnet — {pdf_path.name}").classes("text-lg font-bold")
        page_label = ui.label().classes("text-sm")
        err_badge = ui.label().classes("text-sm")

    # --- main two-column body ---
    with ui.row().classes("w-full no-wrap"):
        with ui.column().classes("w-2/3"):
            slide_img = ui.image().classes("w-full border rounded")
            audio = ui.audio("").props("controls").classes("w-full")
            audio.visible = False
        with ui.column().classes("w-1/3 gap-2"):
            id_label = ui.label().classes("text-base font-mono font-bold")
            body = ui.textarea(label="Narration").classes("w-full ss-mono").props("autogrow rows=8")
            voice = ui.input(label="Voice (optional)").classes("w-full")
            pace = ui.select(["normal", "slow", "fast"], label="Pace", value="normal").classes(
                "w-full"
            )
            diag_box = ui.column().classes("w-full")

    # --- nav + action bar ---
    with ui.row().classes("w-full items-center gap-2"):
        prev_btn = ui.button("Previous", icon="chevron_left")
        next_btn = ui.button("Next", icon="chevron_right")
        ui.space()
        ui.button("Generate", icon="record_voice_over", on_click=lambda: _do(_generate_one))
        ui.button("Generate all", on_click=lambda: _do(_generate_all))
        ui.button("Preview deck", icon="play_arrow", on_click=lambda: _do(_preview_deck))
        ui.button("Export…", icon="movie", on_click=lambda: _do(_export))

    # ---- rendering helpers ----
    cues: list[tuple[float, str]] = []

    def render() -> None:
        page_label.set_text(f"Slide {state.index + 1} / {state.page_count}")
        err_badge.set_text(f"⛔ {state.error_count} errors" if state.error_count else "✓ no errors")
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
        _render_diagnostics()

    def _render_diagnostics() -> None:
        diag_box.clear()
        with diag_box:
            for d in state.diagnostics_for_current():
                color = {"error": "text-red-600", "warning": "text-amber-600"}.get(
                    d.severity, "text-sky-600"
                )
                ui.label(f"{d.severity}: {d.message}").classes(f"text-xs {color}")

    def save_current() -> None:
        state.save(body.value or "", voice=voice.value or "", pace=pace.value or "normal")

    # ---- actions (each saves first) ----
    def _go(delta: int) -> None:
        save_current()
        state.go(state.index + delta)
        render()

    def _do(action: Callable[[], None]) -> None:
        save_current()
        try:
            action()
        except NotImplementedError as exc:
            ui.notify(str(exc), type="warning")
        except Exception as exc:  # surface backend errors without crashing the UI
            logger.exception("action failed")
            ui.notify(f"Error: {exc}", type="negative")
        render()

    def _generate_one() -> None:
        n = state.synth_current()
        ui.notify(f"Synthesized {n} new clip(s) for {state.current_id}", type="positive")

    def _generate_all() -> None:
        n = state.synth_all()
        ui.notify(f"Synthesized {n} new clip(s) across the deck", type="positive")

    def _preview_deck() -> None:
        nonlocal cues
        preview = state.preview_deck()
        cues = preview.cues
        audio.set_source(_media_url(state, preview.track))
        audio.visible = True
        audio.play()
        ui.notify(f"Preview ready ({preview.total_duration:.1f}s)", type="positive")

    def _export() -> None:
        out = state.pdf_path.with_suffix(".mp4")
        result = state.export(out)
        ui.notify(f"Exported {out.name} ({result.duration:.1f}s)", type="positive")

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

    audio.on("timeupdate", _on_timeupdate, args=["target.currentTime"])
    prev_btn.on_click(lambda: _go(-1))
    next_btn.on_click(lambda: _go(1))
    body.on("blur", lambda: save_current())

    render()
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
