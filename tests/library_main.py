"""NiceGUI 'main file' for the deck-library and deck-switching tests.

Mirrors :func:`slidesonnet.gui.app.register_pages`, but rebuilds the registry on
every request from ``SLIDESONNET_LIB_ROOT`` so each test can point it at its own
temporary tree (the real app scans once at launch).
"""

from __future__ import annotations

import os
from pathlib import Path

from nicegui import ui

from slidesonnet.gui.app import build_editor, set_registry
from slidesonnet.gui.library import DeckRegistry
from slidesonnet.gui.library_view import build_library


def _registry() -> DeckRegistry:
    registry = DeckRegistry(Path(os.environ["SLIDESONNET_LIB_ROOT"]))
    registry.rescan()
    set_registry(registry)
    return registry


@ui.page("/")
def index() -> None:
    build_library(_registry())


@ui.page("/d/{token}")
def deck_page(token: str) -> None:
    registry = _registry()
    entry = registry.resolve(token)
    if entry is None:
        ui.navigate.to("/")
        return
    build_editor(entry.pdf_path, entry.sidecar_path, entry=entry)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run()
