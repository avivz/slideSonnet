"""Tests for the dependency doctor."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import shutil
import subprocess
import sys

import pytest

from slidesonnet.doctor import (
    CheckResult,
    _get_cli_version,
    check_ffmpeg,
    check_inworld_api_key,
    check_nicegui,
    check_pymupdf,
    check_python,
    print_report,
    run_all_checks,
)


def test_python_ok() -> None:
    assert check_python().status == "ok"


def test_pymupdf_detected() -> None:
    # PyMuPDF is a hard dependency, installed in the dev env
    assert check_pymupdf().status == "ok"


def test_run_all_checks_groups() -> None:
    groups = dict(run_all_checks())
    assert "Core (always required)" in groups
    names = {c.name for c in groups["Core (always required)"]}
    assert {"ffmpeg", "ffprobe", "pdftoppm", "PyMuPDF"} <= names
    # marp must be gone from the new toolchain
    all_names = {c.name for _, checks in run_all_checks() for c in checks}
    assert "marp-cli" not in all_names
    # all TTS backends are reported (kokoro/qwen3 free, inworld paid)
    tts_names = {c.name for c in groups["TTS backends (at least one required)"]}
    assert {"kokoro", "qwen-tts", "inworld-tts"} <= tts_names


def test_get_cli_version_missing_command_returns_none() -> None:
    assert _get_cli_version(["definitely-not-a-command-xyz"], r"(\d+)") is None


def test_get_cli_version_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow_run(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=["x"], timeout=5)

    monkeypatch.setattr(subprocess, "run", slow_run)
    assert _get_cli_version(["x", "--version"], r"(\d+)") is None


def test_cli_tool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    result = check_ffmpeg()
    assert result.status == "missing"
    assert result.version == ""
    assert "apt install" in result.hint


def test_cli_tool_unknown_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/ffmpeg")
    monkeypatch.setattr("slidesonnet.doctor._get_cli_version", lambda *a, **kw: None)
    result = check_ffmpeg()
    assert result.status == "ok"
    assert result.version == "unknown"


def test_python_package_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    result = check_nicegui()
    assert result.status == "missing"
    assert result.hint == "pip install nicegui"


def test_python_package_version_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_version(dist: str) -> str:
        raise importlib.metadata.PackageNotFoundError(dist)

    monkeypatch.setattr(importlib.metadata, "version", no_version)
    result = check_nicegui()
    assert result.status == "ok"
    assert result.version == "installed"


def test_inworld_api_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INWORLD_API_KEY", "secret")
    result = check_inworld_api_key()
    assert result.name == "INWORLD_API_KEY"
    assert result.status == "ok"
    assert result.version == "set"


def test_inworld_api_key_missing_without_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "dotenv", None)  # makes `from dotenv import ...` fail
    monkeypatch.delenv("INWORLD_API_KEY", raising=False)
    result = check_inworld_api_key()
    assert result.status == "missing"


def _groups(group: str, *checks: CheckResult) -> list[tuple[str, list[CheckResult]]]:
    return [(group, list(checks))]


def test_print_report_core_missing_fails(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    groups = _groups(
        "Core (always required)",
        CheckResult("ffmpeg", "missing", "", "sudo apt install ffmpeg", "Video compositing"),
        CheckResult("ffprobe", "ok", "6.1", "", "Durations"),
    )
    assert print_report(groups) is False
    out = capsys.readouterr().out
    assert "✗ ffmpeg" in out
    assert "Video compositing" in out  # context shown for the missing tool
    assert "sudo apt install ffmpeg" in out  # hint shown
    assert "✓ ffprobe 6.1" in out
    assert "Missing core dependencies" in out


def test_print_report_optional_missing_still_passes(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    groups = _groups(
        "TTS backends (at least one required)",
        CheckResult("kokoro", "missing", "", "pip install slidesonnet[kokoro]", "Local TTS"),
    )
    assert print_report(groups) is True
    out = capsys.readouterr().out
    assert "— kokoro" in out  # optional deps get a dash, not a cross
    assert "All core dependencies found." in out


def test_print_report_colored_symbols(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    groups = _groups(
        "Core (always required)",
        CheckResult("pdftoppm", "missing", "", "sudo apt install poppler-utils", "Raster"),
    )
    assert print_report(groups) is False
    assert "pdftoppm" in capsys.readouterr().out
