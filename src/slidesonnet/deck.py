"""Load a :class:`Deck` from a PDF + its narration sidecar, with diagnostics."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from slidesonnet.atomic import atomic_write_text
from slidesonnet.builds import deck_pdf
from slidesonnet.diagnostics import Diagnostic, bracket_diagnostics, diagnose, sort_diagnostics
from slidesonnet.models import VoiceConfig
from slidesonnet.narration.format import parse_document, serialize_sidecar
from slidesonnet.narration.model import Deck, PageNarration
from slidesonnet.pdf.reader import read_page_ids
from slidesonnet.tts import FILE_VOICE_BACKENDS


def default_sidecar_path(pdf_path: Path) -> Path:
    """The sidecar path for *pdf_path*: ``<deck-stem>.narration`` beside it (a plain
    build ``X.plain.pdf`` shares its deck's ``X.narration``)."""
    return deck_pdf(pdf_path).with_suffix(".narration")


def resolve_voice_files(voices: dict[str, VoiceConfig], base_dir: Path) -> dict[str, VoiceConfig]:
    """Resolve file-based voice values (e.g. a Qwen3 ``.pt``) against *base_dir*.

    A voice-map value for a file-voiced backend is a path stored relative to the
    deck, so the sidecar stays portable; in memory it becomes absolute so the
    engine can load it regardless of the process's working directory (an already
    absolute path is left unchanged). Returns a fresh map — the input is never
    mutated — so the on-disk preamble keeps the portable relative form.
    """
    out: dict[str, VoiceConfig] = {}
    for name, vc in voices.items():
        backend_voices = dict(vc.backend_voices)
        for backend, value in backend_voices.items():
            if value and _is_file_voice(backend, value):
                backend_voices[backend] = str((base_dir / value).resolve())
        out[name] = VoiceConfig(name=name, backend_voices=backend_voices)
    return out


def relativize_voice_files(
    voices: dict[str, VoiceConfig], base_dir: Path
) -> dict[str, VoiceConfig]:
    """Inverse of :func:`resolve_voice_files`: store file voices relative to *base_dir*.

    The in-memory deck holds absolute file-voice paths (so the engine can load
    them), but the sidecar must stay portable — a save, and the editor's display,
    re-relativize them against the deck dir. A path already relative, or one
    outside the deck tree (kept absolute on load), passes through unchanged.
    Returns a fresh map; the input is never mutated.
    """
    base = base_dir.resolve()
    out: dict[str, VoiceConfig] = {}
    for name, vc in voices.items():
        backend_voices = dict(vc.backend_voices)
        for backend, value in backend_voices.items():
            if value and _is_file_voice(backend, value) and Path(value).is_absolute():
                backend_voices[backend] = str(Path(value).resolve().relative_to(base, walk_up=True))
        out[name] = VoiceConfig(name=name, backend_voices=backend_voices)
    return out


def _is_file_voice(backend: str, value: str) -> bool:
    """True when a voice-map value is a file artifact, not an opaque voice id.

    A file-voice backend (Qwen3) may carry *either* a ``.pt`` clone prompt (a
    path, made portable relative to the deck) *or* a built-in speaker name (an
    opaque id, left verbatim). Only the ``.pt`` artifact is path-resolved.
    """
    return backend in FILE_VOICE_BACKENDS and value.endswith(".pt")


def dedupe_page_ids(pages: list[str]) -> tuple[list[str], list[Diagnostic]]:
    """Rename repeated slide-ids so every page is addressable: x, x → x, x-2.

    The first occurrence keeps its name; each later one gets the smallest
    ``-n`` (n ≥ 2) that no other page uses — raw ids included, so a genuine
    ``x-2`` elsewhere in the deck is never clobbered (the duplicate skips to
    ``x-3``). Every rename is reported as a warning: narration attached to a
    renamed id is bound by *occurrence order*, which shifts if pages reorder —
    giving each page its own ``\\ssid`` is still the durable fix.

    Unmarked pages (empty id) pass through; they carry their own diagnostic.
    """
    taken = {p for p in pages if p}
    seen: set[str] = set()
    out: list[str] = []
    diags: list[Diagnostic] = []
    for i, pid in enumerate(pages, start=1):
        if not pid or pid not in seen:
            seen.add(pid)
            out.append(pid)
            continue
        n = 2
        while f"{pid}-{n}" in taken:
            n += 1
        new = f"{pid}-{n}"
        taken.add(new)
        seen.add(new)
        out.append(new)
        if pid not in {d.slide_id for d in diags if d.code == "duplicate-id"}:
            diags.append(
                Diagnostic(
                    "warning",
                    "duplicate-id",
                    f"slide-id '{pid}' appears on several pages — later ones were "
                    "renamed to disambiguate; give each page its own \\ssid",
                    pid,
                )
            )
        diags.append(
            Diagnostic(
                "warning",
                "duplicate-id",
                f"page {i} reused slide-id '{pid}' — renamed to '{new}' to "
                "disambiguate; give it its own \\ssid",
                new,
            )
        )
    return out, diags


def dedupe_block_ids(
    blocks: list[PageNarration],
) -> tuple[list[PageNarration], dict[str, str]]:
    """Rename repeated sidecar ``@ids`` so no narration block is silently dropped.

    The narration is keyed by id, so two ``@same-id`` blocks would otherwise
    collapse to one (last wins) — losing the first block's text. Instead the
    first keeps its id and each later one is renamed to the smallest free
    ``-n`` (n ≥ 2), avoiding collision with any other block id. Returns the
    blocks and the renames (new id → the repeated id). A renamed block has no
    page, so the editor offers it with the unattached narration, where it can be
    appended to its slide or deleted; :func:`duplicate_block_diagnostics` says
    what went wrong, in the file's own terms.
    """
    taken = {b.slide_id for b in blocks}
    seen: set[str] = set()
    out: list[PageNarration] = []
    renamed: dict[str, str] = {}
    for block in blocks:
        sid = block.slide_id
        if sid not in seen:
            seen.add(sid)
            out.append(block)
            continue
        n = 2
        while f"{sid}-{n}" in taken:
            n += 1
        new = f"{sid}-{n}"
        taken.add(new)
        seen.add(new)
        out.append(replace(block, slide_id=new))
        renamed[new] = sid
    return out, renamed


_HEADER_LINE_RE = re.compile(r"^\s*@(?P<id>\S+)\s*(?:#.*)?$")


def duplicate_block_diagnostics(
    text: str, repeated: set[str], sidecar_name: str
) -> list[Diagnostic]:
    """One error per slide-id in *repeated* with several ``@`` blocks, naming their lines.

    The single diagnosis of a repeated ``@id`` — ``check`` and the editor both
    show it — keyed to the id as written, never to a made-up ``id-2``.
    """
    lines: dict[str, list[int]] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        m = _HEADER_LINE_RE.match(raw)
        if m and m.group("id") in repeated:
            lines.setdefault(m.group("id"), []).append(lineno)
    diags: list[Diagnostic] = []
    for sid, where in lines.items():
        at = ", ".join(str(n) for n in where[:-1]) + f" and {where[-1]}"
        diags.append(
            Diagnostic(
                "error",
                "duplicate-block",
                f"slide-id '{sid}' has more than one narration block (lines {at} of "
                f"{sidecar_name}) — merge them into a single @{sid} block",
                sid,
            )
        )
    return diags


_PAUSE_LINE_RE = re.compile(r"^\s*pause\s*:")


def double_pause_diagnostics(text: str, sidecar_name: str) -> list[Diagnostic]:
    """A warning per run of ``pause:`` lines with nothing said between them, naming
    the slide and the lines: two silences in a row are one longer silence, and
    usually a slip. Comment and blank lines between them don't break the run."""
    diags: list[Diagnostic] = []
    slide: str | None = None
    run: list[int] = []

    def flush() -> None:
        if slide is not None and len(run) > 1:
            at = ", ".join(str(n) for n in run[:-1]) + f" and {run[-1]}"
            diags.append(
                Diagnostic(
                    "warning",
                    "double-pause",
                    f"slide '{slide}' has {len(run)} pauses in a row (lines {at} of "
                    f"{sidecar_name}) — they make one longer silence; merge them into one pause",
                    slide,
                )
            )
        run.clear()

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if _PAUSE_LINE_RE.match(line):
            run.append(lineno)
            continue
        flush()
        if header := _HEADER_LINE_RE.match(raw):
            slide = header.group("id")
    flush()
    return diags


def load_deck(
    pdf_path: Path,
    *,
    sidecar_path: Path | None = None,
    pages: tuple[list[str], list[Diagnostic]] | None = None,
) -> tuple[Deck, list[Diagnostic]]:
    """Load *pdf_path* and its sidecar into a :class:`Deck` plus diagnostics.

    A missing sidecar is treated as empty narration (every page un-narrated).
    *pages* injects a previously-computed (deduped page ids, dedupe
    diagnostics) pair when the PDF is known unchanged — reading ids re-opens
    the PDF and walks every page, which callers that reload per edit-commit
    (the editor) cannot afford.
    """
    pdf_path = pdf_path.resolve()
    sidecar = sidecar_path or default_sidecar_path(pdf_path)
    if pages is None:
        pages = dedupe_page_ids(read_page_ids(pdf_path))
    page_ids, dedupe_diags = pages

    blocks: list[PageNarration] = []
    block_diags: list[Diagnostic] = []
    renamed: dict[str, str] = {}
    voices: dict[str, VoiceConfig] = {}
    default_voice: str | None = None
    preamble_source: str | None = None
    if sidecar.exists():
        text = sidecar.read_text(encoding="utf-8")
        doc = parse_document(text)
        blocks, renamed = dedupe_block_ids(doc.blocks)
        block_diags = duplicate_block_diagnostics(text, set(renamed.values()), sidecar.name)
        block_diags += double_pause_diagnostics(text, sidecar.name)
        voices = resolve_voice_files(doc.voices, sidecar.resolve().parent)
        default_voice, preamble_source = doc.default_voice, doc.preamble_source

    # a renamed block's only problem is the repeat, reported once above
    id_diags = [d for d in diagnose(page_ids, blocks) if d.slide_id not in renamed]
    diags = sort_diagnostics(dedupe_diags + block_diags + id_diags + bracket_diagnostics(blocks))
    deck = Deck(
        pdf_path=pdf_path,
        sidecar_path=sidecar,
        pages=page_ids,
        narration={b.slide_id: b for b in blocks},
        voices=voices,
        default_voice=default_voice,
        preamble_source=preamble_source,
        duplicate_blocks=renamed,
    )
    return deck, diags


def sidecar_text(deck: Deck, *, header: str | None = None) -> str:
    """The sidecar text :func:`save_deck` would write for *deck*, in PDF page order.

    Empty placeholder blocks are skipped: a page with no narration is left out
    of the sidecar entirely (a bare ``@id`` header would otherwise read back as
    an empty narration block and silence its ``missing-narration`` warning).
    """
    blocks = [deck.page_narration(pid) for pid in unique_real_ids(deck.pages)]
    # Include any orphan blocks (not on a page) so they aren't silently dropped.
    on_page = {pid for pid in deck.pages if pid}
    for sid, block in deck.narration.items():
        if sid not in on_page:
            blocks.append(block)
    blocks = [b for b in blocks if not b.is_empty]
    # The in-memory deck holds absolute file-voice paths; the sidecar must stay
    # portable, so re-relativize them. Only used when the preamble is regenerated
    # (``preamble_source`` is None, i.e. the voice map was edited) — otherwise the
    # original relative preamble is re-emitted verbatim.
    voices = relativize_voice_files(deck.voices, deck.sidecar_path.resolve().parent)
    return serialize_sidecar(
        blocks,
        header=header,
        voices=voices,
        default_voice=deck.default_voice,
        preamble_source=deck.preamble_source,
    )


def save_deck(deck: Deck, *, header: str | None = None) -> None:
    """Serialize *deck*'s narration to its sidecar, atomically (see :func:`sidecar_text`).

    The file is replaced in one rename, so a watcher (the editor's poll, an
    agent) never reads a truncated sidecar mid-save.
    """
    atomic_write_text(deck.sidecar_path, sidecar_text(deck, header=header))


def unique_real_ids(pages: list[str]) -> list[str]:
    """The deck's addressable slide-ids: deduped, in page order, blanks dropped."""
    return [pid for pid in dict.fromkeys(pages) if pid]
