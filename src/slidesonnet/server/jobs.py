"""Backend-owned jobs: generate, preview, export, render-pages.

A job belongs to the server, not to a browser connection: a tab closing or an
SSE stream dropping never cancels or duplicates work, and an export started in
one tab is visible (and cancellable) from any other while the server runs.

Each job records an immutable snapshot of its inputs (deck token, revisions,
engine, scope), its progress, and its outcome. Work runs on a bounded thread
pool; cancellation is cooperative — the job's cancel token is bound as the
active :mod:`slidesonnet.cancellation` scope, so engines that can abort
mid-clip do, external tools are killed (:mod:`slidesonnet.proc`), and the work
function itself checks :meth:`JobContext.check_cancelled` between steps.
``cancelling`` (asked) is reported separately from ``cancelled`` (stopped).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

from slidesonnet.cancellation import cancel_scope
from slidesonnet.exceptions import GenerationCancelled
from slidesonnet.server.events import EventBus

logger = logging.getLogger(__name__)

JobKind = Literal["generate", "preview", "export", "render_pages"]
JobStatus = Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]
ACTIVE: frozenset[str] = frozenset({"queued", "running", "cancelling"})

#: Progress events per job are published at most this often (the final state always is).
_PROGRESS_INTERVAL_S = 0.25
#: Finished jobs kept for status queries before the oldest are forgotten.
_RETAIN_FINISHED = 200


class JobCancelled(GenerationCancelled):
    """Raised inside a job's work function once its cancellation was requested."""


@dataclass
class Progress:
    phase: str = ""
    done: int = 0
    total: int = 0
    label: str = ""


@dataclass
class JobError:
    code: str
    message: str


@dataclass
class Job:
    id: str
    kind: JobKind
    deck: str
    inputs: dict[str, Any]
    status: JobStatus = "queued"
    progress: Progress = field(default_factory=Progress)
    result: Any = None
    error: JobError | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    dedupe_key: str | None = None
    #: The exception a failed job raised (in-process callers re-raise it; never serialized).
    exception: BaseException | None = field(default=None, repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    done_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def active(self) -> bool:
        return self.status in ACTIVE


class JobContext:
    """What a work function gets: its job, progress reporting, and cancel checks."""

    def __init__(self, job: Job, manager: JobManager) -> None:
        self.job = job
        self._manager = manager

    @property
    def cancel_event(self) -> threading.Event:
        return self.job.cancel_event

    def check_cancelled(self) -> None:
        if self.job.cancel_event.is_set():
            raise JobCancelled(f"job {self.job.id} was cancelled")

    def progress(self, phase: str, done: int, total: int, label: str = "") -> None:
        """Record progress (and check for cancellation — a natural yield point)."""
        self.job.progress = Progress(phase=phase, done=done, total=total, label=label)
        self._manager._progress_changed(self.job)
        self.check_cancelled()


Work = Callable[[JobContext], Any]


class JobManager:
    def __init__(self, bus: EventBus, *, max_workers: int = 4) -> None:
        self.bus = bus
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ss-job")
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._last_progress: dict[str, float] = {}
        self._futures: dict[str, Future[None]] = {}
        self._closed = False

    # ---- creating ---------------------------------------------------------
    def submit(
        self,
        kind: JobKind,
        deck: str,
        inputs: dict[str, Any],
        work: Work,
        *,
        dedupe_key: str | None = None,
    ) -> Job:
        """Start *work* as a job; an active job with the same *dedupe_key* is returned instead."""
        with self._lock:
            if self._closed:
                raise RuntimeError("the job manager is shut down")
            if dedupe_key is not None:
                for existing in self._jobs.values():
                    if existing.dedupe_key == dedupe_key and existing.active:
                        return existing
            job = Job(
                id=uuid.uuid4().hex[:12],
                kind=kind,
                deck=deck,
                inputs=dict(inputs),
                dedupe_key=dedupe_key,
            )
            self._jobs[job.id] = job
            self._trim()
        self._publish(job, "job.created")
        future = self._pool.submit(self._run, job, work)
        with self._lock:
            self._futures[job.id] = future
        return job

    # ---- querying ---------------------------------------------------------
    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, *, deck: str | None = None, active_only: bool = False) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [
            j for j in jobs if (deck is None or j.deck == deck) and (not active_only or j.active)
        ]

    def wait_sync(self, job_id: str, *, timeout: float | None = None) -> Job:
        """Block until the job finishes (tests, CLI). Raises KeyError for unknown ids."""
        job = self._require(job_id)
        job.done_event.wait(timeout)
        return job

    async def wait(self, job_id: str) -> Job:
        """Await the job's end without blocking the event loop."""
        job = self._require(job_id)
        if not job.done_event.is_set():
            await asyncio.to_thread(job.done_event.wait)
        return job

    # ---- cancelling -------------------------------------------------------
    def cancel(self, job_id: str) -> Job:
        """Ask a job to stop. Queued jobs never start; running ones stop cooperatively."""
        job = self._require(job_id)
        with self._lock:
            if not job.active:
                return job
            job.cancel_event.set()
            if job.status == "running":
                job.status = "cancelling"
        self._publish(job, "job.updated")
        return job

    def cancel_deck(self, deck: str, *, kinds: set[str] | None = None) -> int:
        n = 0
        for job in self.list(deck=deck, active_only=True):
            if kinds is None or job.kind in kinds:
                self.cancel(job.id)
                n += 1
        return n

    def shutdown(self, *, timeout: float = 10.0) -> None:
        """Cancel everything and wait for workers (bounded), so nothing outlives the server."""
        with self._lock:
            self._closed = True
            active = [j for j in self._jobs.values() if j.active]
        for job in active:
            self.cancel(job.id)
        deadline = time.monotonic() + timeout
        for job in active:
            job.done_event.wait(max(0.0, deadline - time.monotonic()))
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---- internals --------------------------------------------------------
    def _require(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _run(self, job: Job, work: Work) -> None:
        with self._lock:
            if job.cancel_event.is_set():
                job.status = "cancelled"
                job.finished_at = time.time()
                cancelled_before_start = True
            else:
                job.status = "running"
                job.started_at = time.time()
                cancelled_before_start = False
        if cancelled_before_start:
            self._finish(job)
            return
        self._publish(job, "job.updated")
        ctx = JobContext(job, self)
        try:
            with cancel_scope(job.cancel_event):
                result = work(ctx)
        except GenerationCancelled:
            job.status = "cancelled"
        except Exception as exc:
            logger.exception("job %s (%s) failed", job.id, job.kind)
            job.status = "failed"
            job.exception = exc
            job.error = JobError(code=type(exc).__name__, message=str(exc) or type(exc).__name__)
        else:  # work that ran to completion succeeded, even if a cancel arrived late
            job.result = result
            job.status = "succeeded"
        job.finished_at = time.time()
        self._finish(job)

    def _finish(self, job: Job) -> None:
        with self._lock:
            self._futures.pop(job.id, None)
            self._last_progress.pop(job.id, None)
        job.done_event.set()
        self._publish(job, "job.finished")

    def _progress_changed(self, job: Job) -> None:
        now = time.monotonic()
        with self._lock:
            last = self._last_progress.get(job.id, 0.0)
            if now - last < _PROGRESS_INTERVAL_S:
                return
            self._last_progress[job.id] = now
        self._publish(job, "job.progress")

    def _publish(self, job: Job, type: str) -> None:
        self.bus.publish(
            type,
            deck=job.deck,
            data={
                "job_id": job.id,
                "kind": job.kind,
                "status": job.status,
                "progress": {
                    "phase": job.progress.phase,
                    "done": job.progress.done,
                    "total": job.progress.total,
                },
            },
        )

    def _trim(self) -> None:
        finished = [jid for jid, j in self._jobs.items() if not j.active]
        for jid in finished[: max(0, len(finished) - _RETAIN_FINISHED)]:
            self._jobs.pop(jid, None)
