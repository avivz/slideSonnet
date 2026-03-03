"""Tests for the doctor module."""

from __future__ import annotations

import re
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from slidesonnet.cli import main
from slidesonnet.doctor import (
    CheckResult,
    _get_cli_version,
    check_api_key,
    check_elevenlabs,
    check_ffmpeg,
    check_ffprobe,
    check_marp,
    check_pdflatex,
    check_pdftoppm,
    check_piper,
    check_python,
    print_report,
)


# ---- _get_cli_version ----


def test_get_cli_version_found():
    with patch("slidesonnet.doctor.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="ffmpeg version 6.1.1\n", stderr="")
        result = _get_cli_version(["ffmpeg", "-version"], r"version\s+(\S+)")
        assert result == "6.1.1"


def test_get_cli_version_not_found():
    with patch("slidesonnet.doctor.subprocess.run", side_effect=FileNotFoundError):
        result = _get_cli_version(["nonexistent", "--version"], r"(\S+)")
        assert result is None


def test_get_cli_version_timeout():
    with patch(
        "slidesonnet.doctor.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)
    ):
        result = _get_cli_version(["slow-cmd"], r"(\S+)")
        assert result is None


def test_get_cli_version_stderr():
    with patch("slidesonnet.doctor.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="pdftoppm version 24.03.0\n")
        result = _get_cli_version(["pdftoppm", "-v"], r"version\s+(\S+)", stderr=True)
        assert result == "24.03.0"


def test_get_cli_version_no_match_returns_first_line():
    with patch("slidesonnet.doctor.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="marp 4.2.3\n", stderr="")
        result = _get_cli_version(["marp", "--version"], r"(nomatch)")
        assert result == "marp 4.2.3"


# ---- check_python ----


def test_check_python_ok():
    result = check_python()
    assert result.status == "ok"
    assert result.name == "python"
    assert result.version != ""


# ---- check_ffmpeg ----


def test_check_ffmpeg_found():
    with (
        patch("slidesonnet.doctor.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("slidesonnet.doctor.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(stdout="ffmpeg version 6.1\n", stderr="")
        result = check_ffmpeg()
        assert result.status == "ok"
        assert result.version == "6.1"


def test_check_ffmpeg_missing():
    with patch("slidesonnet.doctor.shutil.which", return_value=None):
        result = check_ffmpeg()
        assert result.status == "missing"
        assert "apt install ffmpeg" in result.hint


# ---- check_ffprobe ----


def test_check_ffprobe_found():
    with (
        patch("slidesonnet.doctor.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("slidesonnet.doctor.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(stdout="ffprobe version 6.1\n", stderr="")
        result = check_ffprobe()
        assert result.status == "ok"
        assert result.version == "6.1"


def test_check_ffprobe_missing():
    with patch("slidesonnet.doctor.shutil.which", return_value=None):
        result = check_ffprobe()
        assert result.status == "missing"
        assert "apt install ffmpeg" in result.hint


# ---- check_marp ----


def test_check_marp_found():
    with (
        patch("slidesonnet.doctor.shutil.which", return_value="/usr/bin/marp"),
        patch("slidesonnet.doctor.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(stdout="4.2.3\n", stderr="")
        result = check_marp()
        assert result.status == "ok"
        assert result.name == "marp-cli"


def test_check_marp_missing():
    with patch("slidesonnet.doctor.shutil.which", return_value=None):
        result = check_marp()
        assert result.status == "missing"
        assert "npm install" in result.hint


# ---- check_pdflatex ----


def test_check_pdflatex_found():
    with (
        patch("slidesonnet.doctor.shutil.which", return_value="/usr/bin/pdflatex"),
        patch("slidesonnet.doctor.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(stdout="pdfTeX 3.14 (TeX Live 2024)\n", stderr="")
        result = check_pdflatex()
        assert result.status == "ok"
        assert "TeX Live 2024" in result.version


def test_check_pdflatex_missing():
    with patch("slidesonnet.doctor.shutil.which", return_value=None):
        result = check_pdflatex()
        assert result.status == "missing"
        assert "texlive" in result.hint


# ---- check_pdftoppm ----


def test_check_pdftoppm_found():
    with (
        patch("slidesonnet.doctor.shutil.which", return_value="/usr/bin/pdftoppm"),
        patch("slidesonnet.doctor.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(stdout="", stderr="pdftoppm version 24.03.0\n")
        result = check_pdftoppm()
        assert result.status == "ok"
        assert result.version == "24.03.0"


def test_check_pdftoppm_missing():
    with patch("slidesonnet.doctor.shutil.which", return_value=None):
        result = check_pdftoppm()
        assert result.status == "missing"
        assert "poppler" in result.hint


# ---- check_piper ----


def test_check_piper_found_in_path():
    with (
        patch("slidesonnet.doctor.shutil.which", return_value="/usr/bin/piper"),
        patch("slidesonnet.doctor.importlib.metadata.version", return_value="1.4.1"),
    ):
        result = check_piper()
        assert result.status == "ok"
        assert result.version == "1.4.1"


def test_check_piper_found_in_venv():
    with (
        patch("slidesonnet.doctor.shutil.which", return_value=None),
        patch("slidesonnet.doctor.os.path.isfile", return_value=True),
        patch("slidesonnet.doctor.importlib.metadata.version", return_value="1.4.1"),
    ):
        result = check_piper()
        assert result.status == "ok"


def test_check_piper_missing():
    with (
        patch("slidesonnet.doctor.shutil.which", return_value=None),
        patch("slidesonnet.doctor.os.path.isfile", return_value=False),
    ):
        result = check_piper()
        assert result.status == "missing"
        assert "piper" in result.hint


def test_check_piper_no_package_metadata():
    """Piper binary found but piper-tts package not installed."""
    with (
        patch("slidesonnet.doctor.shutil.which", return_value="/usr/bin/piper"),
        patch(
            "slidesonnet.doctor.importlib.metadata.version",
            side_effect=__import__(
                "importlib.metadata", fromlist=["PackageNotFoundError"]
            ).PackageNotFoundError,
        ),
    ):
        result = check_piper()
        assert result.status == "ok"
        assert result.version == "installed"


# ---- check_elevenlabs ----


def test_check_elevenlabs_found():
    with patch("slidesonnet.doctor.importlib.metadata.version", return_value="1.20.0"):
        result = check_elevenlabs()
        assert result.status == "ok"
        assert result.version == "1.20.0"


def test_check_elevenlabs_missing():
    with patch(
        "slidesonnet.doctor.importlib.metadata.version",
        side_effect=__import__(
            "importlib.metadata", fromlist=["PackageNotFoundError"]
        ).PackageNotFoundError,
    ):
        result = check_elevenlabs()
        assert result.status == "missing"
        assert "elevenlabs" in result.hint


# ---- check_api_key ----


def test_check_api_key_set(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test-key")
    result = check_api_key()
    assert result.status == "ok"


def test_check_api_key_unset(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with patch("dotenv.load_dotenv"):
        result = check_api_key()
        assert result.status == "missing"
        assert ".env" in result.hint


# ---- print_report ----


def test_print_report_all_ok():
    groups = [
        ("Python", [CheckResult("python", "ok", "3.13.1", "", "Runtime")]),
        (
            "Core (always required)",
            [
                CheckResult("ffmpeg", "ok", "6.1", "", "Video compositing"),
                CheckResult("ffprobe", "ok", "6.1", "", "Duration detection"),
            ],
        ),
    ]
    result = print_report(groups)
    assert result is True


def test_print_report_core_missing():
    groups = [
        ("Python", [CheckResult("python", "ok", "3.13.1", "", "Runtime")]),
        (
            "Core (always required)",
            [
                CheckResult(
                    "ffmpeg", "missing", "", "sudo apt install ffmpeg", "Video compositing"
                ),
                CheckResult("ffprobe", "ok", "6.1", "", "Duration detection"),
            ],
        ),
    ]
    result = print_report(groups)
    assert result is False


def test_print_report_optional_missing_still_ok():
    """Missing optional tools don't affect the return value."""
    groups = [
        ("Python", [CheckResult("python", "ok", "3.13.1", "", "Runtime")]),
        (
            "Core (always required)",
            [
                CheckResult("ffmpeg", "ok", "6.1", "", "Video compositing"),
                CheckResult("ffprobe", "ok", "6.1", "", "Duration detection"),
            ],
        ),
        (
            "TTS backends (at least one required)",
            [CheckResult("piper", "missing", "", "pip install piper-tts", "Local TTS")],
        ),
    ]
    result = print_report(groups)
    assert result is True


# ---- CLI wiring ----


@pytest.fixture
def runner():
    return CliRunner()


def test_doctor_cli_ok(runner):
    groups = [
        ("Python", [CheckResult("python", "ok", "3.13.1", "", "Runtime")]),
        (
            "Core (always required)",
            [
                CheckResult("ffmpeg", "ok", "6.1", "", ""),
                CheckResult("ffprobe", "ok", "6.1", "", ""),
            ],
        ),
    ]
    with patch("slidesonnet.doctor.run_all_checks", return_value=groups):
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0
        assert "All core dependencies found" in result.output


def test_doctor_cli_fail(runner):
    groups = [
        ("Python", [CheckResult("python", "ok", "3.13.1", "", "Runtime")]),
        (
            "Core (always required)",
            [
                CheckResult("ffmpeg", "missing", "", "sudo apt install ffmpeg", ""),
                CheckResult("ffprobe", "ok", "6.1", "", ""),
            ],
        ),
    ]
    with patch("slidesonnet.doctor.run_all_checks", return_value=groups):
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 1
        assert "Missing core dependencies" in result.output


def test_doctor_in_help(runner):
    result = runner.invoke(main, ["--help"])
    assert "doctor" in result.output


# ---- Version regex regression tests ----
# Validate that regexes match real version strings from different platforms
# without calling any subprocess.


@pytest.mark.parametrize(
    "output, expected",
    [
        # Ubuntu 24.04
        (
            "ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023 the FFmpeg developers",
            "6.1.1-3ubuntu5",
        ),
        # macOS Homebrew
        ("ffmpeg version 7.0.1 Copyright (c) 2000-2024 the FFmpeg developers", "7.0.1"),
        # Arch / rolling
        ("ffmpeg version n6.1.1 Copyright (c) 2000-2023 the FFmpeg developers", "n6.1.1"),
    ],
)
def test_ffmpeg_version_regex(output, expected):
    m = re.search(r"version\s+(\S+)", output)
    assert m is not None
    assert m.group(1) == expected


@pytest.mark.parametrize(
    "output, expected",
    [
        (
            "ffprobe version 6.1.1-3ubuntu5 Copyright (c) 2007-2023 the FFmpeg developers",
            "6.1.1-3ubuntu5",
        ),
        ("ffprobe version 7.0.1 Copyright (c) 2007-2024 the FFmpeg developers", "7.0.1"),
    ],
)
def test_ffprobe_version_regex(output, expected):
    m = re.search(r"version\s+(\S+)", output)
    assert m is not None
    assert m.group(1) == expected


@pytest.mark.parametrize(
    "output, expected",
    [
        ("@marp-team/marp-cli v4.2.3 (w/ @marp-team/marp-core v4.2.0)", "v4.2.3"),
        ("@marp-team/marp-cli v3.4.0 (w/ @marp-team/marp-core v3.11.4)", "v3.4.0"),
    ],
)
def test_marp_version_regex(output, expected):
    m = re.search(r"v(\d+\.\d+\.\d+)", output)
    assert m is not None
    assert f"v{m.group(1)}" == expected


@pytest.mark.parametrize(
    "output, expected",
    [
        ("pdfTeX 3.141592653-2.6-1.40.25 (TeX Live 2023/Debian)", "TeX Live 2023/Debian"),
        ("pdfTeX 3.141592653-2.6-1.40.26 (TeX Live 2024)", "TeX Live 2024"),
    ],
)
def test_pdflatex_version_regex(output, expected):
    m = re.search(r"\((.+?)\)", output)
    assert m is not None
    assert m.group(1) == expected


@pytest.mark.parametrize(
    "output, expected",
    [
        ("pdftoppm version 24.02.0", "24.02.0"),
        ("pdftoppm version 22.12.0", "22.12.0"),
        ("pdftoppm version 0.86.1", "0.86.1"),
    ],
)
def test_pdftoppm_version_regex(output, expected):
    m = re.search(r"version\s+(\S+)", output)
    assert m is not None
    assert m.group(1) == expected
