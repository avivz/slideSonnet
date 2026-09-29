"""First-run CLI behaviour: one error boundary, plain messages, and refusals that say
what went wrong and how to fix it (init → check → tts → export → subs)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from slidesonnet import api
from slidesonnet.cli import main
from slidesonnet.exceptions import ExportRefused
from tests.conftest import prep_marked_deck, write_pdf

NARRATED = "@intro-title\nHello there.\n"


def _run(*args: str, input: str | None = None) -> Result:
    return CliRunner().invoke(main, ["--no-log-file", *args], input=input)


def _one_line_error(result: Result, *needles: str) -> None:
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    for n in needles:
        assert n in result.output, result.output


def _sidecar(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "marked.narration"
    path.write_text(body, encoding="utf-8")
    return path


# ---- one error boundary --------------------------------------------------------


def test_latex_source_instead_of_pdf(tmp_path: Path) -> None:
    tex = tmp_path / "deck.tex"
    tex.write_text("\\documentclass{beamer}", encoding="utf-8")
    _one_line_error(_run("check", str(tex)), "deck.tex is LaTeX source", "compiled PDF")


def test_non_pdf_file(tmp_path: Path) -> None:
    junk = tmp_path / "deck.pdf"
    junk.write_text("not a pdf", encoding="utf-8")
    _one_line_error(_run("check", str(junk)), "deck.pdf", "isn't a PDF")


def test_sty_into_missing_folder(tmp_path: Path) -> None:
    _one_line_error(_run("sty", "-o", str(tmp_path / "nope" / "x.sty")), "x.sty", "folder")


def test_verbose_adds_the_traceback(tmp_path: Path) -> None:
    result = _run("-v", "sty", "-o", str(tmp_path / "nope" / "x.sty"))
    assert result.exit_code != 0
    assert "Traceback" in result.output


def test_bad_config_value_is_one_line(tmp_path: Path) -> None:
    pdf = prep_marked_deck(tmp_path)
    (tmp_path / "slidesonnet.toml").write_text("[video]\nfps = 0\n", encoding="utf-8")
    result = CliRunner().invoke(main, ["check", str(pdf)])  # with the run log attached
    _one_line_error(result, "slidesonnet.toml", "fps")


def test_clean_errors_are_one_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from slidesonnet.exceptions import SlideSonnetError

    pdf = prep_marked_deck(tmp_path)
    (tmp_path / ".slidesonnet").mkdir()

    def boom(*_a: Any, **_k: Any) -> None:
        raise SlideSonnetError("cache is locked")

    monkeypatch.setattr("slidesonnet.clean.clean", boom)
    _one_line_error(_run("clean", str(pdf)), "cache is locked")


def test_programmer_errors_are_not_dressed_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bug(*_a: Any, **_k: Any) -> None:
        raise ValueError("an internal bug")

    monkeypatch.setattr("slidesonnet.api.check_deck", bug)
    result = _run("check", str(prep_marked_deck(tmp_path)))
    assert isinstance(result.exception, ValueError)


@pytest.mark.parametrize("cmd", ["export", "subs"])
def test_bad_timing_is_a_usage_error(tmp_path: Path, cmd: str) -> None:
    pdf = prep_marked_deck(tmp_path, NARRATED)
    out = tmp_path / ("x.mp4" if cmd == "export" else "x.srt")
    result = _run(cmd, str(pdf), "-o", str(out), "--timing", "fixed:")
    _one_line_error(result, "invalid timing spec")


# ---- init ----------------------------------------------------------------------


def test_init_scaffold_teaches_the_v1_grammar(tmp_path: Path) -> None:
    pdf = prep_marked_deck(tmp_path)
    result = _run("init", str(pdf))
    assert result.exit_code == 0, result.output
    text = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "[pause" not in text
    assert "#   utterance:" in text and "#     text:" in text and "#   pause:" in text
    assert "slidesonnet edit" in result.output  # the next step
    api.check_deck(pdf)  # the commented example parses


def test_init_refusal_names_the_flags(tmp_path: Path) -> None:
    pdf = prep_marked_deck(tmp_path, NARRATED)
    _one_line_error(_run("init", str(pdf)), "--merge", "--force")


# ---- decks with no \ssid, missing sidecars --------------------------------------


@pytest.mark.parametrize("cmd", ["init", "check"])
def test_pdf_without_any_ssid(tmp_path: Path, cmd: str) -> None:
    pdf = write_pdf(tmp_path / "deck.pdf", ["", ""])
    result = _run(cmd, str(pdf))
    assert result.exit_code != 0
    assert "slidesonnet sty" in result.output
    assert "\\usepackage{slidesonnet}" in result.output


@pytest.mark.parametrize("cmd", ["check", "tts", "export", "subs"])
def test_explicit_missing_narration_is_an_error(tmp_path: Path, cmd: str) -> None:
    pdf = prep_marked_deck(tmp_path)
    args = [cmd, str(pdf), "--narration", str(tmp_path / "typo.narration")]
    if cmd in {"export", "subs"}:
        args += ["-o", str(tmp_path / ("x.mp4" if cmd == "export" else "x.srt"))]
    _one_line_error(_run(*args), "typo.narration", "not found")


# ---- check ---------------------------------------------------------------------


def test_check_warns_a_plain_build_needs_draft(tmp_path: Path) -> None:
    pdf = write_pdf(tmp_path / "deck.pdf", ["a"], plain=True)
    (tmp_path / "deck.narration").write_text("@a\n  utterance:\n    text: Hi.\n")
    result = _run("check", str(pdf))
    assert result.exit_code == 0, result.output
    assert "--draft" in result.output and "ssfinal" in result.output


@pytest.mark.parametrize(
    ("voice", "ok"),
    [("nobody", False), ("af_hart", False), ("af_heart", True), ("narrator", True)],
)
def test_check_validates_voices(tmp_path: Path, voice: str, ok: bool) -> None:
    pdf = prep_marked_deck(tmp_path)
    _sidecar(
        tmp_path,
        "voices:\n  narrator:\n    kokoro: am_echo\n\n"
        f"@intro-title\n  utterance:\n    voice: {voice}\n    text: Hi.\n",
    )
    result = _run("check", str(pdf))
    assert (result.exit_code == 0) is ok, result.output
    if not ok:
        assert f"'{voice}'" in result.output and "kokoro voice" in result.output
    if voice == "af_hart":
        assert "af_heart" in result.output  # a close-match suggestion


def test_check_reports_a_duplicate_block_with_both_lines(tmp_path: Path) -> None:
    pdf = prep_marked_deck(tmp_path)
    _sidecar(
        tmp_path,
        "@intro-title\n  utterance:\n    text: One.\n\n@intro-title\n  utterance:\n    text: Two.\n",
    )
    result = _run("check", str(pdf))
    assert result.exit_code == 1
    assert "intro-title-2" not in result.output
    assert "more than one" in result.output and "lines 1 and 5" in result.output


def test_sidecar_syntax_error_names_the_file(tmp_path: Path) -> None:
    pdf = prep_marked_deck(tmp_path)
    _sidecar(tmp_path, "@intro-title\n  bogus line here\n")
    _one_line_error(_run("check", str(pdf)), "marked.narration", "line 2")


# ---- export refusals -----------------------------------------------------------


class _Reached(Exception):
    """Raised by a stubbed synthesizer: export got past its checks."""


@pytest.fixture
def stub_synth(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise _Reached

    monkeypatch.setattr("slidesonnet.audio.synth.synthesize", boom)


@pytest.mark.parametrize(
    ("sidecar", "why"),
    [
        ("", "no slide has narration"),
        ("@a\n  utterance:\n    text: Hi.\n@ghost\n  utterance:\n    text: Boo.\n", "ghost"),
    ],
)
def test_export_refuses_a_broken_deck_unless_draft(
    tmp_path: Path, stub_synth: None, sidecar: str, why: str
) -> None:
    pdf = write_pdf(tmp_path / "deck.pdf", ["a", "b"], final=True)
    if sidecar:
        (tmp_path / "deck.narration").write_text(sidecar, encoding="utf-8")
    with pytest.raises(ExportRefused, match=why):
        api.export(pdf, tmp_path / "deck.mp4")
    with pytest.raises(_Reached):
        api.export(pdf, tmp_path / "deck.mp4", draft=True)


def test_export_refuses_non_mp4_up_front(tmp_path: Path) -> None:
    pdf = prep_marked_deck(tmp_path, NARRATED)
    _one_line_error(_run("export", str(pdf), "-o", str(tmp_path / "x.webm")), ".mp4")
    assert not (tmp_path / "x.webm").exists()


# ---- tts and subs messages -----------------------------------------------------


@pytest.mark.parametrize(
    ("ids", "needles"),
    [
        (["nosuch"], ["Unknown slide-id 'nosuch'"]),
        (["intro-titel"], ["Unknown slide-id 'intro-titel'", "intro-title"]),
    ],
)
def test_tts_unknown_id(tmp_path: Path, ids: list[str], needles: list[str]) -> None:
    pdf = prep_marked_deck(tmp_path, NARRATED)
    args = [a for i in ids for a in ("--id", i)]
    result = _run("tts", str(pdf), *args)
    assert result.exit_code == 1
    _one_line_error(result, *needles)


def test_tts_summary_counts_generated_and_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = prep_marked_deck(tmp_path, "@intro-title\nOne. [pause 1] Two.\n")

    def fake_synth(*_a: Any, **_k: Any) -> dict[tuple[str, int], Any]:
        from slidesonnet.audio.synth import SynthResult

        return {
            ("intro-title", 0): SynthResult(tmp_path / "a.wav", 1.0, from_cache=False),
            ("intro-title", 1): SynthResult(tmp_path / "b.wav", 1.0, from_cache=True),
        }

    monkeypatch.setattr("slidesonnet.audio.synth.synthesize", fake_synth)
    result = _run("tts", str(pdf))
    assert result.exit_code == 0, result.output
    assert "1 generated, 1 reused" in result.output


@pytest.mark.parametrize(
    ("out", "flag", "fmt"),
    [
        ("x.vtt", None, "vtt"),
        ("x.srt", None, "srt"),
        ("x.txt", "vtt", "vtt"),
        ("x.vtt", "srt", None),
    ],
)
def test_subs_format_follows_the_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, out: str, flag: str | None, fmt: str | None
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "slidesonnet.api.write_subs", lambda pdf, output, **kw: seen.update(kw) or output
    )
    pdf = prep_marked_deck(tmp_path, NARRATED)
    result = _run(
        "subs", str(pdf), "-o", str(tmp_path / out), *(["--format", flag] if flag else [])
    )
    if fmt is None:
        _one_line_error(result, "--format srt", ".vtt")
    else:
        assert result.exit_code == 0, result.output
        assert seen["fmt"] == fmt


# ---- paid synthesis asks first ---------------------------------------------------


@pytest.fixture
def paid_deck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    """A narrated deck whose synthesis is stubbed; records whether it would run."""
    calls: list[str] = []

    def fake_synth(*_a: Any, **_k: Any) -> dict[tuple[str, int], Any]:
        calls.append("synth")
        raise _Reached

    monkeypatch.setattr("slidesonnet.audio.synth.synthesize", fake_synth)
    pdf = write_pdf(tmp_path / "deck.pdf", ["a"], final=True)
    (tmp_path / "deck.narration").write_text("@a\n  utterance:\n    text: Hi.\n")
    return pdf, calls


def _paid_args(cmd: str, pdf: Path) -> list[str]:
    out = ["-o", str(pdf.with_suffix(".mp4"))] if cmd == "export" else []
    return [cmd, str(pdf), *out, "--engine", "inworld"]


@pytest.mark.parametrize("cmd", ["tts", "export"])
@pytest.mark.parametrize(
    ("tty", "extra", "answer", "runs"),
    [
        (False, [], None, False),  # no terminal, no --yes: refuse
        (False, ["--yes"], None, True),
        (True, [], "n\n", False),
        (True, [], "y\n", True),
    ],
)
def test_paid_synthesis_asks_first(
    monkeypatch: pytest.MonkeyPatch,
    paid_deck: tuple[Path, list[str]],
    cmd: str,
    tty: bool,
    extra: list[str],
    answer: str | None,
    runs: bool,
) -> None:
    pdf, calls = paid_deck
    monkeypatch.setattr("slidesonnet.cli._stdin_is_tty", lambda: tty)
    result = _run(*_paid_args(cmd, pdf), *extra, input=answer)
    assert result.exit_code != 0  # the stub stops every run
    assert bool(calls) is runs, result.output
    assert "1 new clip" in result.output or extra
    if not tty and not extra:
        assert "--yes" in result.output


def test_free_engine_never_asks(paid_deck: tuple[Path, list[str]]) -> None:
    pdf, calls = paid_deck
    _run("tts", str(pdf), "--engine", "kokoro")
    assert calls == ["synth"]


# ---- help text -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "absent"),
    [(["edit", "--help"], "NiceGUI"), (["review", "--help"], "\\b")],
)
def test_help_text_is_clean(args: list[str], absent: str) -> None:
    result = _run(*args)
    assert result.exit_code == 0
    assert absent not in result.output


def test_top_level_help_lists_commands_once() -> None:
    result = _run("--help")
    assert result.output.count("Commands:") == 1
    assert "--draft" in result.output  # the workflow reaches a video that works
