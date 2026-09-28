"""Mounting the backend on a FastAPI app.

During the migration :func:`install_api` mounts the API, media, and events on
NiceGUI's own FastAPI app (one process, one origin, one port) — safely even
after that app has started. :func:`create_api_app` builds a plain FastAPI app
with the same routers: what the API tests use today, and what the editor runs
on once NiceGUI is gone.
"""

from __future__ import annotations

from fastapi import FastAPI

from slidesonnet.gui.library import DeckRegistry
from slidesonnet.server.context import API_PREFIX, ServerContext, context_of


def _mounted(app: FastAPI) -> bool:
    return any(getattr(r, "path", "") == API_PREFIX + "/session" for r in app.routes)


def install_api(app: FastAPI, registry: DeckRegistry, *, host: str | None = None) -> ServerContext:
    """Mount the API and media routes on *app* (idempotent; updates the registry).

    Whether the routes are present is asked of the app itself rather than
    remembered: the NiceGUI test server rebuilds its routes per test while the
    app object (and its state) lives on.
    """
    ctx = getattr(app.state, "slidesonnet", None)
    if not isinstance(ctx, ServerContext):
        ctx = ServerContext(registry=registry)
        app.state.slidesonnet = ctx
    ctx.registry = registry
    if host:
        ctx.allow_host(host)
    if not _mounted(app):
        from slidesonnet.server.media import media_router
        from slidesonnet.server.routes import router

        app.include_router(router, prefix=API_PREFIX)
        app.include_router(media_router(lambda: context_of(app).registry))
    return ctx


def install_frontend(app: FastAPI) -> None:
    """Serve the built Vue app shell at ``/`` and its assets under ``/ui`` (idempotent)."""
    from slidesonnet.server.frontend import ASSET_PREFIX, frontend_router

    if not any(getattr(r, "path", "") == ASSET_PREFIX + "/{path:path}" for r in app.routes):
        app.include_router(frontend_router())


def create_api_app(registry: DeckRegistry) -> FastAPI:
    """A plain FastAPI app serving the API and media (tests; post-NiceGUI serving)."""
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    holder: list[ServerContext] = []

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        for ctx in holder:
            ctx.shutdown()

    app = FastAPI(title="slideSonnet", version="1", lifespan=lifespan)
    ctx = install_api(app, registry)
    install_frontend(app)
    ctx.allowed_hosts.add("testserver")
    holder.append(ctx)
    return app
