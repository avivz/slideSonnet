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
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from slidesonnet.audio.synth import _ref_targets
from slidesonnet.cancellation import cancel_scope
from slidesonnet.config import Config
from slidesonnet.exceptions import GenerationCancelled
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
CurrentIndex = Callable[[], int | None]  # -> the slide index the user is on (drives priority)


@dataclass(eq=False)
class JobHandle:
    """One in-flight (or finished) synthesis job; ``done`` fires on completion."""

    key: JobKey
    refs: set[Target]
    done: asyncio.Event
    status: JobStatus = "queued"
    error: Exception | None = None
    force: bool = False
    #: Set to ask a heavy engine to abort this clip mid-generation (play preempt).
    #: A cancelled job is re-queued (not failed) and the flag cleared for the retry.
    cancel: threading.Event = field(default_factory=threading.Event)
    #: ``time.monotonic()`` when this clip started running (drives the elapsed timer).
    started_at: float | None = None


class JobQueue:
    """A background generation queue: one worker, per-clip dedup, distance-priority.

    The worker doesn't run jobs first-in-first-out. Each time it's free it picks
    the *best-next* pending clip — the one nearest the slide you're on, current
    and ahead before behind (see :meth:`_priority`). Because the pick is lazy
    (decided when the worker frees up, against where you are *then*), navigating
    re-prioritizes the backlog for free, without disturbing the running clip.
    """

    def __init__(
        self,
        *,
        deck_provider: DeckProvider,
        synth: SynthFn,
        is_paid: IsPaid,
        current_index: CurrentIndex | None = None,
        on_change: Callable[[], None] | None = None,
        on_error: Callable[[JobHandle], None] | None = None,
    ) -> None:
        self._deck_provider = deck_provider
        self._synth = synth
        self._is_paid = is_paid
        self._current_index = current_index or (lambda: None)
        self._on_change = on_change or (lambda: None)
        self._on_error = on_error or (lambda _h: None)
        self._pending: dict[JobKey, JobHandle] = {}  # queued, not yet started
        self._running: JobHandle | None = None  # the clip the worker is on now
        self._inflight: dict[JobKey, JobHandle] = {}  # pending + running (dedup/lookup)
        self._wake = asyncio.Event()  # set when new pending work arrives
        self._idle = asyncio.Event()  # set when nothing is pending or running
        self._idle.set()
        self._unfinished = 0
        self._burst_total = 0  # clips queued since the queue last went idle
        self._burst_done = 0  # of those, how many have finished (for the deck bar)
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
        if not self._inflight:  # a fresh burst starts: reset the deck-progress tally
            self._burst_total = 0
            self._burst_done = 0
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
            self._pending[key] = handle
            self._unfinished += 1
            self._burst_total += 1
            self._idle.clear()
            handles.append(handle)
        if handles:
            self._wake.set()  # nudge the worker to (re)evaluate the backlog
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
        """Block until nothing is pending or running (tests/shutdown)."""
        await self._idle.wait()

    async def drain_after(self, handles: Iterable[JobHandle]) -> None:
        """Block until each given handle finishes."""
        for handle in handles:
            await handle.done.wait()

    def cancel_running_unless(self, targets: set[Target]) -> bool:
        """Abort the in-flight clip unless it's already one of *targets*.

        Used when play needs an ungenerated current slide: a heavy clip for some
        other slide is told to stop so the worker is freed to pick the current one
        (which the distance priority then ranks first). Returns whether anything
        was cancelled. The cancelled clip is re-queued, not lost.
        """
        running = self._running
        if running is None or running.refs & targets:
            return False
        running.cancel.set()
        return True

    def running_handle(self) -> JobHandle | None:
        """The clip currently generating, if any (drives the live elapsed timer)."""
        return self._running

    def progress(self) -> tuple[int, int]:
        """``(done, total)`` clips for the current generation burst (``(0, 0)`` idle).

        Counts since the queue last went idle, so the deck bar fills 0→100% over a
        sweep and resets when the next burst starts. A re-queued (preempted) clip
        is not double-counted — only genuine completions advance ``done``.
        """
        return (self._burst_done, self._burst_total)

    # ---- worker ---------------------------------------------------------
    async def _worker(self) -> None:
        while True:
            handle = await self._take_next()
            self._running = handle
            handle.status = "running"
            handle.started_at = time.monotonic()
            self._emit()
            try:
                with cancel_scope(handle.cancel):
                    await asyncio.to_thread(self._synth, set(handle.refs), handle.force)
            except GenerationCancelled:
                # Preempted (e.g. by play): re-queue this clip and free the worker
                # for the higher-priority one. Keep the handle in _inflight and
                # leave it unfinished so its awaiters still resolve on the retry.
                self._running = None
                handle.cancel.clear()
                handle.status = "queued"
                self._pending[handle.key] = handle
                self._wake.set()
                self._emit()
                continue
            except Exception as exc:  # keep the worker alive; surface on the handle
                handle.status = "error"
                handle.error = exc
                logger.exception("background generation failed for %s", handle.key)
                self._safe_on_error(handle)
            else:
                handle.status = "done"
            self._running = None
            self._inflight.pop(handle.key, None)
            handle.done.set()
            self._burst_done += 1
            self._finish_one()
            self._emit()

    async def _take_next(self) -> JobHandle:
        """Wait for pending work, then pop the best-next clip for where we are now."""
        while not self._pending:
            self._wake.clear()
            await self._wake.wait()
        current = self._current_index()
        order = self._slide_order()
        key = min(self._pending, key=lambda k: self._priority(self._pending[k], current, order))
        return self._pending.pop(key)

    def _slide_order(self) -> dict[str, int]:
        """slide-id → position in deck order (for distance-to-current ranking)."""
        deck, _, _ = self._deck_provider()
        return {sid: i for i, sid in enumerate(deck.pages)}

    def _priority(
        self, handle: JobHandle, current: int | None, order: dict[str, int]
    ) -> tuple[int, int]:
        """Sort key for picking the next clip — smaller runs first.

        With no current slide (tests / headless) it's plain deck order. Otherwise
        the current slide ranks first, then slides *ahead* by nearness, then slides
        *behind* (all ahead before any behind); ties break by speech index so a
        slide's clips render front-to-back.
        """
        n = len(order)
        slide_idx, speech_idx = min(
            ((order.get(sid, n), sp) for (sid, sp) in handle.refs), default=(n, 0)
        )
        if current is None:
            return (slide_idx, speech_idx)
        if slide_idx >= current:
            distance = slide_idx - current  # 0 = current slide, then ahead
        else:
            distance = n + (current - slide_idx)  # behind: always after every ahead slide
        return (distance, speech_idx)

    def _finish_one(self) -> None:
        self._unfinished -= 1
        if self._unfinished <= 0:
            self._unfinished = 0
            self._idle.set()

    def _emit(self) -> None:
        try:
            self._on_change()
        except Exception:  # the client may have disconnected mid-job
            logger.debug("job on_change failed (client gone?)", exc_info=True)

    def _safe_on_error(self, handle: JobHandle) -> None:
        try:
            self._on_error(handle)
        except Exception:  # the client may have disconnected mid-job
            logger.debug("job on_error failed (client gone?)", exc_info=True)
