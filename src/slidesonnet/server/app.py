"""The editor's FastAPI app: :func:`create_app` mounts the API, media, and frontend.

One process, one origin, one port. :func:`install_api` stays idempotent (it
asks the app whether its routes are present) so a rebuilt app never ends up
with duplicate routes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from slidesonnet.server.context import API_PREFIX, ServerContext, context_of
from slidesonnet.server.library import DeckRegistry


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


def create_app(registry: DeckRegistry, *, host: str | None = None) -> FastAPI:
    """The editor's web app: the API, media, and the bundled frontend.

    Everything the process serves — explicit lifetimes, no process-global app:
    the context (jobs, generation queues, event bus) lives on ``app.state`` and
    is shut down with the app.
    """
    holder: list[ServerContext] = []

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        for ctx in holder:
            ctx.shutdown()

    app = FastAPI(
        title="slideSonnet", version="1", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    ctx = install_api(app, registry, host=host)
    install_frontend(app)
    holder.append(ctx)
    return app


def create_api_app(registry: DeckRegistry) -> FastAPI:
    """:func:`create_app` for the test client (which calls itself ``testserver``)."""
    app = create_app(registry)
    context_of(app).allowed_hosts.add("testserver")
    return app
