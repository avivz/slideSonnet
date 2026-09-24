"""Whole-run progress: one overall percentage, stable console lines, phase timings.

The pipeline stages report per-phase counters through a
:data:`~slidesonnet.models.ProgressFn` — ``(phase, done, total, label)``, each
phase counting from 0 on its own. :class:`RunProgress` is such a callback: it
maps each phase onto a share of the whole run so the overall percentage never
goes backwards, and emits one line per update in a fixed format any wrapper (a
progress window, CI, a log grep) can follow with :data:`LINE_PATTERN`::

    [01:42 37%] 3/5 video 7/23 · step2-zeros
    [02:10 81%] 4/5 concat 142/391s

The time prefix is the elapsed time since the run started; ``3/5`` is the
phase's place in the run, so a wrapper that draws phases can use
:data:`PHASE_PATTERN` instead. Phases that count
seconds of output (the final ffmpeg passes) carry an ``s`` unit and only print
when the percentage moves, since ffmpeg reports twice a second.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

#: Matches every progress line; ``pct`` is the overall percentage, ``text`` the rest.
LINE_PATTERN = r"\[(?:\S+ )?(?P<pct>\d+)%\] (?P<text>.*)"

#: Matches lines of a planned phase: phase ``phase`` of ``phases``, named ``name``,
#: ``done`` of ``total`` through it; ``text`` is everything after the position.
PHASE_PATTERN = (
    r"\[(?:\S+ )?(?P<pct>\d+)%\] (?P<phase>\d+)/(?P<phases>\d+) "
    r"(?P<text>(?P<name>\S+) (?P<done>\d+)/(?P<total>\d+)s?(?: · .*)?)"
)

#: Phases whose ``done``/``total`` are seconds of output written, not item counts.
SECONDS_PHASES = frozenset({"concat", "mux"})

#: Export's phases, in the order they run.
EXPORT_PHASES = ("tts", "assemble", "video", "concat", "mux")
#: A silent export has no speech to synthesize, assemble, or mux.
SILENT_EXPORT_PHASES = ("video", "concat")


def format_clock(seconds: float) -> str:
    """``MM:SS``, or ``H:MM:SS`` from an hour up."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _short_clock(seconds: float) -> str:
    """``M:SS`` for the timing summary."""
    clock = format_clock(seconds)
    return clock[1:] if clock.startswith("0") and len(clock) == 5 else clock


class RunProgress:
    """A :data:`~slidesonnet.models.ProgressFn` that reports the run as a whole.

    *phases* lists the phases the run will go through, in order. Each gets an
    equal share of the overall percentage for now; a phase not in the plan is
    still printed but leaves the percentage where it is.
    """

    def __init__(
        self,
        phases: Sequence[str],
        *,
        emit: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not phases:
            raise ValueError("a progress plan needs at least one phase")
        self._phases = list(phases)
        self._emit = emit
        self._clock = clock
        self._start = clock()
        self._last_tick = self._start
        self._pct = 0
        self._last_key: tuple[str, str, int, int] | None = None
        self._spent: dict[str, float] = {}

    def __call__(self, phase: str, done: int, total: int, label: str) -> None:
        now = self._clock()
        # Time since the previous tick was spent getting this one done.
        self._spent[phase] = self._spent.get(phase, 0.0) + (now - self._last_tick)
        self._last_tick = now

        if phase in self._phases:
            share = 1.0 / len(self._phases)
            frac = min(1.0, done / total) if total > 0 else 1.0
            overall = (self._phases.index(phase) + frac) * share
            self._pct = max(self._pct, min(100, int(overall * 100 + 1e-9)))

        # Seconds phases tick twice a second: print only when the percent moves.
        step = 0 if phase in SECONDS_PHASES else done
        key = (phase, label, self._pct, step)
        if key == self._last_key:
            return
        self._last_key = key
        unit = "s" if phase in SECONDS_PHASES else ""
        text = f"{phase} {done}/{total}{unit}" + (f" · {label}" if label else "")
        if phase in self._phases:
            text = f"{self._phases.index(phase) + 1}/{len(self._phases)} {text}"
        self._emit(f"[{format_clock(now - self._start)} {self._pct}%] {text}")

    def summary(self) -> str:
        """One line splitting the elapsed time by phase, e.g. for the end of a run."""
        parts = [f"{p} {_short_clock(t)}" for p, t in self._spent.items()]
        parts.append(f"total {_short_clock(self._clock() - self._start)}")
        return "Timing: " + " · ".join(parts)
