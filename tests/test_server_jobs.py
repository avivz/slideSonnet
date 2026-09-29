"""Backend-owned jobs: lifecycle, cancellation, dedupe, events."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from slidesonnet.cancellation import current_cancel
from slidesonnet.server import jobs as jobs_mod
from slidesonnet.server.events import EventBus
from slidesonnet.server.jobs import JobCancelled, JobContext, JobManager


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def jobs(bus: EventBus) -> Iterator[JobManager]:
    manager = JobManager(bus, max_workers=2)
    yield manager
    manager.shutdown()


def _finish(jobs: JobManager, job_id: str, timeout: float = 5.0) -> str:
    job = jobs.wait_sync(job_id, timeout=timeout)
    return job.status


def test_job_runs_off_thread_reports_progress_and_result(jobs: JobManager, bus: EventBus) -> None:
    seen_thread: list[str] = []

    def work(ctx: JobContext) -> dict[str, int]:
        seen_thread.append(threading.current_thread().name)
        ctx.progress("assemble", 1, 2)
        ctx.progress("assemble", 2, 2)
        return {"answer": 42}

    job = jobs.submit("preview", "tok", {"scope": "deck"}, work)
    assert _finish(jobs, job.id) == "succeeded"
    done = jobs.get(job.id)
    assert done is not None
    assert done.result == {"answer": 42}
    assert (done.progress.phase, done.progress.done, done.progress.total) == ("assemble", 2, 2)
    assert seen_thread and seen_thread[0] != threading.current_thread().name
    kinds = [e.type for e in bus.history()]
    assert kinds[0] == "job.created" and kinds[-1] == "job.finished"
    seqs = [e.seq for e in bus.history()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_failure_is_recorded_with_a_readable_message(jobs: JobManager) -> None:
    def work(ctx: JobContext) -> None:
        raise RuntimeError("ffmpeg exploded")

    job = jobs.submit("export", "tok", {}, work)
    assert _finish(jobs, job.id) == "failed"
    done = jobs.get(job.id)
    assert done is not None and done.error is not None
    assert "ffmpeg exploded" in done.error.message


def test_cancel_is_cooperative_and_distinguishes_requested_from_stopped(
    jobs: JobManager,
) -> None:
    started = threading.Event()
    release = threading.Event()

    def work(ctx: JobContext) -> None:
        assert current_cancel() is ctx.cancel_event  # engines/tools see the token
        started.set()
        release.wait(5)
        ctx.check_cancelled()

    job = jobs.submit("generate", "tok", {}, work)
    assert started.wait(5)
    assert jobs.cancel(job.id).status == "cancelling"  # asked, not yet stopped
    release.set()
    assert _finish(jobs, job.id) == "cancelled"


def test_cancelling_a_queued_job_never_runs_it(bus: EventBus) -> None:
    manager = JobManager(bus, max_workers=1)
    gate = threading.Event()
    ran: list[str] = []
    try:
        first = manager.submit("export", "tok", {}, lambda ctx: gate.wait(5))
        second = manager.submit("preview", "tok", {}, lambda ctx: ran.append("second"))
        manager.cancel(second.id)
        gate.set()
        assert manager.wait_sync(first.id, timeout=5).status == "succeeded"
        assert manager.wait_sync(second.id, timeout=5).status == "cancelled"
        assert ran == []
    finally:
        manager.shutdown()


def test_same_dedupe_key_attaches_to_the_active_job(jobs: JobManager) -> None:
    gate = threading.Event()
    a = jobs.submit("preview", "tok", {}, lambda ctx: gate.wait(5), dedupe_key="deck@r1")
    b = jobs.submit("preview", "tok", {}, lambda ctx: None, dedupe_key="deck@r1")
    assert a.id == b.id
    gate.set()
    assert _finish(jobs, a.id) == "succeeded"
    c = jobs.submit("preview", "tok", {}, lambda ctx: None, dedupe_key="deck@r1")
    assert c.id != a.id  # a finished job doesn't swallow a new request


def test_progress_events_are_coalesced(jobs: JobManager, bus: EventBus) -> None:
    def work(ctx: JobContext) -> None:
        for i in range(500):
            ctx.progress("generate", i, 500)

    job = jobs.submit("generate", "tok", {}, work)
    _finish(jobs, job.id)
    progress_events = [e for e in bus.history() if e.type == "job.progress"]
    assert len(progress_events) < 20


def test_shutdown_cancels_running_work_and_returns(bus: EventBus) -> None:
    manager = JobManager(bus, max_workers=1)
    started = threading.Event()

    def work(ctx: JobContext) -> None:
        started.set()
        while True:
            ctx.check_cancelled()
            time.sleep(0.01)

    job = manager.submit("generate", "tok", {}, work)
    assert started.wait(5)
    t0 = time.monotonic()
    manager.shutdown()
    assert time.monotonic() - t0 < 5
    got = manager.get(job.id)
    assert got is not None and got.status == "cancelled"


def _raise(exc: BaseException) -> None:
    raise exc


_OUTCOMES: dict[str, Callable[[JobContext], object]] = {
    "succeeds": lambda ctx: "ok",
    "fails": lambda ctx: _raise(RuntimeError("boom")),
    "cancelled": lambda ctx: _raise(JobCancelled("stop")),
}


@pytest.mark.parametrize("work", _OUTCOMES.values(), ids=_OUTCOMES.keys())
def test_status_changes_only_under_the_lock(
    bus: EventBus, monkeypatch: pytest.MonkeyPatch, work: Callable[[JobContext], object]
) -> None:
    """A cancel landing as the work ends must not overwrite the terminal state
    (a job stuck in ``cancelling`` blocks every later export)."""
    manager = JobManager(bus, max_workers=1)
    unlocked: list[str] = []

    class Watched(jobs_mod.Job):
        def __setattr__(self, name: str, value: object) -> None:
            if name == "status" and not manager._lock.locked():
                unlocked.append(str(value))
            super().__setattr__(name, value)

    monkeypatch.setattr(jobs_mod, "Job", Watched)
    try:
        job = manager.submit("export", "tok", {}, work)
        manager.wait_sync(job.id, timeout=5)
        manager.cancel(job.id)
    finally:
        manager.shutdown()
    assert unlocked == [] and not job.active


def test_dedupe_skips_a_job_being_cancelled(jobs: JobManager) -> None:
    started, release = threading.Event(), threading.Event()

    def work(ctx: JobContext) -> None:
        started.set()
        release.wait(5)

    first = jobs.submit("export", "tok", {}, work, dedupe_key="export:tok")
    assert started.wait(5)
    assert jobs.cancel(first.id).status == "cancelling"
    again = jobs.submit("export", "tok", {}, lambda ctx: None, dedupe_key="export:tok")
    release.set()
    assert again.id != first.id


def test_shutdown_settles_jobs_that_never_started(bus: EventBus) -> None:
    manager = JobManager(bus, max_workers=1)
    started, release = threading.Event(), threading.Event()

    def stubborn(ctx: JobContext) -> None:  # ignores cancellation
        started.set()
        release.wait(5)

    manager.submit("export", "tok", {}, stubborn)
    queued = manager.submit("preview", "tok", {}, lambda ctx: None)
    assert started.wait(5)
    manager.shutdown(timeout=0)
    release.set()
    assert queued.done_event.is_set() and queued.status == "cancelled"


def test_concurrent_requests_share_one_job_manager(
    bus: EventBus, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from slidesonnet.server import context as context_mod
    from slidesonnet.server.library import DeckRegistry

    both_inside = threading.Barrier(2, timeout=0.5)
    made: list[JobManager] = []

    def slow_manager(bus: EventBus) -> JobManager:
        with contextlib.suppress(threading.BrokenBarrierError):
            both_inside.wait()  # passes only if two creations overlap
        made.append(JobManager(bus, max_workers=1))
        return made[-1]

    monkeypatch.setattr(context_mod, "JobManager", slow_manager)
    ctx = context_mod.ServerContext(registry=DeckRegistry(tmp_path), bus=bus)
    got: list[JobManager] = []
    threads = [threading.Thread(target=lambda: got.append(ctx.job_manager())) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for m in made:
        m.shutdown()
    assert len(made) == 1 and got[0] is got[1]


async def test_wait_resolves_on_the_event_loop(jobs: JobManager) -> None:
    job = jobs.submit("preview", "tok", {}, lambda ctx: "ok")
    done = await jobs.wait(job.id)
    assert done.status == "succeeded" and done.result == "ok"


def test_event_bus_replays_after_a_sequence_and_flags_gaps() -> None:
    bus = EventBus(capacity=3)
    for i in range(5):
        bus.publish("deck.changed", deck="d", data={"i": i})
    assert [e.seq for e in bus.since(3)] == [4, 5]
    assert bus.since(0) is None  # seq 1 fell out of the buffer: the client must resync
