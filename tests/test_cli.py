"""Tests for the CLI surface (sty, init, check, tts, export, subs, edit, clean, doctor)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from slidesonnet.api import ExportResult
from slidesonnet.clean import CleanResult
from slidesonnet.cli import main
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.logging_setup import (
    _ConsoleFormatter,
    configure_console_logging,
    resolve_console_level,
)
from tests.conftest import simple_narration

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def test_version() -> None:
    import slidesonnet

    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert slidesonnet.__version__ in result.output


def test_sty_writes_macro(tmp_path: Path) -> None:
    out = tmp_path / "slidesonnet.sty"
    result = CliRunner().invoke(main, ["sty", "-o", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    assert "\\ssid" in out.read_text(encoding="utf-8")


def test_init_scaffolds_sidecar(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    result = CliRunner().invoke(main, ["init", str(pdf)])
    assert result.exit_code == 0
    sidecar = tmp_path / "marked.narration"
    assert sidecar.exists()
    text = sidecar.read_text(encoding="utf-8")
    assert "@intro-title" in text
    assert "# page 1" in text


def test_init_refuses_overwrite(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    runner = CliRunner()
    runner.invoke(main, ["init", str(pdf)])
    result = runner.invoke(main, ["init", str(pdf)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_init_merge_tops_up(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    sidecar = tmp_path / "marked.narration"
    sidecar.write_text(simple_narration("@intro-title\nHello.\n"), encoding="utf-8")
    result = CliRunner().invoke(main, ["init", str(pdf), "--merge"])
    assert result.exit_code == 0
    text = sidecar.read_text(encoding="utf-8")
    assert "Hello." in text  # existing untouched
    assert "@euler-setup" in text  # missing id added


def test_check_reports_missing(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    result = CliRunner().invoke(main, ["check", str(pdf)])
    # un-narrated pages -> warnings, but no errors -> exit 0
    assert result.exit_code == 0
    assert "warning" in result.output.lower()


def test_check_errors_on_orphan(tmp_path: Path) -> None:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    sidecar = tmp_path / "marked.narration"
    sidecar.write_text(simple_narration("@ghost\nNobody.\n"), encoding="utf-8")
    result = CliRunner().invoke(main, ["check", str(pdf)])
    assert result.exit_code == 1
    assert "ghost" in result.output and "no matching" in result.output.lower()


def test_doctor_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub the checks: the real ones probe external tools and run load_dotenv
    # (which would pull the developer's .env into the test process).
    from slidesonnet.doctor import CheckResult

    ok = CheckResult("ffmpeg", "ok", "7.0", "", "")
    monkeypatch.setattr("slidesonnet.doctor.run_all_checks", lambda: [("Core", [ok])])
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 0
    assert "ffmpeg" in result.output


def test_unknown_command_suggests() -> None:
    result = CliRunner().invoke(main, ["chekc", "x"])
    assert result.exit_code != 0
    assert "check" in result.output


def test_unknown_command_without_close_match() -> None:
    result = CliRunner().invoke(main, ["zzzqqq"])
    assert result.exit_code != 0
    assert "No such command" in result.output
    assert "Did you mean" not in result.output


def test_no_subcommand_prints_help() -> None:
    result = CliRunner().invoke(main, [])
    assert result.exit_code == 0
    assert "Workflow:" in result.output


def test_cli_formatter_prefixes_warnings_only() -> None:
    fmt = _ConsoleFormatter()
    warn = logging.LogRecord("x", logging.WARNING, __file__, 1, "careful", None, None)
    info = logging.LogRecord("x", logging.INFO, __file__, 1, "progress", None, None)
    assert fmt.format(warn) == "WARNING: careful"
    assert fmt.format(info) == "progress"


def test_configure_logging_installs_handler_and_quiet_level() -> None:
    configure_console_logging(resolve_console_level(quiet=True))
    consoles = [
        h for h in logging.getLogger().handlers if getattr(h, "name", "") == "slidesonnet-console"
    ]
    assert len(consoles) == 1
    assert consoles[0].level == logging.WARNING
    assert isinstance(consoles[0].formatter, _ConsoleFormatter)


def _copy_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    return pdf


def test_init_quiet_suppresses_path(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["--quiet", "init", str(_copy_pdf(tmp_path))])
    assert result.exit_code == 0
    assert result.output.strip() == ""
    assert (tmp_path / "marked.narration").exists()


def test_init_reports_slidesonnet_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Path:
        raise SlideSonnetError("sidecar exploded")

    monkeypatch.setattr("slidesonnet.api.init_sidecar", boom)
    result = CliRunner().invoke(main, ["init", str(_copy_pdf(tmp_path))])
    assert result.exit_code != 0
    assert "sidecar exploded" in result.output


def test_check_reports_slidesonnet_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> list[Any]:
        raise SlideSonnetError("unreadable deck")

    monkeypatch.setattr("slidesonnet.api.check_deck", boom)
    result = CliRunner().invoke(main, ["check", str(_copy_pdf(tmp_path))])
    assert result.exit_code != 0
    assert "unreadable deck" in result.output


def test_check_ok_when_no_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("slidesonnet.api.check_deck", lambda *a, **kw: [])
    result = CliRunner().invoke(main, ["check", str(_copy_pdf(tmp_path))])
    assert result.exit_code == 0
    assert "OK — no issues." in result.output


def test_tts_passes_engine_and_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_synthesize_deck(pdf: Path, **kwargs: Any) -> int:
        seen.update(kwargs, pdf=pdf)
        return 3

    monkeypatch.setattr("slidesonnet.api.synthesize_deck", fake_synthesize_deck)
    pdf = _copy_pdf(tmp_path)
    result = CliRunner().invoke(
        main, ["tts", str(pdf), "--engine", "kokoro", "--id", "a", "--id", "b"]
    )
    assert result.exit_code == 0
    assert "Synthesized 3 new clip(s)" in result.output
    assert seen["pdf"] == pdf
    assert seen["engine"] == "kokoro"
    assert seen["only_ids"] == {"a", "b"}


def test_tts_progress_logs_slide_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_synthesize_deck(pdf: Path, **kwargs: Any) -> int:
        kwargs["progress"]("intro-title", 1, 2)
        return 1

    monkeypatch.setattr("slidesonnet.api.synthesize_deck", fake_synthesize_deck)
    with caplog.at_level(logging.INFO, logger="slidesonnet.cli"):
        result = CliRunner().invoke(main, ["tts", str(_copy_pdf(tmp_path))])
    assert result.exit_code == 0
    assert "[1/2] intro-title" in caplog.text


def test_tts_writes_run_log_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_synthesize_deck(pdf: Path, **kwargs: Any) -> int:
        kwargs["progress"]("intro-title", 1, 1)
        return 1

    monkeypatch.setattr("slidesonnet.api.synthesize_deck", fake_synthesize_deck)
    pdf = _copy_pdf(tmp_path)
    result = CliRunner().invoke(main, ["tts", str(pdf)])
    assert result.exit_code == 0
    log = tmp_path / ".slidesonnet" / "slidesonnet.log"
    assert log.exists()
    assert "intro-title" in log.read_text(encoding="utf-8")


def test_no_log_file_skips_run_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("slidesonnet.api.synthesize_deck", lambda pdf, **kw: 0)
    pdf = _copy_pdf(tmp_path)
    result = CliRunner().invoke(main, ["--no-log-file", "tts", str(pdf)])
    assert result.exit_code == 0
    assert not (tmp_path / ".slidesonnet" / "slidesonnet.log").exists()


def test_log_file_override_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_synthesize_deck(pdf: Path, **kwargs: Any) -> int:
        kwargs["progress"]("intro-title", 1, 1)
        return 1

    monkeypatch.setattr("slidesonnet.api.synthesize_deck", fake_synthesize_deck)
    pdf = _copy_pdf(tmp_path)
    custom = tmp_path / "elsewhere" / "run.log"
    result = CliRunner().invoke(main, ["--log-file", str(custom), "tts", str(pdf)])
    assert result.exit_code == 0
    assert custom.exists()
    assert not (tmp_path / ".slidesonnet" / "slidesonnet.log").exists()


def test_quiet_and_verbose_conflict(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["--quiet", "--verbose", "init", str(_copy_pdf(tmp_path))])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_tts_reports_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> int:
        raise SlideSonnetError("no narration")

    monkeypatch.setattr("slidesonnet.api.synthesize_deck", boom)
    result = CliRunner().invoke(main, ["tts", str(_copy_pdf(tmp_path))])
    assert result.exit_code != 0
    assert "no narration" in result.output


def test_export_passes_options_and_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    out = tmp_path / "deck.mp4"

    def fake_export(pdf: Path, output: Path, **kwargs: Any) -> ExportResult:
        seen.update(kwargs, pdf=pdf, output=output)
        return ExportResult(
            video=output, subtitles=[output.with_suffix(".srt")], duration=12.34, silent=False
        )

    monkeypatch.setattr("slidesonnet.api.export", fake_export)
    pdf = _copy_pdf(tmp_path)
    result = CliRunner().invoke(
        main,
        ["export", str(pdf), "-o", str(out), "--timing", "fixed:3", "--subtitles", "both"],
    )
    assert result.exit_code == 0
    assert "Built deck.mp4 (12.3s) + deck.srt" in result.output
    assert seen["output"] == out
    assert seen["timing"] == "fixed:3"
    assert seen["subtitles"] == "both"
    assert seen["silent"] is False


def test_export_silent_reports_silent_no_subs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_export(pdf: Path, output: Path, **kwargs: Any) -> ExportResult:
        assert kwargs["silent"] is True
        return ExportResult(video=output, subtitles=[], duration=5.0, silent=True)

    monkeypatch.setattr("slidesonnet.api.export", fake_export)
    out = tmp_path / "deck.mp4"
    result = CliRunner().invoke(
        main, ["export", str(_copy_pdf(tmp_path)), "-o", str(out), "--silent"]
    )
    assert result.exit_code == 0
    assert "Built deck.mp4 (silent 5.0s)" in result.output
    assert "+" not in result.output


def test_export_reports_value_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> ExportResult:
        raise ValueError("invalid timing spec 'fixed:'")

    monkeypatch.setattr("slidesonnet.api.export", boom)
    result = CliRunner().invoke(
        main, ["export", str(_copy_pdf(tmp_path)), "-o", str(tmp_path / "x.mp4")]
    )
    assert result.exit_code != 0
    assert "invalid timing spec" in result.output


def test_subs_passes_options_and_prints_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    out = tmp_path / "deck.vtt"

    def fake_write_subs(pdf: Path, output: Path, **kwargs: Any) -> Path:
        seen.update(kwargs, output=output)
        return output

    monkeypatch.setattr("slidesonnet.api.write_subs", fake_write_subs)
    result = CliRunner().invoke(
        main,
        [
            "subs",
            str(_copy_pdf(tmp_path)),
            "-o",
            str(out),
            "--format",
            "vtt",
            "--sub-granularity",
            "slide",
            "--timing",
            "estimate",
        ],
    )
    assert result.exit_code == 0
    assert str(out) in result.output
    assert seen["fmt"] == "vtt"
    assert seen["sub_granularity"] == "slide"
    assert seen["timing"] == "estimate"


def test_subs_reports_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Path:
        raise SlideSonnetError("bad sidecar")

    monkeypatch.setattr("slidesonnet.api.write_subs", boom)
    result = CliRunner().invoke(
        main, ["subs", str(_copy_pdf(tmp_path)), "-o", str(tmp_path / "x.srt")]
    )
    assert result.exit_code != 0
    assert "bad sidecar" in result.output


def test_clean_without_cache(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["clean", str(_copy_pdf(tmp_path))])
    assert result.exit_code == 0
    assert "Nothing to clean." in result.output


def test_clean_reports_removed_and_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _copy_pdf(tmp_path)
    (tmp_path / ".slidesonnet").mkdir()
    monkeypatch.setattr(
        "slidesonnet.clean.clean",
        lambda p, keep: CleanResult(removed_files=3, removed_bytes=2 * 1024 * 1024, kept_files=2),
    )
    result = CliRunner().invoke(main, ["clean", str(pdf), "--keep", "current"])
    assert result.exit_code == 0
    assert "Removed 3 files (2.0 MB), kept 2" in result.output


def test_clean_nothing_to_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _copy_pdf(tmp_path)
    (tmp_path / ".slidesonnet").mkdir()
    monkeypatch.setattr("slidesonnet.clean.clean", lambda p, keep: CleanResult())
    result = CliRunner().invoke(main, ["clean", str(pdf)])
    assert result.exit_code == 0
    assert "Nothing to remove." in result.output


def test_clean_keep_nothing_prompts_and_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _copy_pdf(tmp_path)
    (tmp_path / ".slidesonnet").mkdir()
    called = False

    def fake_clean(p: Path, keep: str) -> CleanResult:
        nonlocal called
        called = True
        return CleanResult()

    monkeypatch.setattr("slidesonnet.clean.clean", fake_clean)
    result = CliRunner().invoke(main, ["clean", str(pdf), "--keep", "nothing"], input="n\n")
    assert result.exit_code != 0
    assert "Aborted" in result.output
    assert called is False


def test_clean_keep_nothing_yes_skips_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _copy_pdf(tmp_path)
    (tmp_path / ".slidesonnet").mkdir()
    seen: dict[str, str] = {}

    def fake_clean(p: Path, keep: str) -> CleanResult:
        seen["keep"] = keep
        return CleanResult(removed_files=1, removed_bytes=10, kept_files=0)

    monkeypatch.setattr("slidesonnet.clean.clean", fake_clean)
    result = CliRunner().invoke(main, ["clean", str(pdf), "--keep", "nothing", "--yes"])
    assert result.exit_code == 0
    assert seen["keep"] == "nothing"
    assert "Removed 1 files" in result.output


def test_edit_invokes_run_editor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import slidesonnet.gui.app as gui_app

    pdf = _copy_pdf(tmp_path)
    seen: dict[str, Any] = {}

    def fake_run_editor(pdf_path: Path, **kwargs: Any) -> None:
        seen.update(kwargs, pdf_path=pdf_path)

    monkeypatch.setattr(gui_app, "run_editor", fake_run_editor)
    result = CliRunner().invoke(main, ["edit", str(pdf), "--no-browser", "--port", "9999", "--app"])
    assert result.exit_code == 0
    assert seen["pdf_path"] == pdf
    assert seen["port"] == 9999
    assert seen["open_browser"] is False
    assert seen["app_window"] is True


def test_edit_scans_the_decks_own_folder_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import slidesonnet.gui.app as gui_app

    pdf = _copy_pdf(tmp_path)
    seen: dict[str, Any] = {}
    monkeypatch.setattr(gui_app, "run_editor", lambda p=None, **kw: seen.update(kw, pdf_path=p))
    result = CliRunner().invoke(main, ["edit", str(pdf), "--no-browser"])
    assert result.exit_code == 0
    assert seen["pdf_path"] == pdf
    assert seen["root"] == tmp_path.resolve()


def test_edit_accepts_a_folder_of_decks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`edit <dir>` opens the library for that tree with no deck preselected."""
    import slidesonnet.gui.app as gui_app

    course = tmp_path / "course"
    course.mkdir()
    seen: dict[str, Any] = {}
    monkeypatch.setattr(gui_app, "run_editor", lambda p=None, **kw: seen.update(kw, pdf_path=p))
    result = CliRunner().invoke(main, ["edit", str(course), "--no-browser"])
    assert result.exit_code == 0
    assert seen["pdf_path"] is None
    assert seen["root"] == course.resolve()


def test_edit_root_overrides_the_scanned_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deck can be opened while browsing a wider tree."""
    import slidesonnet.gui.app as gui_app

    deep = tmp_path / "week01"
    deep.mkdir()
    pdf = _copy_pdf(deep)
    seen: dict[str, Any] = {}
    monkeypatch.setattr(gui_app, "run_editor", lambda p=None, **kw: seen.update(kw, pdf_path=p))
    result = CliRunner().invoke(main, ["edit", str(pdf), "--root", str(tmp_path), "--no-browser"])
    assert result.exit_code == 0
    assert seen["pdf_path"] == pdf
    assert seen["root"] == tmp_path.resolve()


def test_edit_with_no_target_scans_the_current_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import slidesonnet.gui.app as gui_app

    seen: dict[str, Any] = {}
    monkeypatch.setattr(gui_app, "run_editor", lambda p=None, **kw: seen.update(kw, pdf_path=p))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["edit", "--no-browser"])
    assert result.exit_code == 0
    assert seen["pdf_path"] is None
    assert seen["root"] == tmp_path.resolve()


def test_edit_dev_execs_devserver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import slidesonnet.gui.app as gui_app
    import slidesonnet.gui.launch as gui_launch

    pdf = _copy_pdf(tmp_path)
    argv = [sys.executable, "-m", "slidesonnet.gui.devserver"]
    extra_env = {"SLIDESONNET_DEV_PDF": str(pdf)}
    monkeypatch.setattr(gui_launch, "dev_invocation", lambda *a, **kw: (argv, extra_env))
    execve_calls: list[tuple[str, list[str], dict[str, str]]] = []
    monkeypatch.setattr(
        os, "execve", lambda path, args, env: execve_calls.append((path, args, env))
    )
    # The fake execve returns (the real one never does), so stub run_editor too.
    monkeypatch.setattr(gui_app, "run_editor", lambda *a, **kw: None)

    result = CliRunner().invoke(main, ["edit", str(pdf), "--dev"])
    assert result.exit_code == 0
    path, args, env = execve_calls[0]
    assert path == sys.executable
    assert args == argv
    assert env["SLIDESONNET_DEV_PDF"] == str(pdf)


def test_doctor_exits_nonzero_when_core_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from slidesonnet.doctor import CheckResult

    groups = [
        (
            "Core (always required)",
            [CheckResult("ffmpeg", "missing", "", "sudo apt install ffmpeg", "Video")],
        )
    ]
    monkeypatch.setattr("slidesonnet.doctor.run_all_checks", lambda: groups)
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 1
    assert "Missing core dependencies" in result.output
