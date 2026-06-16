"""Unit tests for the background generation job queue (gui/jobs.py).

Drives the asyncio queue with a FakeEngine and a real content-addressed cache,
so the dedup/coalesce logic is exercised against the genuine hashing scheme —
no NiceGUI, no browser, no real TTS.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from slidesonnet.audio import synth as synth_mod
from slidesonnet.config import Config
from slidesonnet.gui.jobs import JobQueue
from slidesonnet.narration.model import Deck, PageNarration, Segment
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

    def synth(targets: set[tuple[str, int]], force: bool) -> None:
        synth_mod.synthesize(
            deck, config, audio_dir=tmp_path, only_segments=set(targets), force=force
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
        await queue.drain_after(queue.enqueue({("a", 0)}))  # first generation
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


def test_await_targets_blocks_until_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch)
        queue.start()
        queue.enqueue({("a", 0)})
        await queue.await_targets({("a", 0)})  # must not return before the job finishes
        assert engine.calls == 1
        assert queue.handle_for("a", 0) is None  # cleared once done
        # Awaiting a target with no in-flight job returns immediately.
        await queue.await_targets({("b", 0)})
        queue.stop()

    asyncio.run(body())


def test_failed_job_leaves_no_stuck_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body() -> None:
        queue, engine, _ = _make_queue(tmp_path, monkeypatch, engine=FailingEngine())
        queue.start()
        handles = queue.enqueue({("a", 0)})
        await queue.drain()
        queue.stop()
        assert handles[0].status == "error"
        assert handles[0].error is not None
        assert handles[0].done.is_set()
        assert queue.handle_for("a", 0) is None  # not stuck in-flight

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
