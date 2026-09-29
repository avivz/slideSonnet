"""Tests for the CLI surface (sty, init, check, tts, export, subs, edit, clean, doctor)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import slidesonnet.clean as clean_mod
from slidesonnet.api import ExportResult
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
    assert "3 generated" in result.output
    assert seen["pdf"] == pdf
    assert seen["engine"] == "kokoro"
    assert seen["only_ids"] == {"a", "b"}


def test_tts_progress_logs_slide_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_synthesize_deck(pdf: Path, **kwargs: Any) -> int:
        kwargs["progress"]("tts", 1, 2, "intro-title")
        return 1

    monkeypatch.setattr("slidesonnet.api.synthesize_deck", fake_synthesize_deck)
    with caplog.at_level(logging.INFO, logger="slidesonnet.cli"):
        result = CliRunner().invoke(main, ["tts", str(_copy_pdf(tmp_path))])
    assert result.exit_code == 0
    assert re.search(r"\[00:00 50%\] 1/1 tts 1/2 · intro-title", caplog.text)


def test_tts_writes_run_log_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_synthesize_deck(pdf: Path, **kwargs: Any) -> int:
        kwargs["progress"]("tts", 1, 1, "intro-title")
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
        kwargs["progress"]("tts", 1, 1, "intro-title")
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


def test_export_prints_overall_progress_and_timing_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Every phase feeds one overall percentage, and the run ends with a timing line."""

    def fake_export(pdf: Path, output: Path, **kwargs: Any) -> ExportResult:
        kwargs["progress"]("tts", 1, 1, "intro-title")
        kwargs["progress"]("video", 1, 2, "intro-title")
        kwargs["progress"]("mux", 10, 10, "")
        return ExportResult(video=output, subtitles=[], duration=10.0, silent=False)

    monkeypatch.setattr("slidesonnet.api.export", fake_export)
    out = tmp_path / "deck.mp4"
    with caplog.at_level(logging.INFO, logger="slidesonnet.cli"):
        result = CliRunner().invoke(main, ["export", str(_copy_pdf(tmp_path)), "-o", str(out)])
    assert result.exit_code == 0
    assert re.search(r"\[00:00 20%\] 1/5 tts 1/1 · intro-title", caplog.text)
    assert re.search(r"\[00:00 50%\] 3/5 video 1/2 · intro-title", caplog.text)
    assert re.search(r"\[00:00 100%\] 5/5 mux 10/10s", caplog.text)
    assert "Timing: tts " in caplog.text


def test_silent_export_plans_only_the_video_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_export(pdf: Path, output: Path, **kwargs: Any) -> ExportResult:
        kwargs["progress"]("video", 2, 2, "")
        return ExportResult(video=output, subtitles=[], duration=5.0, silent=True)

    monkeypatch.setattr("slidesonnet.api.export", fake_export)
    out = tmp_path / "deck.mp4"
    with caplog.at_level(logging.INFO, logger="slidesonnet.cli"):
        result = CliRunner().invoke(
            main, ["export", str(_copy_pdf(tmp_path)), "-o", str(out), "--silent"]
        )
    assert result.exit_code == 0
    assert "[00:00 50%] 1/2 video 2/2" in caplog.text  # video is half of (video, concat)


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
            "--engine",
            "inworld",
            "--allow-estimates",
        ],
    )
    assert result.exit_code == 0
    assert str(out) in result.output
    assert seen["fmt"] == "vtt"
    assert seen["sub_granularity"] == "slide"
    assert seen["timing"] == "estimate"
    # subs must be able to name the engine the audio was rendered with (its cache
    # key embeds the backend), and to opt back into guessed times explicitly.
    assert seen["engine"] == "inworld"
    assert seen["allow_estimates"] is True


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


def _cached_deck(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A deck with no narration and one cheap + one paid clip cached."""
    pdf = _copy_pdf(tmp_path)
    ad = tmp_path / ".slidesonnet" / "audio"
    ad.mkdir(parents=True)
    local, paid = ad / "aaaa.kokoro.bbbb.wav", ad / "cccc.inworld.dddd.mp3"
    local.write_bytes(b"x")
    paid.write_bytes(b"paid")
    return pdf, local, paid


@pytest.mark.parametrize(
    ("args", "answer", "local_gone", "paid_where", "says"),
    [
        (["--keep", "api"], None, True, "kept", "Removed 1 files (0.0 MB), kept 1 paid clip(s)."),
        (["--keep", "nothing"], "n\n", False, "kept", "Aborted"),  # asks before trashing paid
        (["--keep", "nothing", "--yes"], None, True, "trash", "Moved 1 paid/slow clip(s)"),
        (["--keep", "nothing", "--dry-run"], None, False, "kept", "Would move 1 paid"),
    ],
)
def test_clean_trashes_paid_clips_only_when_confirmed(
    tmp_path: Path,
    args: list[str],
    answer: str | None,
    local_gone: bool,
    paid_where: str,
    says: str,
) -> None:
    pdf, local, paid = _cached_deck(tmp_path)
    result = CliRunner().invoke(main, ["clean", str(pdf), *args], input=answer)
    assert says in result.output, result.output
    assert local.exists() != local_gone
    assert paid.exists() == (paid_where == "kept")
    assert (paid.parent / "trash" / paid.name).exists() == (paid_where == "trash")


def test_clean_help_explains_each_keep_level() -> None:
    out = CliRunner().invoke(main, ["clean", "--help"]).output
    assert all(f"{level}:" in out for level in ("api", "current", "exact", "nothing"))
    assert "--dry-run" in out


@pytest.mark.parametrize(
    ("where", "args", "expect_pdf", "expect_root"),
    [
        ("deck", ["--port", "9999", "--app"], "deck", "."),  # the deck's own folder by default
        ("course", [], None, "course"),  # a folder of decks: the library, nothing preselected
        ("deep", ["--root", "."], "deep", "."),  # a deck while browsing a wider tree
        (None, [], None, "."),  # no target: the current folder
    ],
)
def test_edit_resolves_what_to_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    where: str | None,
    args: list[str],
    expect_pdf: str | None,
    expect_root: str,
) -> None:
    import slidesonnet.server.run as server_run

    course = tmp_path / "course"
    course.mkdir()
    deep = tmp_path / "week01"
    deep.mkdir()
    targets = {"deck": _copy_pdf(tmp_path), "course": course, "deep": _copy_pdf(deep)}
    seen: dict[str, Any] = {}
    monkeypatch.setattr(server_run, "run_editor", lambda p=None, **kw: seen.update(kw, pdf_path=p))
    monkeypatch.chdir(tmp_path)
    argv = ["edit", *([str(targets[where])] if where else []), "--no-browser", *args]
    result = CliRunner().invoke(main, [a if a != "." else str(tmp_path) for a in argv])
    assert result.exit_code == 0, result.output
    assert seen["pdf_path"] == (targets[expect_pdf] if expect_pdf else None)
    root = {"course": course.resolve(), ".": tmp_path.resolve()}[expect_root]
    assert seen["root"] == root
    assert seen["open_browser"] is False
    if where == "deck":
        assert seen["port"] == 9999 and seen["app_window"] is True


def test_edit_dev_runs_the_reloading_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import slidesonnet.server.run as server_run

    pdf = _copy_pdf(tmp_path)
    seen: dict[str, Any] = {}
    monkeypatch.setattr(server_run, "run_dev", lambda p, **kw: seen.update(kw, pdf_path=p))
    monkeypatch.setattr(server_run, "run_editor", lambda *a, **kw: seen.update(plain=True))
    result = CliRunner().invoke(main, ["edit", str(pdf), "--dev", "--port", "8123"])
    assert result.exit_code == 0, result.output
    assert seen["pdf_path"] == pdf and seen["port"] == 8123 and "plain" not in seen


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


# ---- shared speech-clip pool ---------------------------------------------------


def test_audio_dir_flag_pins_the_pool_for_the_subcommand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.cache import AUDIO_DIR_ENV

    monkeypatch.delenv(AUDIO_DIR_ENV, raising=False)
    seen: dict[str, str | None] = {}
    real_plan = clean_mod.plan_clean

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(env=os.environ.get(AUDIO_DIR_ENV))
        return real_plan(*args, **kwargs)

    monkeypatch.setattr(clean_mod, "plan_clean", spy)
    pdf = _copy_pdf(tmp_path)
    (tmp_path / ".slidesonnet").mkdir()
    result = CliRunner().invoke(main, ["--audio-dir", str(tmp_path / "pool"), "clean", str(pdf)])
    assert result.exit_code == 0, result.output
    assert seen["env"] == str((tmp_path / "pool").resolve())


def test_clean_says_when_a_pool_was_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _copy_pdf(tmp_path)
    (tmp_path / ".slidesonnet").mkdir()
    monkeypatch.setenv("SLIDESONNET_AUDIO_DIR", str(tmp_path / "pool"))
    result = CliRunner().invoke(main, ["clean", str(pdf), "--keep", "current"])
    assert result.exit_code == 0, result.output
    assert "pool" in result.output and "pool prune" in result.output


def test_pool_status_reports_where_the_pool_comes_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.cache import AUDIO_DIR_ENV

    monkeypatch.delenv(AUDIO_DIR_ENV, raising=False)
    pdf = _copy_pdf(tmp_path)
    pool = tmp_path / "pool"
    pool.mkdir()
    (pool / "aaaa.inworld.bbbb.mp3").write_bytes(b"12345")
    (tmp_path / "slidesonnet.toml").write_text(
        f'[cache]\naudio_dir = "{pool.as_posix()}"\n', encoding="utf-8"
    )
    result = CliRunner().invoke(main, ["pool", "status", str(pdf)])
    assert result.exit_code == 0, result.output
    assert str(pool) in result.output
    assert "slidesonnet.toml" in result.output  # how it was chosen
    assert "inworld" in result.output


def test_pool_prune_is_a_dry_run_unless_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.cache import AUDIO_DIR_ENV
    from slidesonnet.hashing import audio_filename

    monkeypatch.delenv(AUDIO_DIR_ENV, raising=False)
    course = tmp_path / "course"
    deck_dir = course / "01"
    deck_dir.mkdir(parents=True)
    pdf = deck_dir / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    (deck_dir / "marked.narration").write_text(
        simple_narration("@intro-title\nHello.\n"), encoding="utf-8"
    )
    pool = tmp_path / "pool"
    pool.mkdir()
    (course / "slidesonnet.toml").write_text(f'[cache]\naudio_dir = "{pool.as_posix()}"\n')
    (deck_dir / "slidesonnet.toml").write_text(f'[cache]\naudio_dir = "{pool.as_posix()}"\n')
    orphan = pool / audio_filename("Nobody says this.", "inworld", "k")
    orphan.write_bytes(b"paid")

    dry = CliRunner().invoke(main, ["pool", "prune", "--root", str(course)])
    assert dry.exit_code == 0, dry.output
    assert orphan.exists()
    assert "--apply" in dry.output

    applied = CliRunner().invoke(main, ["pool", "prune", "--root", str(course), "--apply"])
    assert applied.exit_code == 0, applied.output
    assert not orphan.exists()
    assert (pool / "trash" / orphan.name).exists()
    assert "trash" in applied.output


def test_pool_prune_of_one_deck_spares_its_folder_siblings(tmp_path: Path) -> None:
    """Without a pool, a folder's decks share .slidesonnet/audio/: naming one deck
    must not orphan the clips of the deck beside it."""
    from slidesonnet.hashing import audio_filename

    pdf = _copy_pdf(tmp_path)
    (tmp_path / "other.pdf").write_bytes(MARKED.read_bytes())
    (tmp_path / "other.narration").write_text(simple_narration("@intro-title\nMine.\n"))
    ad = tmp_path / ".slidesonnet" / "audio"
    ad.mkdir(parents=True)
    sibling = ad / audio_filename("Mine.", "kokoro", "k")
    sibling.write_bytes(b"x")
    result = CliRunner().invoke(main, ["pool", "prune", str(pdf), "--apply"])
    assert result.exit_code == 0, result.output
    assert sibling.exists()


def test_pool_prune_needs_roots_or_decks(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["pool", "prune"])
    assert result.exit_code != 0
    assert "--root" in result.output


def test_pool_migrate_moves_local_caches_into_the_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.cache import AUDIO_DIR_ENV

    monkeypatch.delenv(AUDIO_DIR_ENV, raising=False)
    course = tmp_path / "course"
    pool = tmp_path / "pool"
    pool.mkdir()
    for name in ("01", "02"):
        d = course / name
        d.mkdir(parents=True)
        (d / "marked.pdf").write_bytes(MARKED.read_bytes())
        (d / "marked.narration").write_text(simple_narration("@intro-title\nHello.\n"))
        (d / "slidesonnet.toml").write_text(f'[cache]\naudio_dir = "{pool.as_posix()}"\n')
        local = d / ".slidesonnet" / "audio"
        local.mkdir(parents=True)
        (local / f"{name}aa.inworld.bbbb.mp3").write_bytes(b"paid")
    (pool / "01aa.inworld.bbbb.mp3").write_bytes(b"already")  # pool already has deck 01's clip

    dry = CliRunner().invoke(main, ["pool", "migrate", "--root", str(course)])
    assert dry.exit_code == 0, dry.output
    assert "1 clip(s) to copy" in dry.output and "1 already in pool" in dry.output
    assert (course / "02" / ".slidesonnet" / "audio").exists()

    applied = CliRunner().invoke(main, ["pool", "migrate", "--root", str(course), "--apply"])
    assert applied.exit_code == 0, applied.output
    assert (pool / "02aa.inworld.bbbb.mp3").read_bytes() == b"paid"
    assert (pool / "01aa.inworld.bbbb.mp3").read_bytes() == b"already"  # never overwritten
    assert not (course / "01" / ".slidesonnet" / "audio").exists()
    assert not (course / "02" / ".slidesonnet" / "audio").exists()
    assert "Copied 1 clip(s)" in applied.output


def test_pool_migrate_leaves_decks_without_a_pool_alone(tmp_path: Path) -> None:
    pdf = _copy_pdf(tmp_path)
    (tmp_path / "marked.narration").write_text(simple_narration("@intro-title\nHello.\n"))
    local = tmp_path / ".slidesonnet" / "audio"
    local.mkdir(parents=True)
    (local / "aaaa.kokoro.bbbb.wav").write_bytes(b"x")
    result = CliRunner().invoke(main, ["pool", "migrate", str(pdf), "--apply"])
    assert result.exit_code == 0, result.output
    assert "no pool configured" in result.output
    assert (local / "aaaa.kokoro.bbbb.wav").exists()
