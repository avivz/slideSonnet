"""A process-wide event bus behind ``GET /api/v1/events`` (Server-Sent Events).

Events are *hints to refetch*, not state: each carries a sequence number, the
deck token when it concerns one deck, and a revision or job id. A client that
reconnects sends the last sequence it saw (``Last-Event-ID``); if the buffer no
longer holds everything after it, the client is told to resync (refetch its
snapshots and active jobs) instead of being replayed a partial history.

Publishing is thread-safe — jobs publish from worker threads — and delivery to
each subscriber hops onto that subscriber's event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

#: Per-subscriber backlog before it is dropped into a resync.
_SUBSCRIBER_BACKLOG = 1000


@dataclass(frozen=True)
class Event:
    seq: int
    type: str
    deck: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    at: float = 0.0


class Subscription:
    """One listener's queue. ``overflowed`` means it missed events and must resync."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=_SUBSCRIBER_BACKLOG)
        self.overflowed = False

    def _deliver(self, event: Event) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.overflowed = True


class EventBus:
    def __init__(self, capacity: int = 512) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._buffer: deque[Event] = deque(maxlen=capacity)
        self._subscribers: set[Subscription] = set()

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def publish(
        self, type: str, *, deck: str | None = None, data: dict[str, Any] | None = None
    ) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(
                seq=self._seq, type=type, deck=deck, data=dict(data or {}), at=time.time()
            )
            self._buffer.append(event)
            subscribers = list(self._subscribers)
        for sub in subscribers:
            with contextlib.suppress(RuntimeError):  # that subscriber's loop is closed
                sub.loop.call_soon_threadsafe(sub._deliver, event)
        return event

    def since(self, seq: int) -> list[Event] | None:
        """Buffered events after *seq*, or ``None`` when some were lost (resync)."""
        with self._lock:
            if seq > self._seq:
                return None  # a sequence from before a restart
            if seq == self._seq:
                return []
            if not self._buffer or self._buffer[0].seq > seq + 1:
                return None
            return [e for e in self._buffer if e.seq > seq]

    def subscribe(self) -> Subscription:
        """Register a listener on the running loop (call from async code)."""
        sub = Subscription(asyncio.get_running_loop())
        with self._lock:
            self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            self._subscribers.discard(sub)
