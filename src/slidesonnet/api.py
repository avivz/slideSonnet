"""Typed, importable operations for the narration editor.

Every CLI subcommand delegates here, so the whole pipeline — scaffold a sidecar,
check, synthesize TTS, export video, write subtitles — is scriptable from Python
(an LLM/CI loop or a Makefile) without launching the GUI.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from slidesonnet.deck import default_sidecar_path
from slidesonnet.diagnostics import Diagnostic
from slidesonnet.narration.format import parse_sidecar
from slidesonnet.pdf.reader import read_page_ids

__all__ = [
    "sty_text",
    "write_sty",
    "scaffold_text",
    "init_sidecar",
    "check_deck",
]


def sty_text() -> str:
    """Return the packaged ``slidesonnet.sty`` LaTeX macro source."""
    return (
        importlib.resources.files("slidesonnet.templates")
        .joinpath("slidesonnet.sty")
        .read_text(encoding="utf-8")
    )


def write_sty(target: Path) -> Path:
    """Write ``slidesonnet.sty`` to *target* (a file or a directory)."""
    if target.is_dir():
        target = target / "slidesonnet.sty"
    target.write_text(sty_text(), encoding="utf-8")
    return target


def _unique_real(pages: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in pages:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def scaffold_text(pdf_path: Path, pages: list[str]) -> str:
    """Build a blank sidecar: one ``@<id>`` block per page with a page-number comment."""
    lines = [
        f"# slideSonnet narration — deck: {pdf_path.name}",
        "# Fill in narration under each @slide-id. '[pause N]' inserts N seconds of silence.",
        "",
    ]
    page_of: dict[str, int] = {}
    for i, pid in enumerate(pages, start=1):
        if pid and pid not in page_of:
            page_of[pid] = i
    for pid in _unique_real(pages):
        lines.append(f"@{pid}")
        lines.append(f"# page {page_of[pid]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def init_sidecar(
    pdf_path: Path,
    *,
    sidecar_path: Path | None = None,
    merge: bool = False,
    force: bool = False,
) -> Path:
    """Scaffold a blank narration sidecar from *pdf_path*'s slide-ids.

    - default: write a fresh blank sidecar (one block per page, in PDF order).
    - ``merge``: append blocks for ids missing from an existing sidecar, leaving
      existing narration untouched; safe to re-run after the deck drifts.
    - ``force``: overwrite an existing sidecar.

    Returns the sidecar path. Raises ``FileExistsError`` if it exists and neither
    ``merge`` nor ``force`` was given.
    """
    pdf_path = pdf_path.resolve()
    sidecar = sidecar_path or default_sidecar_path(pdf_path)
    pages = read_page_ids(pdf_path)

    if sidecar.exists() and not (merge or force):
        raise FileExistsError(
            f"{sidecar} already exists — use merge=True to top up or force=True to overwrite"
        )

    if merge and sidecar.exists():
        existing = parse_sidecar(sidecar.read_text(encoding="utf-8"))
        existing_ids = {b.slide_id for b in existing}
        missing = [pid for pid in _unique_real(pages) if pid not in existing_ids]
        if missing:
            page_of = {pid: i for i, pid in enumerate(pages, start=1) if pid}
            chunk = ["", "# --- added by `init --merge` ---"]
            for pid in missing:
                chunk.append("")
                chunk.append(f"@{pid}")
                chunk.append(f"# page {page_of[pid]}")
            text = sidecar.read_text(encoding="utf-8").rstrip() + "\n" + "\n".join(chunk) + "\n"
            sidecar.write_text(text, encoding="utf-8")
        return sidecar

    sidecar.write_text(scaffold_text(pdf_path, pages), encoding="utf-8")
    return sidecar


def check_deck(pdf_path: Path, *, sidecar_path: Path | None = None) -> list[Diagnostic]:
    """Run id-only reconciliation diagnostics for *pdf_path* + its sidecar."""
    from slidesonnet.deck import load_deck

    _, diags = load_deck(pdf_path, sidecar_path=sidecar_path)
    return diags
