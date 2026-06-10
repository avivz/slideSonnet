"""NiceGUI narration editor — placeholder (full editor lands in M2/M3)."""

from __future__ import annotations

from pathlib import Path


def run_editor(
    pdf_path: Path,
    *,
    sidecar_path: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
) -> None:
    """Launch the editor. Implemented in M2/M3."""
    raise NotImplementedError("The NiceGUI editor is not yet implemented.")
