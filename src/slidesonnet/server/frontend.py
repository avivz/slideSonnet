"""Serving the built Vue frontend: the app shell at ``/`` and its assets at ``/ui/``.

The bundle is compiled from ``frontend/`` into ``server/static/`` and shipped
inside the Python package, so an installed wheel or sdist needs no Node. A
source checkout that hasn't been built yet gets a plain page saying how to
build it, instead of a blank screen or a 404.

Only real app routes get the shell (``/`` for now; the deck routes join as
their screens move over). Unknown ``/ui/`` paths are real 404s, never the
shell, so a missing asset fails loudly.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

STATIC_DIR = Path(__file__).parent / "static"
ASSET_PREFIX = "/ui"
_IMMUTABLE = "public, max-age=31536000, immutable"

UNBUILT_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>slideSonnet — not built</title>
<style>body{background:#0e1116;color:#e8ecf3;font:14px/1.6 system-ui,sans-serif;
display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:52ch;padding:24px}
code{background:#1e2531;padding:2px 6px;border-radius:4px}</style></head>
<body><main><h1>The editor's interface hasn't been built</h1>
<p>This is a source checkout, and the browser part of the editor is compiled
separately. Build it once with <code>make frontend</code> (needs Node 20.19 or
newer), then reload this page.</p>
<p>Installed copies of slideSonnet come with it built.</p></main></body></html>
"""


def index_path() -> Path:
    return STATIC_DIR / "index.html"


def is_built() -> bool:
    return index_path().is_file()


def app_shell() -> Response:
    """The frontend's ``index.html`` (always revalidated), or the how-to-build page."""
    if not is_built():
        return HTMLResponse(UNBUILT_PAGE, status_code=503)
    response = FileResponse(index_path(), media_type="text/html")
    response.headers["Cache-Control"] = "no-cache"
    return response


def frontend_router() -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/")
    def library_page() -> Response:
        return app_shell()

    @router.get(ASSET_PREFIX + "/{path:path}")
    def asset(path: str) -> FileResponse:
        root = STATIC_DIR.resolve()
        file = (root / path).resolve()
        if not file.is_relative_to(root) or not file.is_file() or file.name == "index.html":
            raise HTTPException(status_code=404, detail="Not Found")
        response = FileResponse(file)
        # Vite names every built asset by its content hash, so it never changes.
        hashed = path.startswith("assets/")
        response.headers["Cache-Control"] = _IMMUTABLE if hashed else "no-cache"
        return response

    return router
