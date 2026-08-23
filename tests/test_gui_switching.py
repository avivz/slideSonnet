"""The deck library page and switching decks without leaving the editor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from nicegui import ui
from nicegui.testing import User

from slidesonnet.gui.app import _filter_decks, _media_url, deck_url
from slidesonnet.gui.library import DeckEntry, DeckRegistry, deck_token
from slidesonnet.gui.state import EditorState

from .conftest import simple_narration, write_pdf

pytestmark = pytest.mark.nicegui_main_file("tests/library_main.py")


def _make_deck(root: Path, rel: str, stem: str, ids: list[str] | None = None) -> Path:
    """A narrated deck at ``<root>/<rel>/<stem>.pdf`` with one page per id."""
    folder = root / rel if rel else root
    folder.mkdir(parents=True, exist_ok=True)
    pdf = write_pdf(folder / f"{stem}.pdf", ids or ["alpha", "beta"])
    body = "".join(f"@{i}\nLine for {i} in {stem}.\n" for i in (ids or ["alpha", "beta"]))
    (folder / f"{stem}.narration").write_text(simple_narration(body), encoding="utf-8")
    return pdf


@pytest.fixture
def course(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A two-week course tree, with the library rooted at it."""
    _make_deck(tmp_path, "week01", "intro")
    _make_deck(tmp_path, "week02", "llm_basics")
    _make_deck(tmp_path, "week02", "prompting")
    monkeypatch.setenv("SLIDESONNET_LIB_ROOT", str(tmp_path))
    return tmp_path


# ---- pure helpers ------------------------------------------------------


def _entry(label: str) -> DeckEntry:
    group, _, name = label.rpartition("/")
    return DeckEntry(Path(f"/{label}.pdf"), None, deck_token(Path(label)), group, name)


def test_filter_matches_every_term_anywhere_in_the_label() -> None:
    entries = [_entry("week02/llm_basics"), _entry("week03/git_basics")]
    assert [e.name for e in _filter_decks(entries, "llm")] == ["llm_basics"]
    assert [e.name for e in _filter_decks(entries, "basics")] == ["llm_basics", "git_basics"]
    assert [e.name for e in _filter_decks(entries, "week03 basics")] == ["git_basics"]
    assert _filter_decks(entries, "nope") == []


def test_filter_is_case_insensitive_and_empty_query_keeps_all() -> None:
    entries = [_entry("week02/LLM_Basics")]
    assert _filter_decks(entries, "llm") == entries
    assert _filter_decks(entries, "   ") == entries


def test_media_urls_are_namespaced_per_deck(tmp_path: Path) -> None:
    """Two decks must not share one media prefix, or deck B shows deck A's pages."""
    a = _make_deck(tmp_path, "wa", "a")
    b = _make_deck(tmp_path, "wb", "b")
    from slidesonnet.cache import render_dir

    state_a, state_b = EditorState(a), EditorState(b)
    url_a = _media_url(state_a, render_dir(a) / "pages" / "page-1.png")
    url_b = _media_url(state_b, render_dir(b) / "pages" / "page-1.png")
    assert url_a != url_b
    assert url_a.startswith(f"/ssmedia/{deck_token(a)}/")
    assert url_b.startswith(f"/ssmedia/{deck_token(b)}/")


# ---- the library page --------------------------------------------------


async def test_library_lists_every_deck_grouped_by_week(user: User, course: Path) -> None:
    await user.open("/")
    await user.should_see("3 decks")
    await user.should_see("week01")
    await user.should_see("week02")
    await user.should_see("intro")
    await user.should_see("llm_basics")
    await user.should_see("prompting")


async def test_library_deck_card_opens_that_deck(user: User, course: Path) -> None:
    await user.open("/")
    user.find(marker=f"deck-card-{deck_token(course / 'week02' / 'llm_basics.pdf')}").click()
    await user.should_see("llm_basics")
    await user.should_see(marker="deck-switcher")  # we're in the editor now


async def test_library_shows_deck_size_and_what_is_left(user: User, course: Path) -> None:
    await user.open("/")
    await user.should_see("2 slides · complete", retries=200)


async def test_library_counts_what_is_still_unnarrated(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = write_pdf(tmp_path / "half.pdf", ["alpha", "beta", "gamma"])
    (tmp_path / "half.narration").write_text(
        simple_narration("@alpha\nOnly this one.\n"), encoding="utf-8"
    )
    assert pdf.exists()
    monkeypatch.setenv("SLIDESONNET_LIB_ROOT", str(tmp_path))
    await user.open("/")
    await user.should_see("3 slides · 2 to narrate", retries=200)


async def test_library_lists_pdfs_without_narration_separately(user: User, course: Path) -> None:
    (course / "week03").mkdir()
    write_pdf(course / "week03" / "draft.pdf", ["alpha"])
    await user.open("/")
    await user.should_see("no narration yet")
    await user.should_see("draft")


async def test_empty_root_explains_what_a_deck_is(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIDESONNET_LIB_ROOT", str(tmp_path))
    await user.open("/")
    await user.should_see("No decks under this folder")
    await user.should_see("matching .narration")


# ---- switching ---------------------------------------------------------


async def test_editor_header_names_the_current_deck(user: User, course: Path) -> None:
    await user.open(deck_url(deck_token(course / "week01" / "intro.pdf")))
    await user.should_see("week01 / intro")


async def test_deck_forward_moves_to_the_next_deck_in_library_order(
    user: User, course: Path
) -> None:
    await user.open(deck_url(deck_token(course / "week01" / "intro.pdf")))
    user.find(marker="deck-next").click()
    await user.should_see("week02 / llm_basics")


async def test_deck_back_wraps_around_to_the_last_deck(user: User, course: Path) -> None:
    await user.open(deck_url(deck_token(course / "week01" / "intro.pdf")))
    user.find(marker="deck-prev").click()
    await user.should_see("week02 / prompting")


async def test_switcher_palette_filters_and_opens(user: User, course: Path) -> None:
    await user.open(deck_url(deck_token(course / "week01" / "intro.pdf")))
    user.find(marker="deck-switcher").click()
    await user.should_see(marker="switcher-input")
    await user.should_see(marker="switcher-row-2")  # unfiltered: all three decks
    user.find(marker="switcher-input").type("prompt")
    await user.should_see("prompting")
    await user.should_not_see(marker="switcher-row-1")  # ...only one match left
    user.find(marker="switcher-row-0").click()
    await user.should_see("week02 / prompting")


async def test_switcher_says_when_nothing_matches(user: User, course: Path) -> None:
    await user.open(deck_url(deck_token(course / "week01" / "intro.pdf")))
    user.find(marker="deck-switcher").click()
    await user.should_see(marker="switcher-input")
    user.find(marker="switcher-input").type("zzz")
    await user.should_see("No deck matches")


async def test_a_lone_deck_disables_the_step_arrows(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _make_deck(tmp_path, "", "solo")
    monkeypatch.setenv("SLIDESONNET_LIB_ROOT", str(tmp_path))
    await user.open(deck_url(deck_token(pdf)))
    await user.should_see(marker="deck-next")
    assert not user.find(marker="deck-next").elements.pop().enabled


async def test_unknown_token_falls_back_to_the_library(user: User, course: Path) -> None:
    """A bookmark for a deck that has since moved must not dead-end."""
    await user.open("/d/deadbeef")
    await user.should_see("3 decks")


async def test_switching_saves_the_current_slide_first(user: User, course: Path) -> None:
    """A pending edit is written before the page goes away, never dropped."""
    intro = course / "week01" / "intro.pdf"
    await user.open(deck_url(deck_token(intro)))
    user.find(ui.textarea).elements.pop().set_value("Edited before leaving.")
    user.find(marker="deck-next").click()
    await user.should_see("week02 / llm_basics")
    sidecar = (course / "week01" / "intro.narration").read_text(encoding="utf-8")
    assert "Edited before leaving." in sidecar


async def test_switching_prompts_while_clips_are_generating(
    user: User, course: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.gui import app as gui_app

    monkeypatch.setattr(gui_app, "_skip_switch_prompt", False)
    monkeypatch.setattr(gui_app.JobQueue, "outstanding", lambda self: 3)
    await user.open(deck_url(deck_token(course / "week01" / "intro.pdf")))
    user.find(marker="deck-next").click()
    await user.should_see("3 clips are still generating")
    user.find(marker="switch-stay").click()
    await user.should_see("week01 / intro")  # stayed put


async def test_switching_proceeds_when_the_prompt_is_accepted(
    user: User, course: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.gui import app as gui_app

    monkeypatch.setattr(gui_app, "_skip_switch_prompt", False)
    monkeypatch.setattr(gui_app.JobQueue, "outstanding", lambda self: 1)
    await user.open(deck_url(deck_token(course / "week01" / "intro.pdf")))
    user.find(marker="deck-next").click()
    await user.should_see("1 clip is still generating")
    user.find(marker="switch-go").click()
    await user.should_see("week02 / llm_basics")


async def test_no_prompt_when_nothing_is_generating(
    user: User, course: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.gui import app as gui_app

    monkeypatch.setattr(gui_app, "_skip_switch_prompt", False)
    await user.open(deck_url(deck_token(course / "week01" / "intro.pdf")))
    user.find(marker="deck-next").click()
    await user.should_see("week02 / llm_basics")


# ---- media routing (the blocker: one mount used to serve deck A only) ----


async def test_each_deck_serves_its_own_page_images(user: User, course: Path) -> None:
    """The route is per-deck: deck B's URL must never return deck A's bytes."""
    intro = course / "week01" / "intro.pdf"
    llm = course / "week02" / "llm_basics.pdf"
    await user.open(deck_url(deck_token(intro)))  # registers + creates render dirs
    await user.open(deck_url(deck_token(llm)))

    from slidesonnet.cache import render_dir

    for pdf, body in ((intro, b"intro-bytes"), (llm, b"llm-bytes")):
        pages = render_dir(pdf) / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        (pages / "page-1.png").write_bytes(body)

    for pdf, body in ((intro, b"intro-bytes"), (llm, b"llm-bytes")):
        url = f"/ssmedia/{deck_token(pdf)}/pages/page-1.png"
        response = await user.http_client.get(url)
        assert response.status_code == 200
        assert response.content == body


async def test_media_route_refuses_an_unregistered_deck(user: User, course: Path) -> None:
    await user.open("/")
    response = await user.http_client.get("/ssmedia/deadbeef/pages/page-1.png")
    assert response.status_code == 404


async def test_media_route_refuses_path_traversal(user: User, course: Path) -> None:
    intro = course / "week01" / "intro.pdf"
    await user.open(deck_url(deck_token(intro)))
    (course / "secret.txt").write_text("nope", encoding="utf-8")
    response = await user.http_client.get(f"/ssmedia/{deck_token(intro)}/../../../../secret.txt")
    assert response.status_code == 404


# ---- the registry seen from a running editor ---------------------------


def test_registry_neighbour_order_matches_the_library(course: Path) -> None:
    registry = DeckRegistry(course)
    registry.rescan()
    order = [e.label for e in registry.entries()]
    assert order == [
        "week01/intro",
        "week02/llm_basics",
        "week02/prompting",
    ]


def test_editor_registers_the_deck_it_opens(tmp_path: Path) -> None:
    """Media for a deck opened directly must resolve even with no prior scan."""
    from slidesonnet.gui import app as gui_app

    pdf = _make_deck(tmp_path, "w", "deck")
    registry = DeckRegistry(tmp_path)
    gui_app.set_registry(registry)
    assert registry.resolve(deck_token(pdf)) is None
    registry.register(pdf)
    entry: Any = registry.resolve(deck_token(pdf))
    assert entry is not None and entry.pdf_path == pdf.resolve()
