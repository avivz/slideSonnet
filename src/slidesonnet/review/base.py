"""The stored *base*: the last-cleared version of each slide.

Lives in ``<deck dir>/.slidesonnet/review/<deck stem>/`` — ``base.json`` plus
``pages/<hash>.png``. Only :func:`snapshot` (reset everything to current) and
:func:`advance` (move named slides to current, on Clear) change it. It is never
committed; losing it just means re-snapshotting, which loses pending diffs but
no work. Callers hold the review lock (:func:`slidesonnet.review.ops.transaction`)
around :func:`snapshot` and :func:`advance`.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from slidesonnet.builds import deck_pdf
from slidesonnet.cache import REVIEW_DIRNAME, cache_root
from slidesonnet.exceptions import ReviewError
from slidesonnet.pdf.reader import is_final_build
from slidesonnet.review.versions import DeckVersion, SlideVersion, capture, store_images

_FORMAT = 1


def base_dir(pdf_path: Path) -> Path:
    return cache_root(pdf_path) / REVIEW_DIRNAME / deck_pdf(pdf_path).stem  # one per deck


def _base_file(pdf_path: Path) -> Path:
    return base_dir(pdf_path) / "base.json"


def _pages_dir(pdf_path: Path) -> Path:
    return base_dir(pdf_path) / "pages"


def has_base(pdf_path: Path) -> bool:
    return _base_file(pdf_path).exists()


def load_base(pdf_path: Path) -> DeckVersion | None:
    """The stored base, or None when the deck has none yet."""
    path = _base_file(pdf_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    slides = {
        sid: SlideVersion(image_hash=s["image"], text=s["text"], narration=s["narration"])
        for sid, s in data["slides"].items()
    }
    return DeckVersion(order=tuple(data["order"]), slides=slides)


def _save(pdf_path: Path, version: DeckVersion) -> None:
    data = {
        "format": _FORMAT,
        "order": list(version.order),
        "slides": {
            sid: {"image": s.image_hash, "text": s.text, "narration": s.narration}
            for sid, s in version.slides.items()
        },
    }
    path = _base_file(pdf_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".base.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _prune_images(pdf_path, version)


def _prune_images(pdf_path: Path, version: DeckVersion) -> None:
    keep = {f"{s.image_hash}.png" for s in version.slides.values()}
    pages = _pages_dir(pdf_path)
    if pages.is_dir():
        for png in pages.glob("*.png"):
            if png.name not in keep:
                png.unlink(missing_ok=True)


def reference_images(pdf_path: Path) -> dict[str, Path]:
    """Slide id -> the base's stored page image, for a tolerant capture."""
    base = load_base(pdf_path)
    if base is None:
        return {}
    pages = _pages_dir(pdf_path)
    return {sid: pages / f"{v.image_hash}.png" for sid, v in base.slides.items()}


def _require_plain(pdf_path: Path) -> None:
    if is_final_build(pdf_path):
        raise ReviewError(
            f"{pdf_path.name} is a final build (page numbers shown) — recompile it "
            "normally (without \\ssfinal) before taking the review base"
        )


def snapshot(pdf_path: Path, *, sidecar_path: Path | None = None) -> DeckVersion:
    """Reset the base to the current deck (every slide, and the order)."""
    _require_plain(pdf_path)
    version = capture(pdf_path, sidecar_path=sidecar_path, images_dir=_pages_dir(pdf_path))
    _save(pdf_path, version)
    return version


def advance(
    pdf_path: Path,
    slide_ids: set[str],
    *,
    adopt_order: bool,
    sidecar_path: Path | None = None,
    current: DeckVersion | None = None,
) -> DeckVersion:
    """Move *slide_ids* to their current version (Clear accepted).

    A named slide that no longer exists leaves the base; a new one joins it.
    With *adopt_order* the base takes the current order (restricted to slides
    the base holds); otherwise the old order is kept, with newly added slides
    placed as in the current order.

    Reuse *current* when the caller already captured this PDF and narration.
    Only missing images for the named slides are rendered and stored.
    """
    _require_plain(pdf_path)
    base = load_base(pdf_path)
    if base is None:
        raise ReviewError("no review base yet — take one with `slidesonnet review snapshot`")
    if current is None:
        current = capture(
            pdf_path,
            sidecar_path=sidecar_path,
            reference=reference_images(pdf_path),
        )
    store_images(pdf_path, current, slide_ids, _pages_dir(pdf_path))
    slides = dict(base.slides)
    for sid in slide_ids:
        if sid in current.slides:
            slides[sid] = current.slides[sid]
        else:
            slides.pop(sid, None)
    if adopt_order:
        order = [sid for sid in current.order if sid in slides]
        order += [sid for sid in base.order if sid in slides and sid not in order]
    else:
        order = [sid for sid in base.order if sid in slides]
        for sid in current.order:  # newcomers slot in after their current predecessor
            if sid in slides and sid not in order:
                i = current.order.index(sid)
                prev = next((p for p in reversed(current.order[:i]) if p in order), None)
                order.insert(order.index(prev) + 1 if prev is not None else 0, sid)
    version = DeckVersion(order=tuple(order), slides=slides)
    _save(pdf_path, version)
    return version


def base_image(pdf_path: Path, slide_id: str) -> Path | None:
    """The stored page image of *slide_id*'s base version, if it has one."""
    base = load_base(pdf_path)
    if base is None or slide_id not in base.slides:
        return None
    path = _pages_dir(pdf_path) / f"{base.slides[slide_id].image_hash}.png"
    return path if path.exists() else None
