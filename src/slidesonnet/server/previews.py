"""Preview artifacts: immutable, content-addressed preview tracks, plus their manifest.

Every preview used to render to one fixed ``track.wav`` that was rewritten in
place and fetched with a one-shot ``?t=`` token (B4): two previews in flight, or
a browser holding the old URL, could play the wrong slide's audio. Now each
built track is copied to ``previews/<content-hash>.wav`` — a file that is never
rewritten, so its URL can be cached forever and always means the same audio.

Builds for one deck are serialized (they share the render directory), and a
single-slide preview assembles in its own sub-directory so it never evicts the
whole-deck page audio that export also reuses.

The manifest is what a browser-side player needs to play a preview on its own
clock: the track URL, duration, cue sheet, page images, and the transition
schedule (the same absorb-into-hold timing the export uses).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slidesonnet import api
from slidesonnet.api import SpeechSpan
from slidesonnet.audio.track import Cue
from slidesonnet.cache import render_dir
from slidesonnet.config import load_config
from slidesonnet.diagnostics import boundary_transition
from slidesonnet.models import Backend, ProgressFn
from slidesonnet.narration.model import Deck, PageNarration, Transition
from slidesonnet.server.decks import DeckService
from slidesonnet.server.engines import engine_lock
from slidesonnet.server.revisions import file_sha256

PREVIEWS_DIRNAME = "previews"
SLIDE_PREVIEW_DIRNAME = "slide-preview"
#: Preview tracks kept per deck (newest first); older ones are deleted.
KEEP_PREVIEWS = 8


@dataclass(frozen=True)
class PreviewArtifact:
    """One built preview: an immutable track and the inputs it was built from."""

    id: str
    path: Path
    duration: float
    cues: list[Cue]
    slide_id: str | None  # None = whole deck
    narration_revision: str
    pdf_revision: str
    engine: str | None
    speech: list[SpeechSpan] = field(default_factory=list)
    #: Per utterance, the silent stretches inside it (absolute track times).
    silences: list[list[tuple[float, float]]] = field(default_factory=list)


#: Silences per built track (artifacts are immutable, so their id is the key).
_SILENCES: dict[str, list[list[tuple[float, float]]]] = {}
_SILENCES_KEPT = 16


def _silences(
    artifact_id: str, track: Path, speech: list[SpeechSpan]
) -> list[list[tuple[float, float]]]:
    found = _SILENCES.get(artifact_id)
    if found is None:
        from slidesonnet.server.voicing import silences_in

        found = silences_in(track, speech)
        if len(_SILENCES) >= _SILENCES_KEPT:
            _SILENCES.pop(next(iter(_SILENCES)))
        _SILENCES[artifact_id] = found
    return found


def previews_dir(pdf_path: Path) -> Path:
    return render_dir(pdf_path) / PREVIEWS_DIRNAME


def _publish(track: Path, dest_dir: Path) -> tuple[str, Path]:
    """Copy *track* to ``<dest_dir>/<hash>.wav`` (atomically, once) and return it."""
    artifact_id = file_sha256(track)[:20]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{artifact_id}{track.suffix}"
    if dest.exists():
        with contextlib.suppress(OSError):
            os.utime(dest)  # most recently used: keep it through the next prune
        return artifact_id, dest
    fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix=".tmp-", suffix=track.suffix)
    os.close(fd)
    try:
        shutil.copyfile(track, tmp)
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return artifact_id, dest


def prune_previews(
    pdf_path: Path, *, keep: int = KEEP_PREVIEWS, protect: Path | None = None
) -> int:
    """Delete all but the *keep* most recently used preview tracks; never *protect*."""
    folder = previews_dir(pdf_path)
    if not folder.is_dir():
        return 0
    tracks = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
    tracks.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for old in tracks[keep:]:
        if protect is not None and old == protect:
            continue
        with contextlib.suppress(OSError):
            old.unlink()
            removed += 1
    return removed


def build_preview_artifact(
    service: DeckService,
    *,
    slide_id: str | None,
    engine: Backend | None,
    progress: ProgressFn | None = None,
    approved_clips: Collection[str] | None = None,
) -> PreviewArtifact:
    """Build (or reuse) the preview for one slide or the whole deck. Blocking.

    Takes the deck's render lock, then the engine's synthesis lock — the one
    order every caller uses, so preview and export can't deadlock.

    Revisions are read *before* the build: if the sidecar changes mid-build, the
    artifact is labelled with the older revision and a client comparing it to
    its current snapshot knows to rebuild.
    """
    pdf = service.pdf_path
    revisions = service.revisions()
    backend = engine or load_config(pdf).tts.backend
    # Lock order is always render, then engine (export takes them the same way).
    with service.render_lock, engine_lock(backend):
        rdir = render_dir(pdf) / SLIDE_PREVIEW_DIRNAME if slide_id else render_dir(pdf)
        preview = api.build_preview(
            pdf,
            sidecar_path=service.sidecar_path,
            engine=engine,
            only_id=slide_id,
            progress=progress,
            render_dir=rdir,
            approved_clips=approved_clips,
        )
        artifact_id, path = _publish(preview.track, previews_dir(pdf))
        prune_previews(pdf, protect=path)
    return PreviewArtifact(
        id=artifact_id,
        path=path,
        duration=preview.total_duration,
        cues=list(preview.cues),
        slide_id=slide_id,
        narration_revision=revisions.narration,
        pdf_revision=revisions.pdf,
        engine=engine,
        speech=list(preview.speech),
        silences=_silences(artifact_id, path, list(preview.speech)),
    )


# ---- the transition schedule a browser player follows --------------------------
def morph_schedule(
    cues: Sequence[Cue],
    deck: Deck,
    images: Sequence[Path | None],
    media_url: Callable[[Path], str],
) -> list[dict[str, Any]]:
    """Per-boundary morph steps for a whole-deck preview.

    Mirrors the export's absorb-into-hold model: each animated boundary's morph
    *completes* at the next slide's cue start (``at``), running ``dur`` seconds
    of the outgoing slide's trailing hold — so the preview's transition lands at
    the same instant the cue flips, just as the rendered wipe does. Plain cuts
    emit nothing.
    """
    steps: list[dict[str, Any]] = []
    index = {sid: i for i, sid in enumerate(deck.pages)}
    for i in range(len(cues) - 1):
        a_start, a_sid = cues[i]
        b_start, b_sid = cues[i + 1]
        tr = boundary_transition(deck.page_narration(a_sid), deck.page_narration(b_sid))
        if not tr.is_animated:
            continue
        ia, ib = index.get(a_sid), index.get(b_sid)
        a_img = images[ia] if ia is not None and ia < len(images) else None
        b_img = images[ib] if ib is not None and ib < len(images) else None
        if a_img is None or b_img is None:
            continue  # page not rasterized (no pdftoppm) — fall back to a flip
        span = b_start - a_start
        steps.append(
            {
                "at": b_start,
                "dur": max(0.05, min(tr.seconds, span)),
                "kind": tr.kind,
                "from": media_url(a_img),
                "to": media_url(b_img),
            }
        )
    return steps


def single_slide_morph(
    block: PageNarration,
    incoming: Transition,
    index: int,
    images: Sequence[Path | None],
    total: float,
    media_url: Callable[[Path], str],
    *,
    enabled: bool = True,
) -> list[dict[str, Any]]:
    """Morph steps for a *single-slide* preview: its in- and out-transition.

    *incoming* is the effective transition entering this slide (its boundary with
    the previous slide); ``block.transition_out`` is the boundary with the next.
    A missing neighbour (the deck's first/last slide) morphs against a black
    frame (``from``/``to`` is ``None``). Each is clamped to half the slide so the
    two never overlap. *enabled* is the "Play transitions in single-slide
    preview" toggle (off by default): when False a single-slide play is a cut.
    """
    if not enabled:
        return []

    def url(j: int) -> str | None:
        image = images[j] if 0 <= j < len(images) else None
        return media_url(image) if image is not None else None

    here = url(index)
    if here is None:  # no rasterized image — nothing to morph
        return []
    steps: list[dict[str, Any]] = []
    if incoming.is_animated:
        d = max(0.05, min(incoming.seconds, total / 2))
        steps.append({"at": d, "dur": d, "kind": incoming.kind, "from": url(index - 1), "to": here})
    t_out = block.transition_out
    if t_out.is_animated:
        d = max(0.05, min(t_out.seconds, total / 2))
        steps.append(
            {"at": total, "dur": d, "kind": t_out.kind, "from": here, "to": url(index + 1)}
        )
    return steps


@dataclass(frozen=True)
class PreviewManifest:
    """Everything a browser-side player needs to play one preview on its own clock."""

    artifact_id: str
    slide_id: str | None
    narration_revision: str
    pdf_revision: str
    engine: str | None
    media_url: str
    duration: float
    start_at: float
    cues: list[dict[str, Any]] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    speech: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "slide_id": self.slide_id,
            "narration_revision": self.narration_revision,
            "pdf_revision": self.pdf_revision,
            "engine": self.engine,
            "media_url": self.media_url,
            "duration": self.duration,
            "start_at": self.start_at,
            "cues": self.cues,
            "pages": self.pages,
            "transitions": self.transitions,
            "speech": self.speech,
        }


def preview_manifest(
    artifact: PreviewArtifact,
    deck: Deck,
    images: Sequence[Path | None],
    *,
    media_url: Callable[[Path], str],
    track_url: str,
    start_slide: str | None = None,
    single_slide_transitions: bool = False,
) -> PreviewManifest:
    """The manifest for *artifact*: cues, page images, and the transition schedule.

    *images* is indexed like ``deck.pages``, with ``None`` for a page not
    rendered yet. A deck preview starts at *start_slide*'s cue (the slide the
    user is on), so playing the deck from slide 7 doesn't rewind to slide 1.
    """
    by_id = {sid: i for i, sid in enumerate(deck.pages)}

    def image_for(sid: str) -> str | None:
        i = by_id.get(sid)
        image = images[i] if i is not None and i < len(images) else None
        return media_url(image) if image is not None else None

    if artifact.slide_id is None:
        cues = artifact.cues
        steps = morph_schedule(cues, deck, images, media_url)
        start_at = next((start for start, sid in cues if sid == start_slide), 0.0)
        page_ids = [sid for _, sid in cues]
    else:
        sid = artifact.slide_id
        cues = [Cue(0.0, sid)]
        index = by_id.get(sid, 0)
        from slidesonnet.server.editing import incoming_transition

        steps = single_slide_morph(
            deck.page_narration(sid),
            incoming_transition(deck, sid) if sid in by_id else Transition(),
            index,
            images,
            artifact.duration,
            media_url,
            enabled=single_slide_transitions,
        )
        start_at = 0.0
        page_ids = [sid]
    return PreviewManifest(
        artifact_id=artifact.id,
        slide_id=artifact.slide_id,
        narration_revision=artifact.narration_revision,
        pdf_revision=artifact.pdf_revision,
        engine=artifact.engine,
        media_url=track_url,
        duration=artifact.duration,
        start_at=start_at,
        cues=[{"start": start, "slide_id": sid} for start, sid in cues],
        pages=[{"slide_id": sid, "image_url": image_for(sid)} for sid in dict.fromkeys(page_ids)],
        transitions=steps,
        speech=[
            {
                "slide_id": sp.slide_id,
                "index": sp.index,
                "start": sp.start,
                "end": sp.end,
                "silences": [list(g) for g in gaps],
            }
            for sp, gaps in zip(
                artifact.speech,
                artifact.silences or [[] for _ in artifact.speech],
                strict=True,
            )
        ],
    )
