"""Background TTS generation queue for the editor.

Generation used to run through the editor's single ``busy`` gate, so making one
clip froze typing, navigation, and every other action. This queue moves
synthesis onto a long-lived background worker: callers ``enqueue`` work and the
UI stays live while clips render.

Two requests for the *same* clip never synthesize twice. Jobs are keyed on the
content-addressed cache filename (text + voice + backend + config), so a second
request for an in-flight clip — a double-click, or pressing play right after
regenerate — attaches to the running job instead of launching a duplicate. Two
byte-identical utterances on different slides collapse to one job for the same
reason.

This module is deliberately NiceGUI-free (its dependencies are injected as
callables) so the dedup/coalesce logic is unit-testable without a browser.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from slidesonnet.audio.synth import _ref_targets
from slidesonnet.config import Config
from slidesonnet.hashing import audio_cache_path_or_alt
from slidesonnet.narration.model import Deck

logger = logging.getLogger(__name__)

JobKey = str  # the content-addressed cache filename — one synthesis per key
JobStatus = Literal["queued", "running", "done", "error"]
Target = tuple[str, int]  # (slide_id, speech_index)

# Injected dependencies (the GUI binds these to an EditorState; tests fake them).
DeckProvider = Callable[[], tuple[Deck, Config, Path]]  # -> (deck, config, audio_dir)
SynthFn = Callable[[set[Target], bool], object]  # (targets, force) -> synthesize; result ignored
IsPaid = Callable[[], bool]


@dataclass(eq=False)
class JobHandle:
    """One in-flight (or finished) synthesis job; ``done`` fires on completion."""

    key: JobKey
    refs: set[Target]
    done: asyncio.Event
    status: JobStatus = "queued"
    error: Exception | None = None
    force: bool = False


class JobQueue:
    """An asyncio work queue with one background worker and per-clip dedup."""

    def __init__(
        self,
        *,
        deck_provider: DeckProvider,
        synth: SynthFn,
        is_paid: IsPaid,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._deck_provider = deck_provider
        self._synth = synth
        self._is_paid = is_paid
        self._on_change = on_change or (lambda: None)
        self._queue: asyncio.Queue[JobHandle] = asyncio.Queue()
        self._inflight: dict[JobKey, JobHandle] = {}
        self._worker_task: asyncio.Task[None] | None = None

    # ---- lifecycle ------------------------------------------------------
    def start(self) -> None:
        """Spawn the background worker (idempotent)."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    def stop(self) -> None:
        """Cancel the background worker (e.g. on client disconnect)."""
        if self._worker_task is not None:
            self._worker_task.cancel()
            self._worker_task = None

    # ---- producing ------------------------------------------------------
    def enqueue(
        self, targets: set[Target], *, force: bool = False, allow_paid: bool = False
    ) -> list[JobHandle]:
        """Queue synthesis of *targets*; return a handle per launched/attached job.

        Already-cached clips are skipped unless *force*. A target whose clip is
        already in flight attaches to that job (no duplicate synthesis). On a
        paid engine the call is refused unless *allow_paid* (a defensive
        invariant so an automatic trigger can never silently bill).
        """
        if self._is_paid() and not allow_paid:
            return []
        deck, config, audio_dir = self._deck_provider()
        handles: list[JobHandle] = []
        for ref, target in _ref_targets(deck, config, audio_dir):
            rid = (ref.slide_id, ref.speech_index)
            if rid not in targets:
                continue
            if not force and audio_cache_path_or_alt(target) is not None:
                continue
            key = target.name
            existing = self._inflight.get(key)
            if existing is not None:
                existing.refs.add(rid)
                if existing not in handles:
                    handles.append(existing)
                continue
            handle = JobHandle(key=key, refs={rid}, done=asyncio.Event(), force=force)
            self._inflight[key] = handle
            self._queue.put_nowait(handle)
            handles.append(handle)
        return handles

    # ---- querying / awaiting -------------------------------------------
    def handle_for(self, slide_id: str, speech_index: int) -> JobHandle | None:
        """The in-flight job covering this clip, if any (drives the per-clip UI)."""
        for handle in self._inflight.values():
            if (slide_id, speech_index) in handle.refs:
                return handle
        return None

    async def await_targets(self, targets: set[Target]) -> None:
        """Block until every in-flight job covering *targets* finishes.

        Targets with no in-flight job return immediately — used by play to wait
        on exactly the clips it needs instead of racing or re-triggering synth.
        """
        deck, config, audio_dir = self._deck_provider()
        keys = {
            target.name
            for ref, target in _ref_targets(deck, config, audio_dir)
            if (ref.slide_id, ref.speech_index) in targets
        }
        for key in keys:
            handle = self._inflight.get(key)
            if handle is not None:
                await handle.done.wait()

    async def drain(self) -> None:
        """Block until the queue is empty and all jobs have finished (tests/shutdown)."""
        await self._queue.join()

    async def drain_after(self, handles: Iterable[JobHandle]) -> None:
        """Block until each given handle finishes."""
        for handle in handles:
            await handle.done.wait()

    # ---- worker ---------------------------------------------------------
    async def _worker(self) -> None:
        while True:
            handle = await self._queue.get()
            try:
                handle.status = "running"
                self._emit()
                await asyncio.to_thread(self._synth, set(handle.refs), handle.force)
                handle.status = "done"
            except Exception as exc:  # keep the worker alive; surface on the handle
                handle.status = "error"
                handle.error = exc
                logger.exception("background generation failed for %s", handle.key)
            finally:
                self._inflight.pop(handle.key, None)
                handle.done.set()
                self._emit()
                self._queue.task_done()

    def _emit(self) -> None:
        try:
            self._on_change()
        except Exception:  # the client may have disconnected mid-job
            logger.debug("job on_change failed (client gone?)", exc_info=True)
