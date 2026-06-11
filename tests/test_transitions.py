"""Slide-boundary transitions: resolution rule + conflict diagnostic."""

from __future__ import annotations

from slidesonnet.diagnostics import boundary_transition, diagnose
from slidesonnet.narration.model import PageNarration, Segment, Transition

CROSSFADE = Transition("crossfade", 0.5)
CUT = Transition()


def _block(slide_id: str, *, tin: Transition = CUT, tout: Transition = CUT) -> PageNarration:
    return PageNarration(
        slide_id=slide_id,
        segments=[Segment.speech("hi")],
        transition_in=tin,
        transition_out=tout,
    )


def test_boundary_defaults_to_cut() -> None:
    assert boundary_transition(_block("a"), _block("b")) == CUT


def test_boundary_uses_next_slide_transition_in_when_earlier_is_cut() -> None:
    assert boundary_transition(_block("a"), _block("b", tin=CROSSFADE)) == CROSSFADE


def test_boundary_earlier_slide_wins_on_conflict() -> None:
    earlier = _block("a", tout=Transition("crossfade", 1.0))
    later = _block("b", tin=Transition("crossfade", 0.2))
    assert boundary_transition(earlier, later) == Transition("crossfade", 1.0)


def test_boundary_handles_missing_blocks() -> None:
    assert boundary_transition(None, None) == CUT
    assert boundary_transition(None, _block("b", tin=CROSSFADE)) == CROSSFADE


def test_conflict_warns_when_sides_disagree() -> None:
    blocks = [
        _block("a", tout=Transition("crossfade", 1.0)),
        _block("b", tin=Transition("crossfade", 0.2)),
    ]
    diags = diagnose(["a", "b"], blocks)
    conflict = [d for d in diags if d.code == "transition-conflict"]
    assert len(conflict) == 1
    assert conflict[0].severity == "warning"
    assert conflict[0].slide_id == "a"  # reported on the earlier slide


def test_no_conflict_when_only_earlier_side_set() -> None:
    # the canonical GUI shape: transition lives on transition_out, next side is a cut
    blocks = [_block("a", tout=CROSSFADE), _block("b")]
    diags = diagnose(["a", "b"], blocks)
    assert not any(d.code == "transition-conflict" for d in diags)


def test_no_conflict_when_sides_agree() -> None:
    blocks = [_block("a", tout=CROSSFADE), _block("b", tin=CROSSFADE)]
    diags = diagnose(["a", "b"], blocks)
    assert not any(d.code == "transition-conflict" for d in diags)


def test_has_nondefault_transitions_flag() -> None:
    assert not _block("a").has_nondefault_transitions
    assert _block("a", tout=CROSSFADE).has_nondefault_transitions
    assert _block("a", tin=CROSSFADE).has_nondefault_transitions
