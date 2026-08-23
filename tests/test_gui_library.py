"""Deck discovery and the token registry behind inter-deck navigation."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.gui.library import (
    DeckEntry,
    DeckRegistry,
    ScanLimits,
    deck_token,
    discover_decks,
    natural_key,
)


def _deck(dirpath: Path, stem: str, *, sidecar: bool = True) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    pdf = dirpath / f"{stem}.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    if sidecar:
        (dirpath / f"{stem}.narration").write_text("@intro\nhello\n", encoding="utf-8")
    return pdf


# ---- tokens ------------------------------------------------------------


def test_token_is_stable_and_path_derived(tmp_path: Path) -> None:
    pdf = _deck(tmp_path / "a", "deck")
    assert deck_token(pdf) == deck_token(pdf)
    assert len(deck_token(pdf)) == 8
    assert deck_token(pdf) != deck_token(_deck(tmp_path / "b", "deck"))


def test_token_ignores_path_spelling(tmp_path: Path) -> None:
    """A token addresses the resolved deck, so ``./a/../a/deck.pdf`` is one deck."""
    pdf = _deck(tmp_path / "a", "deck")
    assert deck_token(tmp_path / "a" / ".." / "a" / "deck.pdf") == deck_token(pdf)


# ---- discovery ---------------------------------------------------------


def test_discovers_decks_nested_in_subfolders(tmp_path: Path) -> None:
    """The course layout: <root>/weekNN/<deck>/<deck>.pdf — found by walking down."""
    _deck(tmp_path / "week01" / "intro", "intro")
    _deck(tmp_path / "week02" / "llm_basics", "llm_basics")
    result = discover_decks(tmp_path)
    assert [e.label for e in result.decks] == [
        "week01/intro/intro",
        "week02/llm_basics/llm_basics",
    ]
    assert not result.truncated


def test_pdf_without_a_sidecar_is_listed_separately(tmp_path: Path) -> None:
    _deck(tmp_path / "narrated", "a")
    _deck(tmp_path / "bare", "b", sidecar=False)
    result = discover_decks(tmp_path)
    assert [e.label for e in result.decks] == ["narrated/a"]
    assert [e.label for e in result.unnarrated] == ["bare/b"]
    assert result.decks[0].sidecar_path is not None
    assert result.unnarrated[0].sidecar_path is None


def test_prunes_dot_dirs_and_vendor_dirs(tmp_path: Path) -> None:
    """A deck's own cache holds PDFs; scanning them would list phantom decks."""
    _deck(tmp_path / "real", "deck")
    _deck(tmp_path / ".slidesonnet" / "render", "cached")
    _deck(tmp_path / ".git" / "objects", "junk")
    _deck(tmp_path / "node_modules" / "pkg", "junk")
    _deck(tmp_path / ".venv" / "share", "junk")
    assert [e.label for e in discover_decks(tmp_path).decks] == ["real/deck"]


def test_deck_at_the_root_itself_is_found(tmp_path: Path) -> None:
    _deck(tmp_path, "solo")
    assert [e.label for e in discover_decks(tmp_path).decks] == ["solo"]


def test_depth_cap_stops_the_walk_and_reports_truncation(tmp_path: Path) -> None:
    _deck(tmp_path / "a" / "b" / "c" / "d", "deep")
    limits = ScanLimits(max_depth=2, max_dirs=1000)
    result = discover_decks(tmp_path, limits=limits)
    assert result.decks == []
    assert result.truncated


def test_visit_cap_stops_the_walk_and_reports_truncation(tmp_path: Path) -> None:
    """Launched somewhere huge, the scan bails out instead of hanging."""
    for i in range(20):
        (tmp_path / f"dir{i}").mkdir()
    _deck(tmp_path / "dir19", "late")
    result = discover_decks(tmp_path, limits=ScanLimits(max_depth=6, max_dirs=5))
    assert result.truncated


def test_scan_is_naturally_sorted(tmp_path: Path) -> None:
    """week10 sorts after week9 — a course list is unreadable otherwise."""
    for name in ("week9", "week10", "week1"):
        _deck(tmp_path / name, "d")
    assert [e.group for e in discover_decks(tmp_path).decks] == ["week1", "week9", "week10"]


def test_natural_key_orders_embedded_numbers() -> None:
    assert sorted(["a10", "a9", "a1"], key=natural_key) == ["a1", "a9", "a10"]


def test_missing_root_scans_to_nothing(tmp_path: Path) -> None:
    result = discover_decks(tmp_path / "nope")
    assert result.decks == [] and not result.truncated


def test_group_is_empty_for_a_root_level_deck(tmp_path: Path) -> None:
    _deck(tmp_path, "solo")
    assert discover_decks(tmp_path).decks[0].group == ""


# ---- registry ----------------------------------------------------------


def test_registry_resolves_a_scanned_deck(tmp_path: Path) -> None:
    pdf = _deck(tmp_path / "w", "deck")
    reg = DeckRegistry(tmp_path)
    reg.rescan()
    entry = reg.resolve(deck_token(pdf))
    assert entry is not None and entry.pdf_path == pdf.resolve()


def test_registry_refuses_an_unregistered_token(tmp_path: Path) -> None:
    """The URL bar must not be able to open an arbitrary PDF off disk."""
    outsider = _deck(tmp_path / "elsewhere", "secret")
    reg = DeckRegistry(tmp_path / "root")
    (tmp_path / "root").mkdir()
    reg.rescan()
    assert reg.resolve(deck_token(outsider)) is None


def test_registry_registers_an_explicit_deck_outside_the_root(tmp_path: Path) -> None:
    """`edit ../other/deck.pdf` from a course root still opens that deck."""
    (tmp_path / "root").mkdir()
    outsider = _deck(tmp_path / "elsewhere", "deck")
    reg = DeckRegistry(tmp_path / "root")
    entry = reg.register(outsider)
    reg.rescan()  # a rescan must not drop the explicitly-registered deck
    assert reg.resolve(entry.token) is not None
    assert entry in reg.entries()


def test_registry_keeps_an_explicit_sidecar_override(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, "deck")
    other = tmp_path / "alt.narration"
    other.write_text("@intro\nhi\n", encoding="utf-8")
    reg = DeckRegistry(tmp_path)
    entry = reg.register(pdf, sidecar_path=other)
    reg.rescan()
    resolved = reg.resolve(entry.token)
    assert resolved is not None and resolved.sidecar_path == other.resolve()


def test_registry_neighbours_wrap_around(tmp_path: Path) -> None:
    """Alt+←/→ steps through the library and wraps, so an audit pass never dead-ends."""
    for name in ("w1", "w2", "w3"):
        _deck(tmp_path / name, "d")
    reg = DeckRegistry(tmp_path)
    reg.rescan()
    labels = [e.label for e in reg.entries()]
    assert labels == ["w1/d", "w2/d", "w3/d"]
    first = reg.entries()[0]
    assert reg.neighbour(first.token, +1).label == "w2/d"  # type: ignore[union-attr]
    assert reg.neighbour(first.token, -1).label == "w3/d"  # type: ignore[union-attr]


def test_registry_neighbour_of_a_lone_deck_is_itself(tmp_path: Path) -> None:
    _deck(tmp_path, "solo")
    reg = DeckRegistry(tmp_path)
    reg.rescan()
    token = reg.entries()[0].token
    assert reg.neighbour(token, 1) is not None
    assert reg.neighbour(token, 1).token == token  # type: ignore[union-attr]


def test_registry_neighbour_of_an_unknown_token_is_none(tmp_path: Path) -> None:
    reg = DeckRegistry(tmp_path)
    reg.rescan()
    assert reg.neighbour("deadbeef", 1) is None


def test_rescan_picks_up_a_new_deck(tmp_path: Path) -> None:
    _deck(tmp_path / "w1", "a")
    reg = DeckRegistry(tmp_path)
    reg.rescan()
    assert len(reg.entries()) == 1
    _deck(tmp_path / "w2", "b")
    reg.rescan()
    assert len(reg.entries()) == 2


def test_entries_are_grouped_by_top_level_folder(tmp_path: Path) -> None:
    """One deck per folder is the norm, so sections come from the week, not the deck."""
    _deck(tmp_path / "week01" / "a", "a")
    _deck(tmp_path / "week01" / "b", "b")
    _deck(tmp_path / "week02" / "c", "c")
    reg = DeckRegistry(tmp_path)
    reg.rescan()
    groups = reg.grouped()
    assert [g for g, _ in groups] == ["week01", "week02"]
    assert [e.name for e in groups[0][1]] == ["a", "b"]


def test_grouped_sections_follow_natural_order(tmp_path: Path) -> None:
    for name in ("week9", "week10", "week1"):
        _deck(tmp_path / name / "d", "d")
    reg = DeckRegistry(tmp_path)
    reg.rescan()
    assert [g for g, _ in reg.grouped()] == ["week1", "week9", "week10"]


def test_root_level_deck_lands_in_the_empty_section(tmp_path: Path) -> None:
    _deck(tmp_path, "solo")
    reg = DeckRegistry(tmp_path)
    reg.rescan()
    assert [g for g, _ in reg.grouped()] == [""]


def test_entry_display_name_is_the_deck_stem(tmp_path: Path) -> None:
    pdf = _deck(tmp_path / "week02" / "llm", "lecture02_4_llm_basics")
    entry = DeckEntry.build(pdf, root=tmp_path)
    assert entry.name == "lecture02_4_llm_basics"
    assert entry.group == "week02/llm"


@pytest.mark.parametrize("root_name", ["root", "root with spaces"])
def test_label_uses_posix_separators(tmp_path: Path, root_name: str) -> None:
    root = tmp_path / root_name
    pdf = _deck(root / "w" / "d", "d")
    entry = DeckEntry.build(pdf, root=root)
    assert entry.label == "w/d/d"
