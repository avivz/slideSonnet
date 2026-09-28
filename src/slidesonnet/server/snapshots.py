"""Read models: a deck snapshot and the library, as API DTOs. Blocking — run off the loop."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from slidesonnet.audio.synth import ref_cache_status
from slidesonnet.cache import render_dir, resolve_audio_dir
from slidesonnet.config import Config
from slidesonnet.deck import relativize_voice_files
from slidesonnet.diagnostics import Diagnostic, voice_diagnostics
from slidesonnet.gui.library import DeckEntry, DeckRegistry
from slidesonnet.models import Backend
from slidesonnet.pdf.reader import open_render
from slidesonnet.review import ops as review_ops
from slidesonnet.server import editing
from slidesonnet.server.decks import LoadedDeck, deck_service
from slidesonnet.server.media import media_url
from slidesonnet.server.schemas import (
    AudioStatusDTO,
    BlockDTO,
    DeckSnapshot,
    DeckStatsDTO,
    DiagnosticDTO,
    EngineDTO,
    LibraryDeckDTO,
    LibraryDTO,
    LibrarySectionDTO,
    PageDTO,
    RevisionsDTO,
    SlideStatus,
    TransitionDTO,
    VoicesDTO,
    segment_dto,
)
from slidesonnet.tts import BACKENDS, available_backends


def with_engine(config: Config, engine: Backend | None) -> Config:
    """*config* with its TTS backend swapped to *engine* (None keeps the configured one)."""
    if engine is None or engine == config.tts.backend:
        return config
    return replace(config, tts=replace(config.tts, backend=engine))


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


def deck_snapshot(entry: DeckEntry, *, engine: Backend | None = None) -> DeckSnapshot:
    """Everything the editor needs to show one deck, at one set of revisions."""
    service = deck_service(entry.pdf_path, entry.sidecar_path)
    loaded = service.load()
    deck, config = loaded.deck, loaded.config
    active: Backend = engine or config.tts.backend
    active_config = with_engine(config, active)
    diags = all_diagnostics(loaded, active)

    audio_dir = resolve_audio_dir(entry.pdf_path, active_config).path
    per_slide: dict[str, list[bool]] = {}
    for ref, cached in ref_cache_status(deck, active_config, audio_dir):
        per_slide.setdefault(ref.slide_id, []).append(cached)
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
    installed = set(available_backends())
    rev = loaded.revisions
    return DeckSnapshot(
        token=entry.token,
        name=entry.name,
        label=entry.label,
        pdf_name=entry.pdf_path.name,
        sidecar_name=service.sidecar_path.name,
        revisions=RevisionsDTO(
            narration=rev.narration, pdf=rev.pdf, config=rev.config, review=rev.review
        ),
        engine=active,
        default_engine=config.tts.backend,
        engines=[
            EngineDTO(name=n, paid=s.paid, realtime=s.realtime, installed=n in installed)
            for n, s in sorted(BACKENDS.items())
        ],
        pages=pages,
        narration=narration,
        orphans=[b.slide_id for b in editing.orphan_blocks(deck)],
        diagnostics=[
            DiagnosticDTO(severity=d.severity, code=d.code, message=d.message, slide_id=d.slide_id)
            for d in diags
        ],
        voices=VoicesDTO(
            map={n: dict(v.backend_voices) for n, v in voice_map.items()},
            default_voice=deck.default_voice,
            names=names,
        ),
        missing_audio=sum(1 for flags in per_slide.values() for c in flags if not c),
        review_active=review_ops.is_active(entry.pdf_path),
    )


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
        root=registry.root.name or str(registry.root),
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


def ensure_page_images(pdf_path: Path, page_count: int, *, batch: int = 8) -> list[Path | None]:
    """Render every page image not rendered yet (blocking); images in page order.

    Fills a partial render in batches, so an interrupted run (or the editor's
    own background fill) is reused rather than started over.
    """
    from slidesonnet.pdf.reader import render_page_range

    out = render_dir(pdf_path) / "pages"
    out.mkdir(parents=True, exist_ok=True)
    pages = page_images(pdf_path, page_count)
    i = 0
    while i < page_count:
        if i in pages:
            i += 1
            continue
        last = i
        while last + 1 < page_count and last + 1 not in pages and last - i + 1 < batch:
            last += 1
        before = len(pages)
        pages.update(render_page_range(pdf_path, out, i, last))
        if len(pages) == before:  # pdftoppm wrote nothing: don't spin
            break
        i = last + 1
    return [pages.get(i) for i in range(page_count)]
