"""NiceGUI narration editor: page nav, editing, per-slide TTS, preview, export.

The whole-deck preview plays a single pre-rendered track (silences baked in)
and flips the slide image on cue-sheet boundaries, so the preview is
sample-accurate to the exported video.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nicegui import app, ui

from slidesonnet.cache import render_dir
from slidesonnet.gui.state import EditorState

logger = logging.getLogger(__name__)

_MEDIA_URL = "/ssmedia"
_served: set[str] = set()


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
            pace = ui.select(["normal", "slow", "fast"], label="Pace", value="normal").classes("w-full")
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
                color = {"error": "text-red-600", "warning": "text-amber-600"}.get(d.severity, "text-sky-600")
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
) -> None:
    """Launch the NiceGUI editor for *pdf_path* (blocking)."""
    pdf_path = pdf_path.resolve()

    @ui.page("/")
    def _index() -> None:
        build_editor(pdf_path, sidecar_path)

    ui.run(host=host, port=port, title="slideSonnet", reload=False, show=open_browser)
