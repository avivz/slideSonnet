"""The editor's FastAPI app: :func:`create_app` mounts the API, media, and frontend.

One process, one origin, one port.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from slidesonnet.server.context import API_PREFIX, ServerContext, context_of
from slidesonnet.server.library import DeckRegistry


def create_app(registry: DeckRegistry, *, host: str | None = None) -> FastAPI:
    """The editor's web app: the API, media, and the bundled frontend.

    Everything the process serves — explicit lifetimes, no process-global app:
    the context (jobs, generation queues, event bus) lives on ``app.state`` and
    is shut down with the app.
    """
    from slidesonnet.server.frontend import frontend_router
    from slidesonnet.server.media import media_router
    from slidesonnet.server.routes import router

    ctx = ServerContext(registry=registry)
    if host:
        ctx.allow_host(host)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        ctx.shutdown()

    app = FastAPI(
        title="slideSonnet", version="1", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.slidesonnet = ctx
    app.include_router(router, prefix=API_PREFIX)
    app.include_router(media_router(lambda: ctx.registry))
    app.include_router(frontend_router())
    return app


def create_api_app(registry: DeckRegistry) -> FastAPI:
    """:func:`create_app` for the test client (which calls itself ``testserver``)."""
    app = create_app(registry)
    context_of(app).allowed_hosts.add("testserver")
    return app
