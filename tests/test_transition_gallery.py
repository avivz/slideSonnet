"""The curated xfade transition gallery: taxonomy, grammar, and rendering map."""

from __future__ import annotations

import pytest

from slidesonnet.narration import transitions as T
from slidesonnet.narration.format import parse_sidecar, serialize_block
from slidesonnet.narration.model import PageNarration, Segment, Transition


# --- xfade name resolution -------------------------------------------------


def test_xfade_name_cut_is_none() -> None:
    assert T.xfade_name("cut") is None


def test_xfade_name_crossfade_alias_maps_to_fade() -> None:
    assert T.xfade_name("crossfade") == "fade"


@pytest.mark.parametrize(
    "name",
    ["fade", "dissolve", "wipeleft", "slideup", "coverright", "revealdown", "circleopen"],
)
def test_xfade_name_passthrough(name: str) -> None:
    assert T.xfade_name(name) == name


# --- the gallery / validation set ------------------------------------------


def test_gallery_contains_every_family_name() -> None:
    for fam in T.FAMILIES:
        names = [n for _l, n in fam.options] or [fam.key]
        for name in names:
            assert name in T.TRANSITION_NAMES


def test_gallery_has_crossfade_alias_and_directional_names() -> None:
    assert "crossfade" in T.TRANSITION_NAMES
    assert {"wipeleft", "wipedown", "slideup", "coverright", "revealleft"} <= T.TRANSITION_NAMES
    assert {"circleopen", "circleclose"} <= T.TRANSITION_NAMES


def test_curated_8_families() -> None:
    assert [f.label for f in T.FAMILIES] == [
        "Cut",
        "Fade",
        "Dissolve",
        "Wipe",
        "Slide",
        "Cover",
        "Reveal",
        "Circle",
    ]


# --- family <-> name decomposition (the picker) ----------------------------


def test_decompose_directional() -> None:
    assert T.decompose("wipeleft") == ("wipe", "Left")
    assert T.decompose("slideup") == ("slide", "Up")
    assert T.decompose("circleopen") == ("circle", "Open")


def test_decompose_nondirectional() -> None:
    assert T.decompose("fade") == ("fade", None)
    assert T.decompose("cut") == ("cut", None)


def test_decompose_crossfade_presents_as_fade() -> None:
    assert T.decompose("crossfade") == ("fade", None)


def test_decompose_unknown_raises() -> None:
    with pytest.raises(KeyError):
        T.decompose("teleport")


def test_compose_directional_roundtrips() -> None:
    assert T.compose("wipe", "Left") == "wipeleft"
    assert T.compose("circle", "Close") == "circleclose"


def test_compose_nondirectional_ignores_direction() -> None:
    assert T.compose("fade", None) == "fade"
    assert T.compose("cut", "Left") == "cut"


def test_compose_directional_defaults_to_first_option() -> None:
    assert T.compose("wipe", None) == "wipeleft"
    assert T.compose("circle", None) == "circleopen"


def test_directions_for_family() -> None:
    assert T.directions_for("wipe") == ["Left", "Right", "Up", "Down"]
    assert T.directions_for("fade") == []


# --- model -----------------------------------------------------------------


def test_transition_accepts_gallery_name() -> None:
    assert Transition("wipeleft", 0.6).kind == "wipeleft"


def test_transition_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown transition"):
        Transition("teleport", 0.5)


def test_is_animated() -> None:
    assert not Transition("cut").is_animated
    assert Transition("wipeleft", 0.5).is_animated
    assert Transition("crossfade", 0.5).is_animated


# --- grammar (parse + serialize) -------------------------------------------


def test_parse_gallery_name() -> None:
    blocks = parse_sidecar("@a\n  utterance:\n    text: hi\n  transition-out: wipeleft 0.6\n")
    assert blocks[0].transition_out == Transition("wipeleft", 0.6)


def test_serialize_gallery_name() -> None:
    block = PageNarration(
        slide_id="x",
        segments=[Segment.speech("Hi.")],
        transition_out=Transition("slideup", 0.5),
    )
    assert serialize_block(block) == (
        "@x\n  utterance:\n    text: Hi.\n  transition-out: slideup 0.5"
    )


def test_gallery_name_round_trips() -> None:
    src = "@a\n  utterance:\n    text: one\n  transition-out: coverright 0.4\n"
    blocks = parse_sidecar(src)
    assert serialize_block(blocks[0]) + "\n" == src
