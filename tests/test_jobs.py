"""Unit tests for the background generation job queue (gui/jobs.py).

Drives the asyncio queue with a FakeEngine and a real content-addressed cache,
so the dedup/coalesce logic is exercised against the genuine hashing scheme —
no NiceGUI, no browser, no real TTS.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest

from slidesonnet.audio import synth as synth_mod
from slidesonnet.config import Config
from slidesonnet.exceptions import GenerationCancelled
from slidesonnet.narration.model import Deck, PageNarration, Segment
from slidesonnet.server.queue import JobHandle, JobQueue
from slidesonnet.tts.base import TTSEngine


class FakeEngine(TTSEngine):
    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        self.calls += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFFfake")
        return 1.25

    def name(self) -> str:
        return "kokoro"

    def cache_key(self) -> str:
        return "fake"


class FailingEngine(FakeEngine):
    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        self.calls += 1
        raise RuntimeError("synthesis blew up")


def _deck(*, same_text: bool = False) -> Deck:
    """Two slides, one speech segment each. *same_text* makes them byte-identical."""
    a_text = "Shared words." if same_text else "First slide words."
    b_text = "Shared words." if same_text else "Second slide words."
    return Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b"],
        narration={
            "a": PageNarration("a", [Segment.speech(a_text)]),
            "b": PageNarration("b", [Segment.speech(b_text)]),
        },
    )


def _make_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    engine: FakeEngine | None = None,
    paid: bool = False,
    same_text: bool = False,
) -> tuple[JobQueue, FakeEngine, Deck]:
    engine = engine or FakeEngine()
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: engine)
    deck = _deck(same_text=same_text)
    config = Config()

    def synth(targets: set[tuple[str, int]], force: bool, approved: frozenset[str] | None) -> None:
        synth_mod.synthesize(
            deck,
            config,
            audio_dir=tmp_path,
            only_segments=set(targets),
            force=force,
            approved=approved,
        )

    queue = JobQueue(
        deck_provider=lambda: (deck, config, tmp_path),
        synth=synth,
        is_paid=lambda: paid,
    )
    return queue, engine, deck


def test_same_target_enqueued_twice_runs_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch)
        queue.start()
        h1 = queue.enqueue({("a", 0)})
        h2 = queue.enqueue({("a", 0)})  # coalesces before the worker runs
        assert h1 == h2  # same handle returned
        await queue.drain()
        queue.stop()
        assert engine.calls == 1

    asyncio.run(body())


def test_byte_identical_segments_coalesce_to_one_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch, same_text=True)
        queue.start()
        handles = queue.enqueue({("a", 0), ("b", 0)})
        assert len({h.key for h in handles}) == 1  # one content-addressed job
        await queue.drain()
        queue.stop()
        assert engine.calls == 1  # one synthesis satisfies both refs

    asyncio.run(body())


@pytest.mark.parametrize("paid", [True, False])
def test_a_paid_clip_makes_only_the_text_that_was_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, paid: bool
) -> None:
    """The line changes while its clip waits: a paid queue refuses; a free one makes it."""
    from slidesonnet.exceptions import UnapprovedClips

    engine = FakeEngine()

    async def body() -> JobHandle:
        queue, _, deck = _make_queue(tmp_path, monkeypatch, engine=engine, paid=paid)
        queue.start()
        if paid:  # a key nobody approved is never queued
            assert queue.enqueue({("b", 0)}, allow_paid=True, approved=set()) == []
        (handle,) = queue.enqueue({("a", 0)}, allow_paid=True)
        deck.narration["a"] = PageNarration("a", [Segment.speech("An unapproved insert.")])
        await queue.drain()
        queue.stop()
        return handle

    handle = asyncio.run(body())
    assert engine.calls == (0 if paid else 1)
    if paid:
        assert isinstance(handle.error, UnapprovedClips)
        assert "approve again to generate 1 new clip" in str(handle.error)


def test_distinct_segments_make_distinct_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch)
        queue.start()
        handles = queue.enqueue({("a", 0), ("b", 0)})
        assert len({h.key for h in handles}) == 2
        await queue.drain()
        queue.stop()
        assert engine.calls == 2

    asyncio.run(body())


def test_cached_clip_skipped_unless_forced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch)
        queue.start()
        queue.enqueue({("a", 0)})  # first generation
        await queue.drain()
        assert engine.calls == 1

        again = queue.enqueue({("a", 0)})  # already cached, no force
        assert again == []
        await queue.drain()
        assert engine.calls == 1

        forced = queue.enqueue({("a", 0)}, force=True)
        assert len(forced) == 1
        await queue.drain()
        queue.stop()
        assert engine.calls == 2

    asyncio.run(body())


def test_failed_job_leaves_no_stuck_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body() -> None:
        queue, _engine, _ = _make_queue(tmp_path, monkeypatch, engine=FailingEngine())
        queue.start()
        handles = queue.enqueue({("a", 0)})
        await queue.drain()
        queue.stop()
        assert handles[0].status == "error"
        assert handles[0].error is not None
        assert handles[0].done.is_set()
        assert queue.inflight() == []  # not stuck in-flight

    asyncio.run(body())


def test_worker_survives_a_deck_that_cannot_be_read_while_picking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sidecar or PDF caught mid-rewrite when the worker ranks the backlog
    mustn't kill it: the clip still runs, and later clips too."""

    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch)
        good = queue._deck_provider
        calls = {"deck": 0, "index": 0}

        def flaky_deck() -> tuple[Deck, Config, Path]:
            calls["deck"] += 1
            if calls["deck"] == 2:  # enqueue reads it once; the pick is the second read
                raise ValueError("sidecar half-written")
            return good()

        def flaky_index() -> int | None:
            calls["index"] += 1
            if calls["index"] == 1:
                raise OSError("PDF being rewritten")
            return None

        queue._deck_provider = flaky_deck
        queue._current_index = flaky_index
        queue.start()
        first = queue.enqueue({("a", 0)})
        await asyncio.wait_for(queue.drain(), 5)
        second = queue.enqueue({("b", 0)})
        await asyncio.wait_for(queue.drain(), 5)
        queue.stop()
        assert [h.status for h in first + second] == ["done", "done"]
        assert engine.calls == 2

    asyncio.run(body())


def test_enqueue_restarts_a_dead_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch)
        queue.start()
        task = queue._worker_task
        assert task is not None
        task.cancel()  # the worker died of something unforeseen
        with contextlib.suppress(asyncio.CancelledError):
            await task
        handles = queue.enqueue({("a", 0)})
        await asyncio.wait_for(queue.drain(), 5)
        queue.stop()
        assert handles[0].status == "done" and engine.calls == 1

    asyncio.run(body())


def test_paid_engine_refused_without_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch, paid=True)
        queue.start()
        refused = queue.enqueue({("a", 0)})  # auto path: not allowed to bill
        assert refused == []
        allowed = queue.enqueue({("a", 0)}, allow_paid=True)  # confirmed path
        assert len(allowed) == 1
        await queue.drain()
        queue.stop()
        assert engine.calls == 1

    asyncio.run(body())


# ---- distance-priority scheduling -------------------------------------------


def _deck_n(n: int) -> Deck:
    """A deck of *n* slides s0..s(n-1), one distinct speech segment each."""
    pages = [f"s{i}" for i in range(n)]
    return Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=pages,
        narration={sid: PageNarration(sid, [Segment.speech(f"Words for {sid}.")]) for sid in pages},
    )


def _priority_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, n: int, cur: list[int | None]
) -> tuple[JobQueue, list[tuple[str, int]]]:
    """A queue over an n-slide deck whose current index is read from *cur[0]*.

    Returns the queue and an ``order`` list the synth appends picked targets to,
    so tests can assert the order the worker chose.
    """
    engine = FakeEngine()
    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: engine)
    deck = _deck_n(n)
    config = Config()
    order: list[tuple[str, int]] = []

    def synth(targets: set[tuple[str, int]], force: bool, _approved: object) -> None:
        order.extend(sorted(targets))
        synth_mod.synthesize(
            deck, config, audio_dir=tmp_path, only_segments=set(targets), force=force
        )

    queue = JobQueue(
        deck_provider=lambda: (deck, config, tmp_path),
        synth=synth,
        is_paid=lambda: False,
        current_index=lambda: cur[0],
    )
    return queue, order


def test_worker_runs_current_then_ahead_then_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """From slide 2 of 5: current first, then ahead (nearest), then behind (nearest)."""

    async def body() -> None:
        cur: list[int | None] = [2]
        queue, order = _priority_queue(tmp_path, monkeypatch, n=5, cur=cur)
        queue.start()
        queue.enqueue({(f"s{i}", 0) for i in range(5)})  # all five at once
        await queue.drain()
        queue.stop()
        assert [sid for sid, _ in order] == ["s2", "s3", "s4", "s1", "s0"]

    asyncio.run(body())


def test_pick_reprioritizes_when_current_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The next clip is chosen against where you are *now* — moving re-ranks it."""

    async def body() -> None:
        cur: list[int | None] = [0]
        queue, _ = _priority_queue(tmp_path, monkeypatch, n=5, cur=cur)
        queue.enqueue({(f"s{i}", 0) for i in range(5)})  # fill the backlog (worker idle)

        first = await queue._take_next()
        assert {sid for sid, _ in first.refs} == {"s0"}  # current slide

        cur[0] = 4  # navigate to the end before the next pick
        second = await queue._take_next()
        assert {sid for sid, _ in second.refs} == {"s4"}  # re-ranked to the new current

    asyncio.run(body())


# ---- cooperative cancellation -----------------------------------------------


def test_cancel_running_unless_skips_the_wanted_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel the in-flight clip only when it isn't already one we need."""
    queue, _, _ = _make_queue(tmp_path, monkeypatch)
    queue._running = JobHandle(key="k", refs={("b", 0)}, done=asyncio.Event())

    assert queue.cancel_running_unless({("b", 0)}) is False  # already generating it
    assert not queue._running.cancel.is_set()

    assert queue.cancel_running_unless({("a", 0)}) is True  # different clip → preempt
    assert queue._running.cancel.is_set()


def test_cancelled_job_is_requeued_and_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GenerationCancelled clip isn't a failure — it re-queues and completes."""

    async def body() -> None:
        engine = FakeEngine()
        monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: engine)
        deck = _deck()
        config = Config()
        calls = {"n": 0}

        def synth(targets: set[tuple[str, int]], force: bool, _approved: object) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise GenerationCancelled("preempted on the first attempt")
            synth_mod.synthesize(
                deck, config, audio_dir=tmp_path, only_segments=set(targets), force=force
            )

        queue = JobQueue(
            deck_provider=lambda: (deck, config, tmp_path), synth=synth, is_paid=lambda: False
        )
        queue.start()
        handle = queue.enqueue({("a", 0)})[0]
        await queue.drain()
        queue.stop()
        assert calls["n"] == 2  # cancelled once, then retried to completion
        assert handle.status == "done"
        assert handle.done.is_set()

    asyncio.run(body())


def test_failed_job_invokes_the_error_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A synthesis failure is surfaced via on_error (no longer swallowed silently)."""

    async def body() -> None:
        engine = FailingEngine()
        monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: engine)
        deck = _deck()
        config = Config()
        errored: list[str] = []

        def synth(targets: set[tuple[str, int]], force: bool, _approved: object) -> None:
            synth_mod.synthesize(
                deck, config, audio_dir=tmp_path, only_segments=set(targets), force=force
            )

        queue = JobQueue(
            deck_provider=lambda: (deck, config, tmp_path),
            synth=synth,
            is_paid=lambda: False,
            on_error=lambda h: errored.append(h.key),
        )
        queue.start()
        handle = queue.enqueue({("a", 0)})[0]
        await queue.drain()
        queue.stop()
        assert handle.status == "error"
        assert errored == [handle.key]  # the failure was reported, not swallowed

    asyncio.run(body())


def test_progress_counts_the_burst_and_resets_on_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``progress()`` drives the deck bar: 0→total over a burst, reset on the next."""

    async def body() -> None:
        queue, _, _ = _make_queue(tmp_path, monkeypatch)
        assert queue.progress() == (0, 0)  # idle
        queue.enqueue({("a", 0), ("b", 0)})
        assert queue.progress() == (0, 2)  # two queued, none done yet
        queue.start()
        await queue.drain()
        assert queue.progress() == (2, 2)  # complete; holds at 100% until the next burst
        queue.enqueue({("a", 0)}, force=True)  # fresh burst from idle → tally resets
        assert queue.progress() == (0, 1)
        await queue.drain()
        queue.stop()

    asyncio.run(body())


def test_cancel_all_drops_queued_clips_and_releases_awaiters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The progress-bar ✕: every queued clip is dropped, awaiters freed, no synth."""

    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch)
        handles = queue.enqueue({("a", 0), ("b", 0)})  # queued; worker not started
        assert queue.progress() == (0, 2)

        cleared = queue.cancel_all()
        assert cleared == 2
        assert queue.progress() == (0, 0)  # the bar clears
        for h in handles:
            assert h.done.is_set()  # anyone awaiting these is released
        await queue.drain()  # nothing pending or running
        assert engine.calls == 0  # dropped before any synthesis

    asyncio.run(body())


def test_cancel_all_aborts_the_running_clip_without_requeue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clip aborted by cancel-all is dropped, not re-queued like a play-preempt."""

    async def body() -> None:
        from slidesonnet.cancellation import current_cancel

        engine = FakeEngine()
        monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: engine)
        deck = _deck()
        config = Config()
        calls = {"n": 0}

        def synth(targets: set[tuple[str, int]], force: bool, _approved: object) -> None:
            calls["n"] += 1
            evt = current_cancel()  # cooperative cancel, like the qwen3 engine
            if evt is not None:
                evt.wait(2)  # block until cancel-all fires
                if evt.is_set():
                    raise GenerationCancelled("aborted by cancel-all")
            synth_mod.synthesize(
                deck, config, audio_dir=tmp_path, only_segments=set(targets), force=force
            )

        queue = JobQueue(
            deck_provider=lambda: (deck, config, tmp_path), synth=synth, is_paid=lambda: False
        )
        queue.start()
        handle = queue.enqueue({("a", 0)})[0]
        for _ in range(300):  # wait until the worker is running this clip
            if queue.running_handle() is not None:
                break
            await asyncio.sleep(0.01)
        assert queue.cancel_all() >= 1
        await queue.drain()
        queue.stop()
        assert calls["n"] == 1  # aborted once, NOT retried/re-queued
        assert handle.done.is_set()

    asyncio.run(body())


def test_cancel_owned_drops_only_clips_nobody_else_wants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leaving a deck drops *that tab's* queued clips; another tab's requests stay."""

    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch)
        mine = queue.enqueue({("a", 0)}, owner="tab-1")
        shared = queue.enqueue({("b", 0)}, owner="tab-1")
        queue.enqueue({("b", 0)}, owner="tab-2")  # tab 2 wants b as well
        assert queue.cancel_owned("tab-1") == 1  # a dropped; b is still wanted
        assert mine[0].done.is_set() and not shared[0].done.is_set()
        assert [h.refs for h in queue.inflight()] == [{("b", 0)}]
        queue.start()
        await queue.drain()
        queue.stop()
        assert engine.calls == 1  # only b was synthesized

    asyncio.run(body())
