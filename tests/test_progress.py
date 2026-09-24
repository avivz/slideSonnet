"""Unit tests for the whole-run progress tracker (slidesonnet.progress)."""

from __future__ import annotations

import re

import pytest

from slidesonnet.progress import LINE_PATTERN, PHASE_PATTERN, RunProgress, format_clock


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _run(phases: tuple[str, ...]) -> tuple[RunProgress, list[str], FakeClock]:
    lines: list[str] = []
    clock = FakeClock()
    return RunProgress(phases, emit=lines.append, clock=clock), lines, clock


def test_format_clock() -> None:
    assert format_clock(0) == "00:00"
    assert format_clock(102.7) == "01:42"
    assert format_clock(3725) == "1:02:05"


def test_line_carries_elapsed_percent_phase_count_and_label() -> None:
    run, lines, clock = _run(("tts", "video"))
    clock.now = 102.0
    run("video", 7, 23, "step2-zeros")
    assert lines == ["[01:42 65%] 2/2 video 7/23 · step2-zeros"]


def test_label_is_omitted_when_empty() -> None:
    run, lines, _ = _run(("video",))
    run("video", 1, 4, "")
    assert lines == ["[00:00 25%] 1/1 video 1/4"]


def test_seconds_phases_show_a_seconds_unit() -> None:
    run, lines, _ = _run(("concat",))
    run("concat", 142, 391, "")
    assert lines[-1].endswith("1/1 concat 142/391s")


def test_percent_spans_all_phases_and_ends_at_100() -> None:
    run, lines, _ = _run(("tts", "assemble", "video", "concat", "mux"))
    run("tts", 23, 23, "last-slide")
    run("mux", 390, 390, "")
    first = int(re.search(r"(\d+)%", lines[0]).group(1))  # type: ignore[union-attr]
    assert 0 < first < 100
    assert "100%" in lines[-1]


def test_percent_never_goes_backwards() -> None:
    run, lines, _ = _run(("tts", "video"))
    run("video", 3, 4, "")
    run("tts", 1, 10, "late-straggler")  # an out-of-order tick must not rewind
    pcts = [int(re.search(r"(\d+)%", ln).group(1)) for ln in lines]  # type: ignore[union-attr]
    assert pcts == sorted(pcts)


def test_unplanned_phase_is_still_shown_without_moving_percent() -> None:
    run, lines, _ = _run(("tts",))
    run("tts", 1, 2, "a")
    run("mystery", 1, 1, "")
    assert lines[-1] == "[00:00 50%] mystery 1/1"  # no position: not in the plan


def test_seconds_phase_is_throttled_to_whole_percent_steps() -> None:
    """ffmpeg reports twice a second; only a changed percent earns a new line."""
    run, lines, _ = _run(("concat",))
    for s in range(1001):
        run("concat", s, 1000, "")
    assert len(lines) == 101  # 0%..100%


def test_count_phases_print_every_step() -> None:
    run, lines, _ = _run(("tts",))
    for i in range(1, 301):
        run("tts", i, 300, f"s{i}")
    assert len(lines) == 300  # a new label is news even at the same percent


def test_every_line_matches_the_documented_pattern() -> None:
    run, lines, clock = _run(("tts", "concat"))
    run("tts", 1, 2, "intro-title")
    clock.now = 4000
    run("concat", 5, 10, "")
    for ln in lines:
        m = re.fullmatch(LINE_PATTERN, ln)
        assert m is not None, ln
    assert re.fullmatch(LINE_PATTERN, lines[0]).group("pct") == "25"  # type: ignore[union-attr]
    assert re.fullmatch(LINE_PATTERN, lines[0]).group("text") == "1/2 tts 1/2 · intro-title"  # type: ignore[union-attr]


def test_summary_attributes_time_to_each_phase() -> None:
    run, _, clock = _run(("tts", "video", "concat"))
    clock.now = 10.0
    run("tts", 1, 2, "a")
    clock.now = 151.0
    run("tts", 2, 2, "b")  # tts took 2:31
    clock.now = 160.0
    run("video", 1, 1, "")  # 0:09 — the gap before a phase's first tick is its own
    clock.now = 230.0
    run("concat", 10, 10, "")  # 1:10
    clock.now = 231.0
    assert run.summary() == "Timing: tts 2:31 · video 0:09 · concat 1:10 · total 3:51"


def test_rejects_a_plan_with_no_phases() -> None:
    with pytest.raises(ValueError):
        RunProgress((), emit=lambda s: None)


def test_phase_position_lets_a_wrapper_draw_phases() -> None:
    """A phase-aware wrapper gets phase i of n plus the count within it from one regex."""
    run, lines, _ = _run(("tts", "assemble", "video"))
    run("assemble", 3, 12, "")
    m = re.fullmatch(PHASE_PATTERN, lines[0])
    assert m is not None
    assert m.group("phase", "phases", "name", "done", "total") == ("2", "3", "assemble", "3", "12")
    run("mystery", 1, 1, "")
    assert re.fullmatch(PHASE_PATTERN, lines[1]) is None
