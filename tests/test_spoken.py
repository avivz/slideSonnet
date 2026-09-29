"""Inline pronunciation fixes: ``[display](spoken)`` — what each engine and the captions get."""

from __future__ import annotations

import pytest

from slidesonnet.narration.format import parse_sidecar, serialize_sidecar
from slidesonnet.narration.spoken import display_text, engine_text

# (narration text, captions, Inworld, Kokoro/Qwen3)
CASES = [
    # no fix: every form is the text itself (so no cache key moves)
    ("Plain words.", "Plain words.", "Plain words.", "Plain words."),
    # IPA: Inworld only; the other engines say the display word
    (
        "the work of [Mengoli](/menˈɡoːli/) in 1650",
        "the work of Mengoli in 1650",
        "the work of /menˈɡoːli/ in 1650",
        "the work of Mengoli in 1650",
    ),
    # several words, one IPA pair each
    (
        "[Leonhard Euler](/ˈleɪɒnhɑːrt/ /ˈɔɪlər/) summed it",
        "Leonhard Euler summed it",
        "/ˈleɪɒnhɑːrt/ /ˈɔɪlər/ summed it",
        "Leonhard Euler summed it",
    ),
    # a respelling serves every engine, never the captions
    (
        "Ask [Dijkstra](DYKE-struh)'s way.",
        "Ask Dijkstra's way.",
        "Ask DYKE-struh's way.",
        "Ask DYKE-struh's way.",
    ),
    # a blank spoken form is no fix at all
    ("[Basel]( ) is a city", "Basel is a city", "Basel is a city", "Basel is a city"),
    # not a fix: a space before the parenthesis, a pause marker, a bare bracket
    (
        "[x] (y) and [pause 2]",
        "[x] (y) and [pause 2]",
        "[x] (y) and [pause 2]",
        "[x] (y) and [pause 2]",
    ),
]


@pytest.mark.parametrize(("text", "captions", "inworld", "local"), CASES)
def test_each_reader_gets_its_form(text: str, captions: str, inworld: str, local: str) -> None:
    assert display_text(text) == captions
    assert engine_text(text, ipa=True, dictionary={}) == inworld
    assert engine_text(text, ipa=False, dictionary={}) == local


def test_the_dictionary_applies_to_every_engine_as_before() -> None:
    """Without inline fixes every engine gets exactly ``apply_pronunciation``'s text
    (IPA values included), so no existing clip is re-keyed."""
    d = {"Mengoli": "/menˈɡoːli/", "Euler": "OY-ler"}
    text = "Mengoli and Euler"
    for ipa in (True, False):
        assert engine_text(text, ipa=ipa, dictionary=d) == "/menˈɡoːli/ and OY-ler"


def test_an_inline_fix_wins_over_the_dictionary() -> None:
    d = {"Euler": "OY-ler", "Mengoli": "MEN-go-lee"}
    text = "[Euler](/ˈɔɪlər/) and [Mengoli](/menˈɡoːli/)"
    assert engine_text(text, ipa=True, dictionary=d) == "/ˈɔɪlər/ and /menˈɡoːli/"
    # an IPA fix falls back to the display word, which the dictionary may respell
    assert engine_text(text, ipa=False, dictionary=d) == "OY-ler and MEN-go-lee"


def test_fixes_round_trip_in_the_sidecar() -> None:
    src = "@s1\n  utterance:\n    text: the work of [Mengoli](/menˈɡoːli/), [x](y)\n"
    blocks = parse_sidecar(src)
    assert blocks[0].segments[0].text == "the work of [Mengoli](/menˈɡoːli/), [x](y)"
    assert serialize_sidecar(blocks) == src
