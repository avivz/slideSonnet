"""``/api/v1`` routes: thin adapters from HTTP to the services.

Sync routes run on FastAPI's threadpool, so blocking reads (parse, hash,
diagnose, audio-cache scans) never stall the event loop. No domain logic lives
here — each route validates, calls a service, and maps the outcome.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from slidesonnet import api
from slidesonnet.audio.synth import ref_cache_status
from slidesonnet.cache import resolve_audio_dir
from slidesonnet.config import load_config
from slidesonnet.deck import resolve_voice_files
from slidesonnet.exceptions import ConfigError
from slidesonnet.gui.library import DeckEntry
from slidesonnet.models import Backend, VoiceConfig
from slidesonnet.narration.format import SidecarError
from slidesonnet.narration.model import Deck
from slidesonnet.server import editing, snapshots
from slidesonnet.server.context import (
    ApiError,
    ApiRoute,
    ServerContext,
    check_mutation,
    context_of,
)
from slidesonnet.server.decks import DeckService, RevisionConflict, deck_service
from slidesonnet.server.engines import engine_lock
from slidesonnet.server.events import Event, EventBus, Subscription
from slidesonnet.server.generation import DeckGeneration
from slidesonnet.server.jobs import Job, JobContext
from slidesonnet.server.media import media_url
from slidesonnet.server.previews import build_preview_artifact, preview_manifest
from slidesonnet.server.schemas import (
    AppendOrphan,
    AttachOrphan,
    CancelGenerationRequest,
    CountDTO,
    DeckCommand,
    DeckSnapshot,
    DeckStatsDTO,
    DeleteOrphan,
    EditVoices,
    EngineDTO,
    EngineVoicesDTO,
    ErrorBody,
    ErrorResponse,
    ExportJob,
    FocusRequest,
    GenerateJob,
    GenerateRequest,
    GenerationStatusDTO,
    JobDTO,
    JobRequest,
    LibraryDTO,
    MetaDTO,
    PagesDTO,
    PreviewJob,
    ProgressDTO,
    RenderPagesJob,
    SaveResponse,
    SessionDTO,
    SlideEdit,
    TransitionFamilyDTO,
    WarmJob,
    segment_domain,
)
from slidesonnet.tts import BACKENDS

_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
router = APIRouter(route_class=ApiRoute, responses=_ERRORS)
Mutation = Depends(check_mutation)

#: SSE keep-alive comment interval (proxies drop idle streams).
_HEARTBEAT_S = 15.0


def _ctx(request: Request) -> ServerContext:
    return context_of(request.app)


def _entry(ctx: ServerContext, token: str) -> DeckEntry:
    entry = ctx.registry.resolve(token)
    if entry is None:
        raise ApiError(404, "unknown_deck", "No such deck in this library.")
    return entry


def _service(entry: DeckEntry) -> DeckService:
    return deck_service(entry.pdf_path, entry.sidecar_path)


def _load_error(exc: Exception) -> ApiError:
    return ApiError(422, "deck_file_error", f"The deck's files have an error: {exc}")


# ---- session / library ------------------------------------------------------------
@router.get("/session", response_model=SessionDTO)
def get_session(request: Request) -> SessionDTO:
    return SessionDTO(token=_ctx(request).session_token)


@router.get("/library", response_model=LibraryDTO)
def get_library(request: Request, rescan: bool = False) -> LibraryDTO:
    ctx = _ctx(request)
    if rescan:
        ctx.registry.rescan()
    return snapshots.library(ctx.registry)


@router.get("/decks/{token}/stats", response_model=DeckStatsDTO)
def get_deck_stats(request: Request, token: str) -> DeckStatsDTO:
    entry = _entry(_ctx(request), token)
    try:
        return snapshots.deck_stats(entry)
    except (SidecarError, ConfigError) as exc:
        raise _load_error(exc) from exc


# ---- deck snapshot + edits -----------------------------------------------------------
@router.get("/decks/{token}", response_model=DeckSnapshot)
def get_deck(request: Request, token: str, engine: Backend | None = None) -> DeckSnapshot:
    ctx = _ctx(request)
    entry = _entry(ctx, token)
    try:
        snap = snapshots.deck_snapshot(entry, engine=engine, registry=ctx.registry)
    except (SidecarError, ConfigError) as exc:
        raise _load_error(exc) from exc
    ctx.watch(token, _service(entry).revisions())
    if ctx.on_deck_open is not None and ctx.last_opened != token:
        ctx.last_opened = token
        ctx.on_deck_open(entry.pdf_path)
    return snap


def _save(ctx: ServerContext, entry: DeckEntry, expected: str, mutate: Any) -> SaveResponse:
    service = _service(entry)
    try:
        result = service.edit(expected, mutate)
    except RevisionConflict as exc:
        raise ApiError(
            409,
            "revision_conflict",
            "The narration file changed since you loaded it. Reload to see the new version.",
        ) from exc
    except editing.EditError as exc:
        raise ApiError(422, "invalid_edit", str(exc)) from exc
    except (SidecarError, ConfigError) as exc:
        raise _load_error(exc) from exc
    if result.changed:
        ctx.announce_write(entry.token, service.revisions())
    return SaveResponse(changed=result.changed, revision=result.revision)


@router.patch("/decks/{token}/slides/{slide_id}", response_model=SaveResponse)
def patch_slide(
    request: Request, token: str, slide_id: str, body: SlideEdit, _m: None = Mutation
) -> SaveResponse:
    ctx = _ctx(request)
    entry = _entry(ctx, token)
    segments = [segment_domain(s) for s in body.segments]

    def mutate(deck: Deck) -> bool:
        if slide_id not in deck.pages:
            raise editing.EditError(f"'{slide_id}' is not a page in the deck")
        return editing.apply_block_edit(
            deck,
            slide_id,
            segments,
            transition_in=body.transition_in.to_domain(),
            transition_out=body.transition_out.to_domain(),
        )

    return _save(ctx, entry, body.expected_revision, mutate)


@router.post("/decks/{token}/commands", response_model=SaveResponse)
def post_command(
    request: Request, token: str, body: DeckCommand, _m: None = Mutation
) -> SaveResponse:
    ctx = _ctx(request)
    entry = _entry(ctx, token)

    def mutate(deck: Deck) -> bool:
        if isinstance(body, AttachOrphan):
            editing.attach_orphan(deck, body.orphan_id, body.target_id)
        elif isinstance(body, AppendOrphan):
            editing.append_orphan(deck, body.orphan_id, body.target_id)
        elif isinstance(body, DeleteOrphan):
            if body.orphan_id not in deck.narration:
                return False
            editing.delete_orphan(deck, body.orphan_id)
        elif isinstance(body, EditVoices):
            voices = {
                name: VoiceConfig(name=name, backend_voices=dict(mapping))
                for name, mapping in body.voices.items()
            }
            resolved = resolve_voice_files(voices, _service(entry).sidecar_path.parent)
            return editing.edit_voices(deck, resolved, body.default_voice, renames=body.renames)
        return True

    return _save(ctx, entry, body.expected_revision, mutate)


# ---- jobs ----------------------------------------------------------------------------
def job_dto(job: Job) -> JobDTO:
    result = job.result if isinstance(job.result, dict) else None
    return JobDTO(
        id=job.id,
        kind=job.kind,
        deck=job.deck,
        status=job.status,
        inputs=job.inputs,
        progress=ProgressDTO(
            phase=job.progress.phase,
            done=job.progress.done,
            total=job.progress.total,
            label=job.progress.label,
        ),
        result=result,
        error=ErrorBody(code=job.error.code, message=job.error.message) if job.error else None,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _resolve_engine(entry: DeckEntry, engine: Backend | None) -> Backend:
    return engine or load_config(entry.pdf_path).tts.backend


def _uncached(
    entry: DeckEntry, engine: Backend, *, slide_id: str | None = None
) -> set[tuple[str, int]]:
    loaded = _service(entry).load()
    config = snapshots.with_engine(loaded.config, engine)
    audio_dir = resolve_audio_dir(entry.pdf_path, config).path
    return {
        (ref.slide_id, ref.speech_index)
        for ref, cached in ref_cache_status(loaded.deck, config, audio_dir)
        if not cached and (slide_id is None or ref.slide_id == slide_id)
    }


def _require_paid_approval(engine: Backend, count: int, allow_paid: bool) -> None:
    """Paid synthesis needs an explicit approval on the request — never implied."""
    if count and BACKENDS[engine].paid and not allow_paid:
        raise ApiError(
            403,
            "paid_confirmation_required",
            f"{count} clip(s) aren't generated yet — making them with {engine} will spend "
            "API credits. Confirm to continue.",
        )


def generate_work(
    entry: DeckEntry, targets: set[tuple[str, int]] | None, *, force: bool, engine: Backend
) -> Any:
    def work(ctx: JobContext) -> dict[str, Any]:
        with engine_lock(engine):
            ctx.check_cancelled()
            made = api.synthesize_deck(
                entry.pdf_path,
                sidecar_path=entry.sidecar_path,
                only_segments=targets,
                force=force,
                engine=engine,
                progress=ctx.progress,
            )
        _service(entry).schedule_prune()
        return {"generated": made}

    return work


def preview_work(entry: DeckEntry, req: PreviewJob, engine: Backend) -> Any:
    def work(ctx: JobContext) -> dict[str, Any]:
        service = _service(entry)
        artifact = build_preview_artifact(
            service, slide_id=req.slide_id, engine=engine, progress=ctx.progress
        )
        loaded = service.load()
        images = snapshots.ensure_page_images(entry.pdf_path, len(loaded.deck.pages))
        manifest = preview_manifest(
            artifact,
            loaded.deck,
            images,
            media_url=lambda p: media_url(entry.pdf_path, p, stamp=True),
            track_url=media_url(entry.pdf_path, artifact.path),
            start_slide=req.start_slide,
            single_slide_transitions=req.single_slide_transitions,
        )
        return manifest.to_json()

    return work


def export_work(entry: DeckEntry, *, draft: bool, engine: Backend) -> Any:
    def work(ctx: JobContext) -> dict[str, Any]:
        service = _service(entry)
        output = entry.pdf_path.with_suffix(".mp4")
        with service.render_lock, engine_lock(engine):
            result = api.export(
                entry.pdf_path,
                output,
                sidecar_path=entry.sidecar_path,
                engine=engine,
                keep_scratch=True,  # an open preview may be streaming the page audio
                draft=draft,
                progress=ctx.progress,
            )
        return {"video": result.video.name, "duration": result.duration, "draft": draft}

    return work


def render_pages_work(entry: DeckEntry, near: int) -> Any:
    def work(ctx: JobContext) -> dict[str, Any]:
        count = len(_service(entry).page_ids()[0])
        images = snapshots.ensure_page_images(
            entry.pdf_path, count, near=near, progress=ctx.progress
        )
        return {"rendered": sum(1 for p in images if p is not None), "pages": count}

    return work


def warm_work(engine: Backend) -> Any:
    def work(ctx: JobContext) -> dict[str, Any]:
        from slidesonnet.models import TTSConfig
        from slidesonnet.tts import create_tts

        with engine_lock(engine):
            create_tts(TTSConfig(backend=engine)).warm()
        return {"engine": engine}

    return work


@router.post("/decks/{token}/jobs", response_model=JobDTO, status_code=202)
def post_job(request: Request, token: str, body: JobRequest, _m: None = Mutation) -> JobDTO:
    ctx = _ctx(request)
    entry = _entry(ctx, token)
    jobs = ctx.job_manager()
    try:
        narration_rev = _service(entry).narration_revision()
        if isinstance(body, GenerateJob):
            engine = _resolve_engine(entry, body.engine)
            if body.targets is None:
                targets: set[tuple[str, int]] | None = None
                count = len(_uncached(entry, engine))
            else:
                targets = {(t.slide_id, t.speech_index) for t in body.targets}
                count = len(targets) if body.force else len(targets & _uncached(entry, engine))
            _require_paid_approval(engine, count, body.allow_paid)
            inputs: dict[str, Any] = {
                "engine": engine,
                "narration_revision": narration_rev,
                "targets": sorted(targets) if targets is not None else None,
                "force": body.force,
            }
            job = jobs.submit(
                "generate",
                token,
                inputs,
                generate_work(entry, targets, force=body.force, engine=engine),
                dedupe_key=f"generate:{token}:{engine}:{narration_rev}:{inputs['targets']}:{body.force}",
            )
        elif isinstance(body, PreviewJob):
            engine = _resolve_engine(entry, body.engine)
            needed = _uncached(entry, engine, slide_id=body.slide_id)
            _require_paid_approval(engine, len(needed), body.allow_paid)
            if needed:
                _preempt_generation(ctx, entry, engine, needed)
            inputs = {
                "engine": engine,
                "narration_revision": narration_rev,
                "slide_id": body.slide_id,
            }
            job = jobs.submit(
                "preview",
                token,
                inputs,
                preview_work(entry, body, engine),
                dedupe_key=(
                    f"preview:{token}:{engine}:{narration_rev}:{body.slide_id}:"
                    f"{body.start_slide}:{body.single_slide_transitions}"
                ),
            )
        elif isinstance(body, ExportJob):
            engine = _resolve_engine(entry, body.engine)
            _require_paid_approval(engine, len(_uncached(entry, engine)), body.allow_paid)
            if not body.draft:
                blockers = api.export_blockers(entry.pdf_path)
                if blockers:
                    raise ApiError(409, "export_blocked", " ".join(blockers))
            inputs = {"engine": engine, "narration_revision": narration_rev, "draft": body.draft}
            job = jobs.submit(
                "export",
                token,
                inputs,
                export_work(entry, draft=body.draft, engine=engine),
                dedupe_key=f"export:{token}",
            )
        elif isinstance(body, WarmJob):
            engine = _resolve_engine(entry, body.engine)
            job = jobs.submit(
                "warm", token, {"engine": engine}, warm_work(engine), dedupe_key=f"warm:{engine}"
            )
        else:
            assert isinstance(body, RenderPagesJob)
            job = jobs.submit(
                "render_pages",
                token,
                {"near": body.near},
                render_pages_work(entry, body.near),
                dedupe_key=f"pages:{token}",
            )
    except (SidecarError, ConfigError) as exc:
        raise _load_error(exc) from exc
    return job_dto(job)


@router.get("/jobs", response_model=list[JobDTO])
def list_jobs(request: Request, deck: str | None = None, active: bool = False) -> list[JobDTO]:
    return [job_dto(j) for j in _ctx(request).job_manager().list(deck=deck, active_only=active)]


@router.get("/jobs/{job_id}", response_model=JobDTO)
def get_job(request: Request, job_id: str) -> JobDTO:
    job = _ctx(request).job_manager().get(job_id)
    if job is None:
        raise ApiError(404, "unknown_job", "No such job (it may have finished long ago).")
    return job_dto(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobDTO)
def cancel_job(request: Request, job_id: str, _m: None = Mutation) -> JobDTO:
    jobs = _ctx(request).job_manager()
    try:
        return job_dto(jobs.cancel(job_id))
    except KeyError:
        raise ApiError(404, "unknown_job", "No such job (it may have finished long ago).") from None


@router.get("/decks/{token}/export-blockers", response_model=list[str])
def get_export_blockers(request: Request, token: str) -> list[str]:
    return api.export_blockers(_entry(_ctx(request), token).pdf_path)


# ---- clip generation (the per-deck queue) --------------------------------------------
def _preempt_generation(
    ctx: ServerContext, entry: DeckEntry, engine: Backend, needed: set[tuple[str, int]]
) -> None:
    """A preview needs these clips now: pause a heavy clip generating for another slide."""
    import anyio.from_thread

    def on_loop() -> None:
        gen = ctx.generation().get(entry, engine, create=False)
        if gen is not None:
            gen.preempt_for(needed)

    with contextlib.suppress(RuntimeError):  # not called from a worker thread (tests)
        anyio.from_thread.run_sync(on_loop)


def _status(gen: DeckGeneration, queued: int = 0) -> GenerationStatusDTO:
    return GenerationStatusDTO.model_validate({**gen.status(), "queued": queued})


@router.post("/decks/{token}/generation", response_model=GenerationStatusDTO)
async def post_generation(
    request: Request, token: str, body: GenerateRequest, _m: None = Mutation
) -> GenerationStatusDTO:
    """Queue clips for generation (dedup'd across tabs; nearest-first)."""
    ctx = _ctx(request)
    entry = _entry(ctx, token)
    engine = await run_in_threadpool(_resolve_engine, entry, body.engine)
    uncached = await run_in_threadpool(_uncached, entry, engine)
    if body.targets is None:
        targets = uncached
    else:
        targets = {(t.slide_id, t.speech_index) for t in body.targets}
    count = len(targets) if body.force else len(targets & uncached)
    _require_paid_approval(engine, count, body.allow_paid)
    gen = ctx.generation().get(entry, engine)
    assert gen is not None
    queued = gen.enqueue(targets, force=body.force, allow_paid=body.allow_paid, owner=body.owner)
    return _status(gen, queued)


@router.get("/decks/{token}/generation", response_model=GenerationStatusDTO)
async def get_generation(
    request: Request, token: str, engine: Backend | None = None
) -> GenerationStatusDTO:
    ctx = _ctx(request)
    entry = _entry(ctx, token)
    resolved = await run_in_threadpool(_resolve_engine, entry, engine)
    gen = ctx.generation().get(entry, resolved)
    assert gen is not None
    return _status(gen)


@router.post("/decks/{token}/generation/cancel", response_model=CountDTO)
async def cancel_generation(
    request: Request, token: str, body: CancelGenerationRequest, _m: None = Mutation
) -> CountDTO:
    """Drop queued clips: this tab's (``owner``), or everything (the progress bar's ✕)."""
    ctx = _ctx(request)
    entry = _entry(ctx, token)
    gens = ctx.generation().for_deck(token)
    if body.engine is not None:
        resolved = await run_in_threadpool(_resolve_engine, entry, body.engine)
        gens = [g for g in gens if g.engine == resolved]
    return CountDTO(count=sum(g.cancel(body.owner) for g in gens))


@router.post("/decks/{token}/focus", response_model=CountDTO)
async def post_focus(
    request: Request, token: str, body: FocusRequest, _m: None = Mutation
) -> CountDTO:
    """Where a tab is looking: its slide's clips generate first."""
    ctx = _ctx(request)
    _entry(ctx, token)
    for gen in ctx.generation().for_deck(token):
        if body.engine is None or gen.engine == body.engine:
            gen.focus(body.slide_id)
    return CountDTO(count=len(ctx.generation().for_deck(token)))


# ---- pages, engines, meta ----------------------------------------------------------------
@router.get("/decks/{token}/pages", response_model=PagesDTO)
def get_pages(request: Request, token: str) -> PagesDTO:
    entry = _entry(_ctx(request), token)
    count = len(_service(entry).page_ids()[0])
    found = snapshots.page_images(entry.pdf_path, count)
    images = [
        media_url(entry.pdf_path, found[i], stamp=True) if i in found else None
        for i in range(count)
    ]
    return PagesDTO(images=images, rendered=len(found))


@router.get("/engines/{engine}/voices", response_model=EngineVoicesDTO)
def get_engine_voices(engine: Backend) -> EngineVoicesDTO:
    """An engine's pickable voices and its default (empty list = free-text ids)."""
    from slidesonnet.models import TTSConfig
    from slidesonnet.tts import create_tts

    tts = create_tts(TTSConfig(backend=engine))
    return EngineVoicesDTO(
        engine=engine, voices=list(tts.list_voices()), default=tts.default_voice()
    )


@router.get("/meta", response_model=MetaDTO)
def get_meta() -> MetaDTO:
    from slidesonnet.narration import transitions as trans
    from slidesonnet.tts import available_backends

    installed = set(available_backends())
    return MetaDTO(
        transitions=[
            TransitionFamilyDTO(key=f.key, label=f.label, options=list(f.options))
            for f in trans.FAMILIES
        ],
        aliases=dict(trans._ALIASES),
        engines=[
            EngineDTO(name=n, paid=b.paid, realtime=b.realtime, installed=n in installed)
            for n, b in sorted(BACKENDS.items())
        ],
        speeds=[1.0, 1.25, 1.5, 2.0],
    )


# ---- events (SSE) ----------------------------------------------------------------------
def _sse(event: Event) -> str:
    import json

    payload = {"type": event.type, "deck": event.deck, **event.data}
    return f"id: {event.seq}\nevent: {event.type}\ndata: {json.dumps(payload)}\n\n"


def _resync(seq: int) -> str:
    return f'id: {seq}\nevent: resync\ndata: {{"type": "resync"}}\n\n'


async def event_stream(
    bus: EventBus,
    sub: Subscription,
    last_seen: str | None,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    heartbeat: float = _HEARTBEAT_S,
) -> AsyncIterator[str]:
    """The SSE body: replay (or resync) after *last_seen*, then live events + keep-alives."""
    try:
        yield "retry: 2000\n\n"
        if last_seen is not None and last_seen.isdigit():
            missed = bus.since(int(last_seen))
            if missed is None:
                yield _resync(bus.last_seq)
            else:
                for event in missed:
                    yield _sse(event)
        while not await is_disconnected():
            if sub.overflowed:
                sub.overflowed = False
                while not sub.queue.empty():
                    sub.queue.get_nowait()
                yield _resync(bus.last_seq)
                continue
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=heartbeat)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield _sse(event)
    finally:
        bus.unsubscribe(sub)


@router.get("/events", response_class=StreamingResponse)
async def events(request: Request) -> StreamingResponse:
    """Deck/job/source events. Hints to refetch; ``resync`` means refetch everything."""
    ctx = _ctx(request)
    ctx.ensure_watcher()
    sub = ctx.bus.subscribe()
    last = request.headers.get("last-event-id") or request.query_params.get("since")
    return StreamingResponse(
        event_stream(ctx.bus, sub, last, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
