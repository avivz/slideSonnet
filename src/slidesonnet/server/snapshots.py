"""Read models: a deck snapshot and the library, as API DTOs. Blocking — run off the loop."""

from __future__ import annotations

import wave
from pathlib import Path

from slidesonnet.audio.synth import _ref_targets
from slidesonnet.cache import render_dir, resolve_audio_dir
from slidesonnet.config import Config
from slidesonnet.deck import relativize_voice_files
from slidesonnet.diagnostics import Diagnostic, voice_diagnostics
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.hashing import audio_cache_path_or_alt
from slidesonnet.models import Backend, ProgressFn, resolve_voice
from slidesonnet.pdf.reader import open_render, page_aspect
from slidesonnet.server import editing
from slidesonnet.server.decks import LoadedDeck, deck_service
from slidesonnet.server.engines import editor_engine, with_engine
from slidesonnet.server.library import DeckEntry, DeckRegistry
from slidesonnet.server.media import media_url
from slidesonnet.server.schemas import (
    AudioStatusDTO,
    BlockDTO,
    ClipDTO,
    DeckSnapshot,
    DeckStatsDTO,
    DiagnosticDTO,
    EngineDTO,
    LibraryDeckDTO,
    LibraryDTO,
    LibrarySectionDTO,
    PageDTO,
    RevisionsDTO,
    SilenceDefaultsDTO,
    SlideStatus,
    TransitionDTO,
    VoicesDTO,
    segment_dto,
)
from slidesonnet.tts import BACKENDS, available_backends, create_tts


def engine_dtos() -> list[EngineDTO]:
    """Every engine slideSonnet knows, and whether this machine has it installed."""
    installed = set(available_backends())
    return [
        EngineDTO(name=n, paid=b.paid, realtime=b.realtime, installed=n in installed)
        for n, b in sorted(BACKENDS.items())
    ]


def all_diagnostics(loaded: LoadedDeck, engine: Backend) -> list[Diagnostic]:
    """Load-time findings plus voice-unmapped warnings for *engine*."""
    deck, config = loaded.deck, loaded.config
    voices = {**config.voices, **deck.voices}
    return loaded.diagnostics + voice_diagnostics(
        list(deck.narration.values()), voices, deck.default_voice, engine
    )


def slide_status(diags: list[Diagnostic], narrated: bool, slide_id: str) -> SlideStatus:
    """Worst finding for a slide; un-narrated alone reads as 'empty'."""
    severities = {
        d.severity for d in diags if d.slide_id == slide_id and d.code != "missing-narration"
    }
    if "error" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    return "ready" if narrated else "empty"


def page_images(pdf_path: Path, page_count: int) -> dict[int, Path]:
    """Page images rendered so far (never renders)."""
    try:
        return open_render(pdf_path, render_dir(pdf_path) / "pages", page_count=page_count)
    except (OSError, ValueError):  # a missing/corrupt render dir: "not rendered yet"
        return {}


def deck_snapshot(
    entry: DeckEntry, *, engine: Backend | None = None, registry: DeckRegistry | None = None
) -> DeckSnapshot:
    """Everything the editor needs to show one deck, at one set of revisions."""
    service = deck_service(entry.pdf_path, entry.sidecar_path)
    loaded = service.load()
    deck, config = loaded.deck, loaded.config
    active: Backend = engine or editor_engine(config)
    active_config = with_engine(config, active)
    diags = all_diagnostics(loaded, active)

    audio_dir = resolve_audio_dir(entry.pdf_path, active_config).path
    per_slide: dict[str, list[bool]] = {}
    clips: dict[str, list[ClipDTO]] = {}
    for ref, target in _ref_targets(deck, active_config, audio_dir):
        path = audio_cache_path_or_alt(target)
        per_slide.setdefault(ref.slide_id, []).append(path is not None)
        clips.setdefault(ref.slide_id, []).append(_clip(path))
    images = page_images(entry.pdf_path, len(deck.pages))

    pages: list[PageDTO] = []
    for i, sid in enumerate(deck.pages):
        flags = per_slide.get(sid, [])
        image = images.get(i)
        pages.append(
            PageDTO(
                index=i,
                slide_id=sid,
                status=slide_status(diags, editing.has_narration(deck, sid), sid),
                image_url=media_url(entry.pdf_path, image, stamp=True) if image else None,
                incoming=TransitionDTO.of(editing.incoming_transition(deck, sid))
                if sid
                else TransitionDTO(),
                audio=AudioStatusDTO(speech=len(flags), cached=sum(flags)),
                clips=clips.get(sid, []),
            )
        )
    narration = {
        sid: BlockDTO(
            slide_id=sid,
            segments=[segment_dto(s) for s in block.segments],
            transition_in=TransitionDTO.of(block.transition_in),
            transition_out=TransitionDTO.of(block.transition_out),
        )
        for sid, block in deck.narration.items()
    }
    voice_map = relativize_voice_files(deck.voices, service.sidecar_path.parent)
    names = sorted(set(config.voices) | set(deck.voices))
    rev = loaded.revisions
    return DeckSnapshot(
        token=entry.token,
        name=entry.name,
        label=entry.label,
        revisions=RevisionsDTO(
            narration=rev.narration, pdf=rev.pdf, config=rev.config, review=rev.review
        ),
        engine=active,
        engines=engine_dtos(),
        pages=pages,
        narration=narration,
        orphans=[b.slide_id for b in editing.orphan_blocks(deck)],
        duplicates=dict(deck.duplicate_blocks),
        diagnostics=[
            DiagnosticDTO(severity=d.severity, code=d.code, message=d.message, slide_id=d.slide_id)
            for d in diags
        ],
        voices=VoicesDTO(
            map={n: dict(v.backend_voices) for n, v in voice_map.items()},
            default_voice=deck.default_voice,
            names=names,
            resolved={n: resolve_voice(n, {**config.voices, **deck.voices}, active) for n in names},
        ),
        missing_audio=sum(1 for flags in per_slide.values() for c in flags if not c),
        silence=SilenceDefaultsDTO(start=config.video.pre_silence, end=config.video.tail_seconds),
        engine_warm=_engine_warm(active_config),
        neighbours=_neighbours(registry, entry.token) if registry is not None else {},
        aspect=_aspect(entry.pdf_path),
    )


def _aspect(pdf_path: Path) -> float:
    try:
        return float(page_aspect(pdf_path))
    except (RuntimeError, ValueError, OSError, IndexError):  # a malformed page: default shape
        return 16 / 9


def _clip(path: Path | None) -> ClipDTO:
    if path is None:
        return ClipDTO(cached=False)
    seconds: float | None = None
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wf:
                rate = wf.getframerate()
                seconds = wf.getnframes() / rate if rate else None
        except (wave.Error, OSError, EOFError):
            seconds = None
    try:
        size: int | None = path.stat().st_size
    except OSError:
        size = None
    return ClipDTO(cached=True, seconds=seconds, bytes=size)


def _engine_warm(config: Config) -> bool:
    """False while a heavy engine (Qwen3) still has its model to load (cheap check)."""
    try:
        return bool(create_tts(config.tts).is_warm())
    except (ImportError, SlideSonnetError):  # engine package missing: nothing to warm
        return True


def _neighbours(registry: DeckRegistry, token: str) -> dict[str, str | None]:
    prev = registry.neighbour(token, -1)
    nxt = registry.neighbour(token, 1)
    return {
        "prev": prev.token if prev is not None and prev.token != token else None,
        "next": nxt.token if nxt is not None and nxt.token != token else None,
    }


def _library_deck(entry: DeckEntry) -> LibraryDeckDTO:
    return LibraryDeckDTO(
        token=entry.token,
        name=entry.name,
        label=entry.label,
        group=entry.group,
        section=entry.section,
        narrated=entry.sidecar_path is not None,
        url=f"/d/{entry.token}",
    )


def library(registry: DeckRegistry) -> LibraryDTO:
    return LibraryDTO(
        root=registry.root.name or registry.root.anchor,
        parents=registry.parents(),
        sections=[
            LibrarySectionDTO(title=title, decks=[_library_deck(e) for e in entries])
            for title, entries in registry.grouped()
        ],
        unnarrated=[_library_deck(e) for e in registry.unnarrated()],
        truncated=registry.truncated(),
    )


def deck_stats(entry: DeckEntry) -> DeckStatsDTO:
    """Cheap per-deck counts for a library card (no audio scan)."""
    loaded = deck_service(entry.pdf_path, entry.sidecar_path).load()
    deck = loaded.deck
    diags = loaded.diagnostics
    return DeckStatsDTO(
        token=entry.token,
        slides=len(deck.pages),
        narrated=sum(1 for sid in deck.pages if editing.has_narration(deck, sid)),
        errors=sum(1 for d in diags if d.severity == "error"),
        warnings=sum(1 for d in diags if d.severity == "warning"),
    )


def ensure_page_images(
    pdf_path: Path,
    page_count: int,
    *,
    near: int = 0,
    batch: int = 4,
    progress: ProgressFn | None = None,
) -> list[Path | None]:
    """Render every page image not rendered yet (blocking); images in page order.

    Starts with page *near* (the one being looked at) and works outward in
    small batches, so the page someone is waiting for comes first and a partial
    render (an interrupted run, the editor's own fill) is reused.
    """
    from slidesonnet.pdf.reader import render_page_range

    out = render_dir(pdf_path) / "pages"
    out.mkdir(parents=True, exist_ok=True)
    pages = page_images(pdf_path, page_count)
    while True:
        missing = [i for i in range(page_count) if i not in pages]
        if not missing:
            break
        first = min(missing, key=lambda i: (abs(i - near), -i))
        last = first
        if first != near:
            while last + 1 < page_count and last + 1 not in pages and last - first + 1 < batch:
                last += 1
        before = len(pages)
        pages.update(render_page_range(pdf_path, out, first, last))
        if progress is not None:
            progress("render", len(pages), page_count, "")
        if len(pages) == before:  # pdftoppm wrote nothing: don't spin
            break
    return [pages.get(i) for i in range(page_count)]
