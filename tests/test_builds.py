"""A deck's two builds: ``X.pdf`` (the final build, the one handed out) and, beside it,
``X.plain.pdf`` (the working build every ordinary compile writes). Both belong to deck
X: one narration, one review. The editor and review work on the plain one."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from slidesonnet.builds import deck_pdf, plain_pdf, working_pdf
from slidesonnet.cache import render_dir
from slidesonnet.cli import main
from slidesonnet.deck import default_sidecar_path
from slidesonnet.review import base as review_base
from slidesonnet.review import ops
from slidesonnet.server.library import DeckEntry, discover_decks
from tests.conftest import simple_narration, write_pdf


def _deck(folder: Path, *, final: bool = True, plain: bool = True) -> Path:
    """Deck ``lec`` in *folder*: its narration, and whichever builds are asked for."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "lec.narration").write_text(simple_narration("@a\nHello.\n"), encoding="utf-8")
    if final:
        write_pdf(folder / "lec.pdf", ["a", "b"], final=True)
    if plain:
        write_pdf(folder / "lec.plain.pdf", ["a", "b"], plain=True)
    return folder / "lec.pdf"


def test_the_names_of_a_decks_builds(tmp_path: Path) -> None:
    pdf = tmp_path / "lec.pdf"
    assert deck_pdf(tmp_path / "lec.plain.pdf") == pdf == deck_pdf(pdf)
    assert plain_pdf(pdf) == tmp_path / "lec.plain.pdf" == plain_pdf(plain_pdf(pdf))
    assert working_pdf(pdf) == pdf  # no plain build yet: the deck's own PDF
    _deck(tmp_path)
    assert working_pdf(pdf) == tmp_path / "lec.plain.pdf"


def test_both_builds_share_the_decks_narration_and_review_but_not_renders(
    tmp_path: Path,
) -> None:
    pdf = _deck(tmp_path)
    plain = plain_pdf(pdf)
    assert default_sidecar_path(plain) == tmp_path / "lec.narration"
    assert ops.review_path(plain) == ops.review_path(pdf) == tmp_path / "lec.review"
    assert review_base.base_dir(plain) == review_base.base_dir(pdf)
    # page pictures differ (the final shows page numbers): each build renders its own
    assert render_dir(plain) != render_dir(pdf)


def test_the_library_lists_a_deck_once_and_opens_its_working_build(tmp_path: Path) -> None:
    _deck(tmp_path / "w1")
    _deck(tmp_path / "w2", plain=False)  # never compiled plain: the final is all there is
    decks = discover_decks(tmp_path).decks
    assert [(d.name, d.pdf_path.name) for d in decks] == [
        ("lec", "lec.plain.pdf"),
        ("lec", "lec.pdf"),
    ]
    assert discover_decks(tmp_path).unnarrated == []
    opened = DeckEntry.build(tmp_path / "w1" / "lec.pdf", root=tmp_path)  # `edit lec.pdf`
    assert opened.pdf_path.name == "lec.plain.pdf" and opened.token == decks[0].token


def test_review_commands_given_the_deck_work_on_its_plain_build(tmp_path: Path) -> None:
    """The agent passes ``lec.pdf`` (a final build: review refuses those); with a plain
    build beside it, review compares that one."""
    pdf = _deck(tmp_path)
    result = CliRunner().invoke(main, ["--no-log-file", "review", "snapshot", str(pdf)])
    assert result.exit_code == 0, result.output
    assert ops.review_path(pdf).exists()
