"""How the editor reacts to every reconciliation error, one slide each.

Driven against the committed ``examples/error-showcase`` deck (the same one a
human can open with ``slidesonnet edit``), plus a fabricated PDF for the one
case the LaTeX package can't produce (a page with no marker at all).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from nicegui import ui
from nicegui.testing import User

from slidesonnet.cli import main
from tests.conftest import write_pdf

EXAMPLE = Path(__file__).parent.parent / "examples" / "error-showcase"

pytestmark = pytest.mark.nicegui_main_file("tests/gui_main.py")


def _prep(tmp_path: Path) -> Path:
    """Copy the example deck to tmp so tests never dirty the committed example."""
    pdf = tmp_path / "error-showcase.pdf"
    pdf.write_bytes((EXAMPLE / "error-showcase.pdf").read_bytes())
    (tmp_path / "error-showcase.narration").write_text(
        (EXAMPLE / "error-showcase.narration").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return pdf


def test_example_stays_deliberately_broken() -> None:
    """Guard the example: every advertised finding must keep firing."""
    res = CliRunner().invoke(main, ["check", str(EXAMPLE / "error-showcase.pdf")])
    assert res.exit_code == 1
    assert "renamed to 'twin-2'" in res.output  # duplicate \ssid: disambiguated + warned
    assert "'double-block' has 2 narration blocks" in res.output
    assert "'ghost-slide' has no matching PDF page" in res.output
    assert "auto-generated default" in res.output
    assert "slide 'silent-stage' has no narration block" in res.output


async def test_error_pill_counts_all_errors(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    await user.should_see("⛔ 2 errors")  # double-block, ghost-slide (twin is a warning now)


async def test_clean_slide_shows_no_issues(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    await user.should_see("all-good")
    await user.should_see("no issues on this slide")


async def test_auto_id_slide_warns_in_console(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    user.find(marker="thumb-1").click()  # page 2: the frame without \ssid
    await user.should_see("auto-generated default")
    await user.should_see("no narration block")


async def test_unnarrated_slide_warns_and_reports_no_speech(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    user.find(marker="thumb-2").click()  # page 3: silent-stage
    await user.should_see("no narration block")
    await user.should_see("no speech on this slide")


async def test_duplicate_pdf_id_renames_and_warns_on_both_pages(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    user.find(marker="thumb-3").click()  # page 4: keeps the original 'twin' id
    await user.should_see("appears on several pages")
    user.find(marker="thumb-4").click()  # page 5: renamed to twin-2, narratable
    await user.should_see("renamed to 'twin-2'")
    await user.should_see("twin-2")  # the id label shows the effective id


async def test_duplicate_sidecar_block_errors(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    user.find(marker="thumb-5").click()  # page 6: double-block
    await user.should_see("2 narration blocks")


async def test_orphan_block_lands_in_tray(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    await user.should_see("Unattached narration")
    await user.should_see("@ghost-slide")


async def test_freeze_shows_persistent_header_pill(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While duplicate blocks freeze saving, the header must say so persistently."""
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    await user.should_see("not saving — duplicate blocks")


async def test_no_freeze_pill_on_healthy_deck(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = write_pdf(tmp_path / "deck.pdf", ["alpha"])
    (tmp_path / "deck.narration").write_text("@alpha\nHi.\n", encoding="utf-8")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("Slide 1 / 1")
    await user.should_not_see("not saving")


# ---- player behavior on broken slides ---------------------------------------


async def test_play_on_speechless_slide_says_so_instead_of_building(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Playing a slide with nothing to say must explain, not render silence."""
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    user.find(marker="thumb-2").click()  # silent-stage: no narration at all
    user.find(marker="play-slide").click()
    await user.should_see("no narration to play", retries=300)


@pytest.mark.integration
async def test_play_on_duplicate_id_slide_still_previews(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ambiguous id is an error, but hearing its narration must still work."""
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    user.find(marker="thumb-3").click()  # first twin
    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=600)


@pytest.mark.integration
async def test_deck_preview_works_despite_all_errors(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole-deck preview must survive empty pages, twins, and orphans."""
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    user.find(marker="play-deck").click()
    await user.should_see("Preview ready", retries=600)


# ---- the one case LaTeX can't produce: a page with no marker at all ----------


async def test_unmarked_page_disables_editing_with_hint(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No slide-id means no sidecar key: the editor must not eat typed text."""
    pdf = write_pdf(tmp_path / "deck.pdf", ["alpha", "", "beta"])
    (tmp_path / "deck.narration").write_text("@alpha\nHi.\n", encoding="utf-8")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    user.find("Next").click()  # onto the unmarked page
    await user.should_see("no slide-id marker")
    body = next(iter(user.find(ui.textarea).elements))
    assert isinstance(body, ui.textarea)
    assert not body.enabled  # typing here could never be saved — don't pretend
    # navigating onward re-enables editing
    user.find("Next").click()
    assert body.enabled
