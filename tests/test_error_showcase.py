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
from tests.conftest import simple_narration, write_pdf

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
    assert "'double-block' has more than one narration block" in res.output  # disambiguated
    assert "renamed to 'double-block-2'" in res.output  # the dup block's text is kept
    assert "'ghost-slide' has no matching PDF page" in res.output
    assert "auto-generated default" in res.output
    assert "slide 'silent-stage' has no narration block" in res.output


async def test_error_pill_counts_all_errors(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    # two orphans: ghost-slide and double-block-2 (the disambiguated dup block).
    # duplicate \ssid and duplicate @block are warnings now, not errors.
    await user.should_see("⛔ 2 errors")


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


async def test_duplicate_sidecar_block_self_heals_in_editor(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duplicate @block is auto-disambiguated: the slide keeps the first block,
    the second lands in the tray, and nothing freezes (the warning is in `check`)."""
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    user.find(marker="thumb-5").click()  # page 6: double-block, narratable
    await user.should_see("I am the first of two blocks")
    await user.should_see("@double-block-2")  # the second block, disambiguated into the tray


async def test_orphan_block_lands_in_tray(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    await user.should_see("Unattached narration")
    await user.should_see("@ghost-slide")
    # the disambiguated duplicate block also surfaces here instead of being lost
    await user.should_see("@double-block-2")
    # the full narration text is shown (not truncated), so it stays readable
    await user.should_see("no longer exists in the PDF")
    # and it can be folded back into the open slide
    user.find(marker="append-ghost-slide")


async def test_append_orphan_folds_text_into_current_slide(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tray's 'Append here' button merges an orphan onto the open slide."""
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    await user.should_see("all-good")  # the control slide is open
    user.find(marker="append-ghost-slide").click()
    await user.should_see("Appended")
    sidecar = (tmp_path / "error-showcase.narration").read_text(encoding="utf-8")
    assert "@ghost-slide" not in sidecar  # the orphan is gone
    assert "no longer exists in the PDF" in sidecar  # its text now lives on all-good


async def test_control_slide_editable_despite_duplicate_blocks(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duplicate @block elsewhere must not freeze editing on a healthy slide."""
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    await user.should_see("all-good")  # the control slide opens first
    text = next(iter(user.find(marker="utext-0").elements))
    assert isinstance(text, ui.textarea) and text.enabled


# ---- player behavior on broken slides ---------------------------------------


async def test_play_and_generate_disabled_on_speechless_slide(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slide with nothing to say can't be played, and offers nothing to generate."""
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(_prep(tmp_path)))
    await user.open("/")
    user.find(marker="thumb-2").click()  # silent-stage: no narration at all
    await user.should_see("no speech on this slide")
    play = next(iter(user.find(marker="play-slide").elements))
    assert isinstance(play, ui.button)
    assert not play.enabled
    # no utterance cards → no per-line generate buttons on this slide
    await user.should_not_see(marker="gen-seg-0")


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
    """No slide-id means no sidecar key: the editor shows a hint, not edit fields."""
    pdf = write_pdf(tmp_path / "deck.pdf", ["alpha", "", "beta"])
    (tmp_path / "deck.narration").write_text(simple_narration("@alpha\nHi.\n"), encoding="utf-8")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    user.find(ui.textarea)  # alpha has an editable utterance card
    user.find("Next").click()  # onto the unmarked page
    await user.should_see("no slide-id marker")  # a hint, not an edit field
    # the add-line button is disabled (can't add narration to a keyless page)
    add = next(iter(user.find(marker="add-utterance").elements))
    assert isinstance(add, ui.button) and not add.enabled
