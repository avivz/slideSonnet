"""Tests for the M0 CLI surface (sty, init, check, doctor)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from slidesonnet.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def test_version() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "1.0.0a0" in result.output


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
    sidecar.write_text("@intro-title\nHello.\n", encoding="utf-8")
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
    sidecar.write_text("@ghost\nNobody.\n", encoding="utf-8")
    result = CliRunner().invoke(main, ["check", str(pdf)])
    assert result.exit_code == 1
    assert "ghost" in result.output and "no matching" in result.output.lower()


def test_doctor_runs() -> None:
    result = CliRunner().invoke(main, ["doctor"])
    assert "ffmpeg" in result.output


def test_unknown_command_suggests() -> None:
    result = CliRunner().invoke(main, ["chekc", "x"])
    assert result.exit_code != 0
    assert "check" in result.output
