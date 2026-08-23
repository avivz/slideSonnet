"""Shared look & feel for the editor's pages.

The editor and the deck library are separate NiceGUI pages but one product, so
the palette, fonts, and stylesheet live here rather than in either page. Assets
are read once at import from ``gui/static/``.
"""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

_STATIC_DIR = Path(__file__).parent / "static"

HEAD_CSS = (_STATIC_DIR / "editor.css").read_text(encoding="utf-8")
HEAD_FONTS = (_STATIC_DIR / "fonts.html").read_text(encoding="utf-8")
HEAD_RESIZE = (_STATIC_DIR / "resize.html").read_text(encoding="utf-8")
HEAD_MORPH = (_STATIC_DIR / "morph.html").read_text(encoding="utf-8")


def apply_theme(*, aspect: float | None = None, extras: str = "") -> None:
    """Set the dark palette and inline the stylesheet into this page's head.

    *aspect* publishes the deck's page aspect ratio as the ``--ss-ar`` custom
    property (the stage sizes itself from it); the library has no deck, so it
    passes none. *extras* appends page-specific head HTML (the editor's resize
    and morph helpers, which the library doesn't need).
    """
    ui.dark_mode().enable()
    ui.colors(
        primary="#5db3f0",
        positive="#2e7d4f",
        negative="#c0443c",
        warning="#a8772a",
        dark="#151a22",
        dark_page="#0e1116",
    )
    ar_css = f":root{{--ss-ar:{aspect:.4f}}}" if aspect is not None else ""
    ui.add_head_html(HEAD_FONTS + "<style>" + HEAD_CSS + ar_css + "</style>" + extras)


def wordmark() -> None:
    """The slideSonnet wordmark, shared by both pages' headers."""
    ui.html('<span class="ss-wordmark">slide<span class="ss-accent">Sonnet</span></span>')
