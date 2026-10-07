"""Preview artifacts: immutable, content-addressed per-slide preview tracks, plus their manifest.

The editor plays the deck slide by slide, one preview track per slide. Every
preview used to render to one fixed ``track.wav`` that was rewritten in place
and fetched with a one-shot ``?t=`` token (B4): two previews in flight, or a
browser holding the old URL, could play the wrong slide's audio. Now each built
track is copied to ``previews/<content-hash>.wav`` — a file that is never
rewritten, so its URL can be cached forever and always means the same audio.

Builds for one deck are serialized (they share the render directory), and a
slide's preview assembles in its own sub-directory so it never evicts the
whole-deck page audio that export reuses.

The manifest is what a browser-side player needs to play a preview on its own
clock: the track URL, its duration, and where each spoken line plays in it.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slidesonnet import api
from slidesonnet.api import SpeechSpan
from slidesonnet.cache import render_dir
from slidesonnet.config import load_config
from slidesonnet.models import Backend, ProgressFn
from slidesonnet.server.decks import DeckService
from slidesonnet.server.engines import engine_lock
from slidesonnet.server.revisions import file_sha256

PREVIEWS_DIRNAME = "previews"
SLIDE_PREVIEW_DIRNAME = "slide-preview"
#: Preview tracks kept per deck (newest first); older ones are deleted.
KEEP_PREVIEWS = 8


@dataclass(frozen=True)
class PreviewArtifact:
    """One slide's built preview: an immutable track and the inputs it was built from."""

    id: str
    path: Path
    duration: float
    slide_id: str
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
    slide_id: str,
    engine: Backend | None,
    progress: ProgressFn | None = None,
    approved_clips: Collection[str] | None = None,
) -> PreviewArtifact:
    """Build (or reuse) one slide's preview. Blocking.

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
        rdir = render_dir(pdf) / SLIDE_PREVIEW_DIRNAME
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
        slide_id=slide_id,
        narration_revision=revisions.narration,
        pdf_revision=revisions.pdf,
        engine=engine,
        speech=list(preview.speech),
        silences=_silences(artifact_id, path, list(preview.speech)),
    )


@dataclass(frozen=True)
class PreviewManifest:
    """Everything a browser-side player needs to play one preview on its own clock."""

    artifact_id: str
    slide_id: str
    narration_revision: str
    pdf_revision: str
    engine: str | None
    media_url: str
    duration: float
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
            "speech": self.speech,
        }


def preview_manifest(artifact: PreviewArtifact, *, track_url: str) -> PreviewManifest:
    """The manifest for *artifact*: its track at *track_url*, and where each line plays."""
    return PreviewManifest(
        artifact_id=artifact.id,
        slide_id=artifact.slide_id,
        narration_revision=artifact.narration_revision,
        pdf_revision=artifact.pdf_revision,
        engine=artifact.engine,
        media_url=track_url,
        duration=artifact.duration,
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
