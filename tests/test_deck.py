"""Tests for deck loading and sidecar save (PDF + narration join)."""

from __future__ import annotations

from pathlib import Path

from slidesonnet.deck import (
    blank_blocks_for,
    dedupe_page_ids,
    default_sidecar_path,
    load_deck,
    save_deck,
)
from slidesonnet.narration.format import serialize_sidecar
from slidesonnet.narration.model import PageNarration, Segment

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def test_dedupe_renames_later_occurrences() -> None:
    pages, diags = dedupe_page_ids(["a", "twin", "twin", "twin"])
    assert pages == ["a", "twin", "twin-2", "twin-3"]
    renames = [d for d in diags if d.code == "duplicate-id"]
    assert all(d.severity == "warning" for d in renames)
    assert {d.slide_id for d in renames} == {"twin", "twin-2", "twin-3"}


def test_dedupe_never_collides_with_a_real_id() -> None:
    # a genuine 'twin-2' page exists: the renamed twin must skip past it
    pages, _ = dedupe_page_ids(["twin", "twin", "twin-2"])
    assert pages == ["twin", "twin-3", "twin-2"]


def test_dedupe_leaves_unique_and_unmarked_pages_alone() -> None:
    pages, diags = dedupe_page_ids(["a", "", "b", ""])
    assert pages == ["a", "", "b", ""]  # unmarked pages have their own diagnostic
    assert diags == []


def test_load_deck_disambiguates_duplicate_ids(tmp_path: Path) -> None:
    from tests.conftest import write_pdf

    pdf = write_pdf(tmp_path / "deck.pdf", ["twin", "twin"])
    (tmp_path / "deck.narration").write_text("@twin\nHello.\n", encoding="utf-8")
    deck, diags = load_deck(pdf)
    assert deck.pages == ["twin", "twin-2"]
    assert deck.page_narration("twin").speech_text == "Hello."
    assert deck.page_narration("twin-2").is_silent  # its own (empty) narration slot
    assert not any(d.severity == "error" for d in diags)  # a warning now, not an error
    assert any(d.code == "duplicate-id" and "renamed" in d.message for d in diags)


def test_default_sidecar_path() -> None:
    assert default_sidecar_path(Path("/x/deck.pdf")).name == "deck.narration"


def test_load_deck_without_sidecar_warns_all_missing() -> None:
    deck, diags = load_deck(MARKED)
    assert deck.pages[0] == "intro-title"
    assert deck.narration == {}
    assert any(d.code == "missing-narration" for d in diags)


def test_load_deck_with_sidecar(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    sidecar = tmp_path / "marked.narration"
    blocks = [PageNarration("intro-title", [Segment.speech("Hello.")])]
    sidecar.write_text(serialize_sidecar(blocks), encoding="utf-8")

    deck, diags = load_deck(pdf)
    assert deck.narration["intro-title"].speech_text == "Hello."
    assert not any(d.code == "orphan-narration" for d in diags)


def test_blank_blocks_for_dedups_and_orders() -> None:
    blocks = blank_blocks_for(["a", "b", "a", "", "c"])
    assert [b.slide_id for b in blocks] == ["a", "b", "c"]
    assert all(b.segments == [] for b in blocks)


def test_save_deck_round_trips(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    deck, _ = load_deck(pdf)
    deck.narration["intro-title"] = PageNarration("intro-title", [Segment.speech("Hi there.")])
    save_deck(deck)

    deck2, _ = load_deck(pdf)
    assert deck2.narration["intro-title"].speech_text == "Hi there."


def test_save_deck_orders_by_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    deck, _ = load_deck(pdf)
    for pid in deck.pages:
        if pid:
            deck.narration[pid] = PageNarration(pid, [Segment.speech(pid)])
    save_deck(deck)
    text = deck.sidecar_path.read_text(encoding="utf-8")
    # intro-title block precedes euler-setup in the file
    assert text.index("@intro-title") < text.index("@euler-setup")


def test_save_deck_keeps_orphan_blocks(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    deck, _ = load_deck(pdf)
    deck.narration["ghost"] = PageNarration("ghost", [Segment.speech("Boo.")])
    save_deck(deck)
    text = deck.sidecar_path.read_text(encoding="utf-8")
    assert "@ghost" in text and "Boo." in text  # orphan not silently dropped


def test_ordered_narration_fills_unnarrated_pages() -> None:
    from slidesonnet.narration.model import Deck

    deck = Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b"],
        narration={"a": PageNarration("a", [Segment.speech("Hi a.")])},
    )
    blocks = deck.ordered_narration
    assert [b.slide_id for b in blocks] == ["a", "b"]
    assert blocks[0].speech_text == "Hi a."
    assert blocks[1].is_silent  # un-narrated page gets an empty block


def test_restricted_to_is_one_page_view() -> None:
    from slidesonnet.narration.model import Deck

    deck = Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a", "b"],
        narration={
            "a": PageNarration("a", [Segment.speech("Hi a.")]),
            "b": PageNarration("b", [Segment.speech("Hi b.")]),
        },
    )
    sub = deck.restricted_to("b")
    assert sub.pages == ["b"]
    assert sub.page_narration("b").speech_text == "Hi b."
    assert sub.pdf_path == deck.pdf_path and sub.sidecar_path == deck.sidecar_path
