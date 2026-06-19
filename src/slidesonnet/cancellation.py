"""Cooperative cancellation for in-flight synthesis.

A heavy engine (Qwen3) can spend many seconds on one clip, so the editor needs
to abort a running generation when the user presses play on an ungenerated
slide. Killing the worker thread isn't safe, so cancellation is *cooperative*:
the generation loop polls a token and stops early when it's set.

The token travels via a :class:`~contextvars.ContextVar` rather than through
every ``synthesize`` signature, because ``asyncio.to_thread`` copies the calling
context into the worker thread — so the queue sets the token right before it
dispatches a job and the engine, running in that thread, reads the *same*
``threading.Event`` by reference. Setting the event from the event loop is then
visible to the polling generation thread. Engines that can't honor it (Kokoro,
Inworld — fast enough not to need it) simply ignore the token.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_cancel_token: ContextVar[threading.Event | None] = ContextVar("ss_cancel_token", default=None)


def current_cancel() -> threading.Event | None:
    """The cancel token for the synthesis running in this context, if any."""
    return _cancel_token.get()


@contextmanager
def cancel_scope(event: threading.Event | None) -> Iterator[None]:
    """Bind *event* as the active cancel token for the duration of the block.

    The queue enters this immediately before ``asyncio.to_thread(synth, …)`` so
    the copied thread context carries the token down to the engine. Resets on
    exit so a token never leaks into the next job.
    """
    token = _cancel_token.set(event)
    try:
        yield
    finally:
        _cancel_token.reset(token)
