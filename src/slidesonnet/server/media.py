"""Per-deck media: page images, preview tracks, and review base images.

One route serves every deck, keyed by its registry token — so deck A's page
images can never be served for deck B, and a token not in the registry never
touches the filesystem. The API's Host check applies here too. Paths are resolved (symlinks included) and must stay
under the deck's render directory. Responses support byte ranges (206/416), so
audio players can seek.

Caching: a URL that names exactly one immutable file may be cached forever —
a content-stamped image (``?v=<mtime_ns>-<size>``), a review base image (named
by its pixel hash), and every preview track under ``previews/`` (named by its
content hash). Everything else revalidates.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from slidesonnet.cache import render_dir
from slidesonnet.review.base import base_dir
from slidesonnet.server.context import ApiRoute
from slidesonnet.server.library import DeckRegistry, deck_token
from slidesonnet.server.previews import PREVIEWS_DIRNAME

MEDIA_PREFIX = "/ssmedia"
BASE_PREFIX = "_base/"
_IMMUTABLE = "public, max-age=31536000, immutable"


def is_content_stamp(value: str | None) -> bool:
    """True for a ``?v=<mtime_ns>-<size>`` stamp minted by :func:`media_url`.

    Checked by shape rather than by mere presence so that only a URL naming one
    exact byte-for-byte render can earn the immutable cache header.
    """
    if not value:
        return False
    mtime, _, size = value.partition("-")
    return mtime.isdigit() and size.isdigit()


def media_url(pdf_path: Path, path: Path, *, stamp: bool = False) -> str:
    """URL for a render artifact under the deck's render directory.

    Page images are re-rasterized to the same ``page-N.png`` paths on every
    recompile, so without a version the browser would show a stale image;
    *stamp* appends an ``(mtime, size)`` stamp so a re-render changes the URL.
    """
    rel = path.resolve().relative_to(render_dir(pdf_path).resolve())
    url = f"{MEDIA_PREFIX}/{deck_token(pdf_path)}/{rel.as_posix()}"
    if stamp:
        try:
            st = path.stat()
            url = f"{url}?v={st.st_mtime_ns}-{st.st_size}"
        except OSError:
            pass
    return url


def base_media_url(pdf_path: Path, path: Path) -> str:
    """URL for a review-base page image (named by its pixel hash, so immutable)."""
    return f"{MEDIA_PREFIX}/{deck_token(pdf_path)}/{BASE_PREFIX}{path.name}?v=0-{path.stem}"


def media_router(registry: Callable[[], DeckRegistry | None]) -> APIRouter:
    """The ``/ssmedia/{token}/{path}`` route, resolving tokens through *registry*.

    Served through :class:`~slidesonnet.server.context.ApiRoute` like the API, so
    the same Host check guards it (a DNS-rebound page can't read slides or audio).
    """
    router = APIRouter(route_class=ApiRoute)

    @router.get(MEDIA_PREFIX + "/{token}/{filename:path}", include_in_schema=False)
    def read_media(request: Request, token: str, filename: str) -> FileResponse:
        reg = registry()
        entry = reg.resolve(token) if reg is not None else None
        if entry is None:  # unknown deck: never touch the filesystem for it
            raise HTTPException(status_code=404, detail="Not Found")
        local_dir = render_dir(entry.pdf_path).resolve()
        immutable = is_content_stamp(request.query_params.get("v"))
        if filename.startswith(BASE_PREFIX):  # review base page images
            local_dir = (base_dir(entry.pdf_path) / "pages").resolve()
            filename = filename.removeprefix(BASE_PREFIX)
        elif filename.startswith(PREVIEWS_DIRNAME + "/"):
            immutable = True  # content-addressed: the name is the content
        filepath = (local_dir / filename).resolve()
        if not filepath.is_relative_to(local_dir) or not filepath.is_file():
            raise HTTPException(status_code=404, detail="Not Found")
        response = FileResponse(filepath)
        response.headers["Cache-Control"] = _IMMUTABLE if immutable else "no-cache"
        return response

    return router
