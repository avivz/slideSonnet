"""NiceGUI 'main file' for the user-simulation tests.

The `user` fixture runs this via runpy to register pages. The target deck is
read from the SLIDESONNET_EDIT_PDF env var at request time (inside the page
builder), so each test can point it at its own temporary deck before
``user.open('/')``.
"""

from __future__ import annotations

import os
from pathlib import Path

from nicegui import ui

from slidesonnet.gui.app import build_editor


@ui.page("/")
def index() -> None:
    build_editor(Path(os.environ["SLIDESONNET_EDIT_PDF"]))


if __name__ in {"__main__", "__mp_main__"}:
    ui.run()
