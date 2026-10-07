"""``slidesonnet review …`` — the command line the agent (and you) drive review with."""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest
from click.testing import CliRunner, Result

from slidesonnet.cli import main
from slidesonnet.review import ops
from tests.conftest import simple_narration, write_pdf


@pytest.fixture
def deck(tmp_path: Path) -> Path:
    pdf = write_pdf(tmp_path / "deck.pdf", ["intro", "proof"])
    (tmp_path / "deck.narration").write_text(simple_narration("@intro\nHello.\n"), encoding="utf-8")
    return pdf


def _run(*args: str) -> str:
    result = CliRunner().invoke(main, ["--no-log-file", "review", *args], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.output


def _fail(*args: str) -> str:
    result = CliRunner().invoke(main, ["--no-log-file", "review", *args])
    assert result.exit_code != 0
    return result.output


def test_snapshot_then_clean_status(deck: Path) -> None:
    assert "2 slides" in _run("snapshot", str(deck))
    out = _run("status", str(deck))
    assert "No changes" in out


def test_comment_reply_list_json(deck: Path) -> None:
    out = _run("comment", str(deck), "@proof", "-m", "Too wordy.", "--as", "author")
    assert "c1" in out
    _run("reply", str(deck), "c1", "Shortened.", "--add-slides", "@intro")
    data = json.loads(_run("list", str(deck), "--json"))
    conv = next(c for c in data["conversations"] if c["id"] == "c1")
    assert conv["slides"] == ["proof", "intro"]
    assert conv["turn"] == "author"
    assert [m["author"] for m in conv["messages"]] == ["author", "agent"]
    assert "page body" in conv["pages"]["proof"]["current_text"]


def test_conversations_take_a_title(deck: Path) -> None:
    _run("comment", str(deck), "@proof", "-m", "Too wordy.", "--title", "Wordy proof")
    _run("reply", str(deck), "c1", "Shortened.", "--title", "Shorter proof")
    assert "Shorter proof" in _run("list", str(deck))
    _run("title", str(deck), "c1", "Proof, two lines")
    convs = json.loads(_run("list", str(deck), "--json"))["conversations"]
    conv = next(c for c in convs if c["id"] == "c1")
    assert conv["title"] == "Proof, two lines" and len(conv["messages"]) == 2


def test_status_json_reports_changes_and_unfiled(deck: Path) -> None:
    _run("snapshot", str(deck))
    doc = pymupdf.open(deck)
    doc[1].insert_text((20, 150), "An edit", fontsize=14)
    doc.saveIncr()
    doc.close()
    data = json.loads(_run("status", str(deck), "--json"))
    (change,) = data["changes"]
    assert change["id"] == "proof" and change["kinds"] == ["edited"] and change["image"]
    assert data["unfiled"] == ["proof"]
    assert data["final_build"] is False


def test_list_filters(deck: Path) -> None:
    _run("comment", str(deck), "@proof", "-m", "one", "--as", "author")
    _run("comment", str(deck), "@intro", "-m", "two", "--as", "author")
    _run("reply", str(deck), "c2", "done")
    _run("accept", str(deck), "c2")
    mine = json.loads(_run("list", str(deck), "--json", "--mine"))
    assert [c["id"] for c in mine["conversations"]] == ["c1"]  # agent's turn, open
    default = json.loads(_run("list", str(deck), "--json"))
    assert "c2" not in [c["id"] for c in default["conversations"]]  # closed: hidden
    every = json.loads(_run("list", str(deck), "--json", "--all"))
    assert "c2" in [c["id"] for c in every["conversations"]]


def test_deck_conversation(deck: Path) -> None:
    _run("reply", str(deck), "deck", "Publish these.", "--as", "author")
    _run("reply", str(deck), "deck", "Done.")
    out = _run("list", str(deck))
    assert "Publish these." in out and "Done." in out


def test_accept_reopen_clear(deck: Path) -> None:
    _run("comment", str(deck), "@proof", "-m", "x", "--as", "author")
    _run("accept", str(deck), "c1")
    assert "Cleared 1" in _run("clear", str(deck))
    assert ops.load(deck).slide_conversations() == []


def test_show_base(deck: Path) -> None:
    _run("snapshot", str(deck))
    data = json.loads(_run("show", str(deck), "@intro", "--base", "--json"))
    assert "Hello." in data["narration"]
    assert Path(data["image"]).exists()
    assert json.loads(_run("show", str(deck), "@intro", "--json")) == data  # --base is optional


def test_narration_override_is_the_reviewed_sidecar(deck: Path) -> None:
    alt = deck.with_name("alt.narration")
    alt.write_text(simple_narration("@intro\nOther.\n"), encoding="utf-8")
    over = ("--narration", str(alt))
    _run("list", str(deck), *over)  # the first use takes the base from the override
    assert "Other." in json.loads(_run("show", str(deck), "@intro", "--json"))["narration"]
    assert "No changes" in _run("status", str(deck), *over)
    assert "No changes" not in _run("status", str(deck))  # deck.narration says "Hello."
    _run("snapshot", str(deck))
    assert "No changes" not in _run("status", str(deck), *over)
    assert "Nothing to clear" in _run("clear", str(deck), *over)
    assert "does not exist" in _fail("status", str(deck), "--narration", "typo.narration")


def test_send_and_wait(deck: Path) -> None:
    _run("comment", str(deck), "@proof", "-m", "x", "--as", "author")
    _run("send", str(deck))
    data = json.loads(_run("wait", str(deck), "--since", "0", "--json", "--timeout", "1"))
    assert data["cursor"] == 1 and [c["id"] for c in data["awaiting_agent"]] == ["c1"]


def test_wait_timeout_exits_3_not_the_usage_error_code(deck: Path) -> None:
    result = CliRunner().invoke(
        main, ["--no-log-file", "review", "wait", str(deck), "--since", "0", "--timeout", "0.1"]
    )
    assert result.exit_code == 3
    assert "exit code 3" in CliRunner().invoke(main, ["review", "wait", "--help"]).output


def test_errors_are_clean(deck: Path) -> None:
    assert "no conversation" in _fail("reply", str(deck), "c7", "hi")


def test_reply_accepts_dash_m_like_comment(deck: Path) -> None:
    _run("snapshot", str(deck))
    _run("reply", str(deck), "deck", "-m", "Publish these.", "--as", "author")
    assert ops.load(deck).conversations["deck"].messages[-1].text == "Publish these."


def test_reply_needs_text(deck: Path) -> None:
    _run("snapshot", str(deck))
    assert "text" in _fail("reply", str(deck), "deck").lower()


def test_comment_on_deck_points_to_reply(deck: Path) -> None:
    _run("snapshot", str(deck))
    out = _fail("comment", str(deck), "deck", "-m", "Publish these.")
    assert "review reply" in out


def test_declaring_an_uncompiled_slide_notes_it(deck: Path) -> None:
    _run("snapshot", str(deck))
    out = _run("comment", str(deck), "@proof", "@proof-2", "-m", "Splitting the proof.")
    assert "@proof-2" in out and "not in the PDF yet" in out
    status = _run("status", str(deck))
    assert "Not in the PDF yet" in status and "@proof-2" in status
    data = json.loads(_run("status", str(deck), "--json"))
    assert data["pending"] == {"proof-2": ["c1"]}


# ---- one listener for a whole course ----------------------------------------------


def _course(root: Path, *names: str) -> dict[str, Path]:
    """One deck per folder (``root/a/a.pdf`` …), the way a course lays them out."""
    decks = {}
    for name in names:
        (root / name).mkdir()
        decks[name] = write_pdf(root / name / f"{name}.pdf", ["s1"])
        (root / name / f"{name}.narration").write_text(simple_narration("@s1\nHi.\n"))
    return decks


def _author_sends(pdf: Path) -> None:
    ops.comment(pdf, ["s1"], "Have a look.", author="author")
    ops.send(pdf)


def _wait(*args: str) -> Result:
    return CliRunner().invoke(main, ["--no-log-file", "review", "wait", *args])


def test_wait_under_a_root_hears_a_send_in_any_deck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decks = _course(tmp_path, "a", "b")
    _author_sends(decks["b"])
    data = json.loads(_run("wait", "--root", str(tmp_path), "--json", "--timeout", "1"))
    assert [Path(d["pdf"]).name for d in data["decks"]] == ["b.pdf"]
    assert [c["id"] for c in data["decks"][0]["awaiting_agent"]] == ["c1"]
    cursor = data["cursor"]
    assert _wait("--root", str(tmp_path), "--since", cursor, "--timeout", "0.1").exit_code == 3
    _author_sends(decks["a"])
    monkeypatch.chdir(tmp_path)  # --root defaults to the current directory
    out = _run("wait", "--since", cursor, "--timeout", "1").splitlines()
    assert out[:2] == ["a/a.pdf", "  c1  @s1"]
    assert out[-1].startswith("cursor ") and out[-1] != f"cursor {cursor}"
    assert len(out) == 3  # deck b had nothing new


def test_wait_on_several_pdfs_watches_exactly_those(tmp_path: Path) -> None:
    decks = _course(tmp_path, "a", "b", "c")
    _author_sends(decks["c"])
    watched = [str(decks["a"]), str(decks["b"])]
    assert _wait(*watched, "--timeout", "0.1").exit_code == 3
    _author_sends(decks["b"])
    data = json.loads(_run("wait", *watched, "--json", "--timeout", "1"))
    assert [Path(d["pdf"]).name for d in data["decks"]] == ["b.pdf"]


def test_wait_keeps_the_two_kinds_of_cursor_apart(deck: Path, tmp_path: Path) -> None:
    for args in (
        [str(deck), "--since", "d:0123abcd=1"],  # a course cursor for one deck
        ["--root", str(tmp_path), "--since", "3"],  # a one-deck cursor for a course
        ["--root", str(tmp_path), "--since", "nonsense"],
        [str(deck), "--root", str(tmp_path)],
    ):
        result = _wait(*args, "--timeout", "0.1")
        assert result.exit_code == 2, (args, result.output)


def test_wait_says_when_the_scan_was_cut_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.server import library

    monkeypatch.setattr(library, "DEFAULT_LIMITS", library.ScanLimits(max_dirs=1))
    write_pdf(tmp_path / "top.pdf", ["s1"])
    (tmp_path / "top.narration").write_text(simple_narration("@s1\nHi.\n"))
    _course(tmp_path, "deeper")
    _author_sends(tmp_path / "top.pdf")
    result = _wait("--root", str(tmp_path), "--json", "--timeout", "1")
    assert result.exit_code == 0, result.output
    assert "stopped" in result.stderr  # …but still watches the decks it found
    assert [Path(d["pdf"]).name for d in json.loads(result.stdout)["decks"]] == ["top.pdf"]
