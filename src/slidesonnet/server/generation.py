"""Per-deck clip generation, owned by the server and shared by every editor tab.

Each (deck, engine) pair gets one :class:`~slidesonnet.server.queue.JobQueue`: one
worker, content-addressed dedup (two requests for the same clip — a
double-click, two tabs — synthesize once), and distance priority (the clip
nearest the slide someone is looking at goes next; a tab reports where it is
with :meth:`DeckGeneration.focus`). The queue lives as long as the server, not
a browser connection, so a reload or a dropped event stream loses nothing; a
tab leaving the deck drops only the clips it alone asked for.

Every change is announced on the event bus as ``generation.changed`` (coalesced),
so tabs refetch :meth:`DeckGeneration.status` instead of polling.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from slidesonnet import api
from slidesonnet.cache import resolve_audio_dir
from slidesonnet.config import Config
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.models import Backend
from slidesonnet.narration.model import Deck
from slidesonnet.server.decks import deck_service
from slidesonnet.server.engines import engine_lock
from slidesonnet.server.events import EventBus
from slidesonnet.server.library import DeckEntry
from slidesonnet.server.queue import JobHandle, JobQueue, Target
from slidesonnet.timing import word_count
from slidesonnet.tts import BACKENDS

logger = logging.getLogger(__name__)

#: ``generation.changed`` events per deck are sent at most this often.
_EMIT_INTERVAL_S = 0.2


def with_engine(config: Config, engine: Backend) -> Config:
    from dataclasses import replace

    if engine == config.tts.backend:
        return config
    return replace(config, tts=replace(config.tts, backend=engine))


@dataclass
class DeckGeneration:
    """The generation queue for one deck under one engine."""

    entry: DeckEntry
    engine: Backend
    bus: EventBus
    queue: JobQueue = field(init=False)
    focus_slide: str | None = None
    _last_emit: float = 0.0
    _emit_pending: bool = False
    _last_error: str | None = None

    def __post_init__(self) -> None:
        self.queue = JobQueue(
            deck_provider=self._context,
            synth=self._synth,
            is_paid=lambda: BACKENDS[self.engine].paid,
            current_index=self._current_index,
            on_change=self._changed,
            on_error=self._failed,
        )
        self.queue.start()

    # ---- the queue's injected dependencies ---------------------------------
    def _context(self) -> tuple[Deck, Config, Any]:
        loaded = deck_service(self.entry.pdf_path, self.entry.sidecar_path).load()
        config = with_engine(loaded.config, self.engine)
        return loaded.deck, config, resolve_audio_dir(self.entry.pdf_path, config).path

    def _synth(self, targets: set[Target], force: bool) -> object:
        with engine_lock(self.engine):
            made = api.synthesize_deck(
                self.entry.pdf_path,
                sidecar_path=self.entry.sidecar_path,
                only_segments=set(targets),
                force=force,
                engine=self.engine,
            )
        deck_service(self.entry.pdf_path, self.entry.sidecar_path).schedule_prune()
        return made

    def _current_index(self) -> int | None:
        if self.focus_slide is None:
            return None
        pages, _ = deck_service(self.entry.pdf_path, self.entry.sidecar_path).page_ids()
        return pages.index(self.focus_slide) if self.focus_slide in pages else None

    def _changed(self) -> None:
        """Coalesce change notifications: at most one event per interval, plus a trailer."""
        now = time.monotonic()
        if now - self._last_emit >= _EMIT_INTERVAL_S:
            self._publish()
        elif not self._emit_pending:
            self._emit_pending = True
            loop = asyncio.get_running_loop()
            loop.call_later(_EMIT_INTERVAL_S, self._trailing)

    def _trailing(self) -> None:
        self._emit_pending = False
        self._publish()

    def _publish(self) -> None:
        self._last_emit = time.monotonic()
        self.bus.publish("generation.changed", deck=self.entry.token, data={"engine": self.engine})

    def _failed(self, handle: JobHandle) -> None:
        self._last_error = str(handle.error) if handle.error else "generation failed"
        self.bus.publish(
            "generation.failed",
            deck=self.entry.token,
            data={"engine": self.engine, "message": self._last_error},
        )

    # ---- operations (call on the event loop) ----------------------------------
    def enqueue(
        self, targets: set[Target], *, force: bool, allow_paid: bool, owner: str | None
    ) -> int:
        return len(self.queue.enqueue(targets, force=force, allow_paid=allow_paid, owner=owner))

    def focus(self, slide_id: str | None) -> None:
        self.focus_slide = slide_id

    def cancel(self, owner: str | None) -> int:
        return self.queue.cancel_owned(owner) if owner else self.queue.cancel_all()

    def preempt_for(self, targets: set[Target]) -> None:
        """A preview needs *targets* now: pause a heavy clip for another slide (re-queued)."""
        self.queue.cancel_running_unless(targets)

    def status(self) -> dict[str, Any]:
        done, total = self.queue.progress()
        running = self.queue.running_handle()
        running_info: dict[str, Any] | None = None
        if running is not None and running.refs:
            sid, si = min(running.refs)
            elapsed = time.monotonic() - running.started_at if running.started_at else 0.0
            running_info = {
                "slide_id": sid,
                "speech_index": si,
                "elapsed": max(0.0, elapsed),
                "estimate": self._estimate(sid, si),
            }
        inflight = sorted({ref for handle in self.queue.inflight() for ref in handle.refs})
        return {
            "engine": self.engine,
            "done": done,
            "total": total,
            "running": running_info,
            "inflight": [{"slide_id": s, "speech_index": i} for s, i in inflight],
            "last_error": self._last_error,
        }

    def _estimate(self, slide_id: str, speech_index: int) -> float | None:
        """Rough seconds to generate a clip: its words → audio seconds × engine speed."""
        try:
            deck, _, _ = self._context()
        except (SlideSonnetError, ValueError, OSError):  # a half-written sidecar: no estimate
            return None
        speeches = deck.page_narration(slide_id).speech_segments
        if speech_index >= len(speeches):
            return None
        audio_seconds = word_count(speeches[speech_index].text) / 150.0 * 60.0
        return max(0.5, audio_seconds * BACKENDS[self.engine].rtf)

    def stop(self) -> None:
        self.queue.cancel_all()
        self.queue.stop()


class GenerationHub:
    """Every deck's generation queues, created on first use (on the event loop)."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._queues: dict[tuple[str, str], DeckGeneration] = {}

    def get(
        self, entry: DeckEntry, engine: Backend, *, create: bool = True
    ) -> DeckGeneration | None:
        key = (entry.token, engine)
        gen = self._queues.get(key)
        if gen is None and create:
            gen = DeckGeneration(entry=entry, engine=engine, bus=self.bus)
            self._queues[key] = gen
        return gen

    def for_deck(self, token: str) -> list[DeckGeneration]:
        return [g for (t, _), g in self._queues.items() if t == token]

    def shutdown(self) -> None:
        for gen in self._queues.values():
            gen.stop()
        self._queues.clear()
