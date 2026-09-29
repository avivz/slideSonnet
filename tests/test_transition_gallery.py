"""The curated xfade transition gallery: taxonomy, grammar, and rendering map."""

from __future__ import annotations

import pytest

from slidesonnet.narration import transitions as T
from slidesonnet.narration.format import parse_sidecar, serialize_block
from slidesonnet.narration.model import Transition


@pytest.mark.parametrize(
    ("kind", "xfade"),
    [
        ("cut", None),
        ("crossfade", "fade"),
        *[
            (name, name)
            for name in (
                "fade",
                "fadeblack",
                "fadewhite",
                "dissolve",
                "wipeleft",
                "slideup",
                "coverright",
                "revealdown",
                "circleopen",
            )
        ],
    ],
)
def test_xfade_name(kind: str, xfade: str | None) -> None:
    assert kind in T.TRANSITION_NAMES
    assert T.xfade_name(kind) == xfade


def test_curated_families_and_their_names() -> None:
    assert [f.label for f in T.FAMILIES] == [
        "Cut",
        "Fade",
        "Fade through black",
        "Fade through white",
        "Dissolve",
        "Wipe",
        "Slide",
        "Cover",
        "Reveal",
        "Circle",
    ]
    family_names = {n for f in T.FAMILIES for n in ([n for _l, n in f.options] or [f.key])}
    assert T.TRANSITION_NAMES == family_names | {"crossfade"}
    assert {"wipeleft", "wipedown", "circleopen", "circleclose"} <= T.TRANSITION_NAMES


def test_transition_model_validates_gallery_names() -> None:
    assert Transition("wipeleft", 0.6).kind == "wipeleft"
    with pytest.raises(ValueError, match="unknown transition"):
        Transition("teleport", 0.5)


def test_is_animated() -> None:
    assert not Transition("cut").is_animated
    assert Transition("wipeleft", 0.5).is_animated
    assert Transition("crossfade", 0.5).is_animated


def test_gallery_name_parses_and_round_trips() -> None:
    src = "@a\n  utterance:\n    text: one\n  transition-out: coverright 0.4\n"
    blocks = parse_sidecar(src)
    assert blocks[0].transition_out == Transition("coverright", 0.4)
    assert serialize_block(blocks[0]) + "\n" == src
