"""Backend context shared by the routes: registry, events, jobs, session, errors.

Security: the server binds to loopback by default, but a browser tab on any
site can still *send* requests to localhost. So every ``/api`` request must
carry an allowed ``Host`` (defeats DNS rebinding), and every mutation must be
same-origin and carry the per-process session token from ``GET
/api/v1/session`` — which a cross-origin page cannot read.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from slidesonnet.server.events import EventBus
from slidesonnet.server.generation import GenerationHub
from slidesonnet.server.jobs import JobManager
from slidesonnet.server.library import DeckRegistry
from slidesonnet.server.revisions import SourceRevisions

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
SESSION_HEADER = "X-SlideSonnet-Session"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
#: How often watched decks' sources are checked for outside changes.
WATCH_INTERVAL_S = 1.0


class ApiError(Exception):
    """An error with a stable code and a user-readable message."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass
class ServerContext:
    """Process-wide backend state: the deck registry, events, jobs, and the session."""

    registry: DeckRegistry
    bus: EventBus = field(default_factory=EventBus)
    jobs: JobManager | None = None
    generation_hub: GenerationHub | None = None
    session_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    allowed_hosts: set[str] = field(default_factory=lambda: set(LOOPBACK_HOSTS))
    #: Called with a deck's PDF when a client opens it (points the run-log at it).
    on_deck_open: Callable[[Path], None] | None = None
    last_opened: str | None = None
    #: Decks a client has opened, with the revisions last announced for each.
    watched: dict[str, SourceRevisions | None] = field(default_factory=dict)
    _watch_task: asyncio.Task[None] | None = None
    _jobs_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def generation(self) -> GenerationHub:
        """Per-deck clip generation queues (create and use on the event loop)."""
        if self.generation_hub is None:
            self.generation_hub = GenerationHub(self.bus)
        return self.generation_hub

    def job_manager(self) -> JobManager:
        """The job manager, created on first use (sync routes run on many threads)."""
        with self._jobs_lock:
            if self.jobs is None:
                self.jobs = JobManager(self.bus)
            return self.jobs

    def allow_host(self, host: str) -> None:
        if host and host not in ("0.0.0.0", "::"):
            self.allowed_hosts.add(host)

    # ---- source watching (hints for SSE subscribers) -------------------------
    def watch(self, token: str, revisions: SourceRevisions) -> None:
        self.watched[token] = revisions

    def ensure_watcher(self) -> None:
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = asyncio.get_running_loop().create_task(self._watch_loop())

    async def _watch_loop(self) -> None:
        from slidesonnet.server.decks import deck_service

        while True:
            await asyncio.sleep(WATCH_INTERVAL_S)
            for token, last in list(self.watched.items()):
                entry = self.registry.resolve(token)
                if entry is None:
                    self.watched.pop(token, None)
                    continue
                service = deck_service(entry.pdf_path, entry.sidecar_path)
                try:
                    now = await asyncio.to_thread(service.revisions)
                except OSError:  # a transient read error: try again next tick
                    logger.debug("watch: could not read %s", entry.pdf_path, exc_info=True)
                    continue
                if now != last:
                    self.watched[token] = now
                    self.bus.publish("deck.changed", deck=token, data=_revisions_json(now))

    def announce_write(self, token: str, revisions: SourceRevisions) -> None:
        """Publish an API write at once (and absorb it, so the watcher stays quiet)."""
        self.watched[token] = revisions
        self.bus.publish("deck.changed", deck=token, data=_revisions_json(revisions))

    def shutdown(self) -> None:
        """Stop the watcher and every job; run pending audio sweeps (server exit)."""
        from slidesonnet.server.decks import flush_all_prunes

        if self._watch_task is not None:
            self._watch_task.cancel()
            self._watch_task = None
        if self.generation_hub is not None:
            self.generation_hub.shutdown()
            self.generation_hub = None
        with self._jobs_lock:
            jobs, self.jobs = self.jobs, None
        if jobs is not None:
            jobs.shutdown()
        flush_all_prunes()


def _revisions_json(rev: SourceRevisions) -> dict[str, str]:
    return {"narration": rev.narration, "pdf": rev.pdf, "config": rev.config, "review": rev.review}


def context_of(app: FastAPI) -> ServerContext:
    ctx = getattr(app.state, "slidesonnet", None)
    if not isinstance(ctx, ServerContext):
        raise TypeError("the slideSonnet API is not installed on this app")
    return ctx


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _host_allowed(ctx: ServerContext, host_header: str | None) -> bool:
    if not host_header:
        return False
    hostname = urlsplit(f"//{host_header}").hostname or ""
    return hostname in ctx.allowed_hosts or f"[{hostname}]" in ctx.allowed_hosts


def check_mutation(request: Request) -> None:
    """Same-origin + session token, for every request that changes something."""
    ctx = context_of(request.app)
    origin = request.headers.get("origin")
    if origin is not None and urlsplit(origin).netloc != request.headers.get("host"):
        raise ApiError(403, "cross_origin", "Requests from other sites are not allowed.")
    if not secrets.compare_digest(request.headers.get(SESSION_HEADER, ""), ctx.session_token):
        raise ApiError(403, "bad_session", "This page's session expired — reload it.")


class ApiRoute(APIRoute):
    """Route class for ``/api/v1``: host check, stable error bodies, no caching.

    Done per route rather than with app middleware and exception handlers,
    because the API is mounted onto NiceGUI's app after it has started — and
    Starlette freezes its middleware stack at startup.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                if not _host_allowed(context_of(request.app), request.headers.get("host")):
                    raise ApiError(403, "bad_host", "Unexpected host name.")
                response = await original(request)
            except ApiError as exc:
                response = _error(exc.status, exc.code, exc.message)
            except RequestValidationError as exc:
                errors = exc.errors()
                first = errors[0] if errors else {}
                where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
                msg = str(first.get("msg", "invalid input"))
                response = _error(422, "invalid_input", f"{where}: {msg}" if where else msg)
            response.headers.setdefault("Cache-Control", "no-store")
            return response

        return handler
