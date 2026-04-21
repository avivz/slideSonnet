"""Dependency checker for slideSonnet external tools."""

from __future__ import annotations

import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Literal

import click


@dataclass
class CheckResult:
    """Result of checking a single dependency."""

    name: str
    status: Literal["ok", "missing"]
    version: str  # "" if missing
    hint: str  # install command when missing
    context: str  # when is this needed


def _get_cli_version(
    cmd: list[str], pattern: str, *, stderr: bool = False, timeout: float = 5.0
) -> str | None:
    """Run *cmd*, match *pattern* against output, return first capture group or None."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        text = result.stderr if stderr else result.stdout
        first_line = text.strip().split("\n", 1)[0]
        m = re.search(pattern, first_line)
        return m.group(1) if m else first_line.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


@dataclass(frozen=True)
class ToolCheck:
    """Definition of a CLI-tool dependency check.

    The doctor runs each declaration to produce a :class:`CheckResult`.
    Keeping these as data rather than one function per tool means adding
    a new dependency is a one-line change.
    """

    name: str
    command: str  # binary looked up via shutil.which
    hint: str
    context: str
    version_args: list[str] = field(default_factory=list)  # e.g. ["-version"]
    version_pattern: str = ""  # regex with one capture group
    version_on_stderr: bool = False


_CLI_CHECKS: list[ToolCheck] = [
    ToolCheck(
        name="ffmpeg",
        command="ffmpeg",
        hint="sudo apt install ffmpeg",
        context="Video compositing",
        version_args=["-version"],
        version_pattern=r"version\s+(\S+)",
    ),
    ToolCheck(
        name="ffprobe",
        command="ffprobe",
        hint="sudo apt install ffmpeg",
        context="Audio/video duration detection",
        version_args=["-version"],
        version_pattern=r"version\s+(\S+)",
    ),
    ToolCheck(
        name="marp-cli",
        command="marp",
        hint="npm install -g @marp-team/marp-cli",
        context="MARP slide rendering",
        version_args=["--version"],
        version_pattern=r"v(\d+\.\d+\.\d+)",
    ),
    ToolCheck(
        name="pdflatex",
        command="pdflatex",
        hint="sudo apt install texlive-latex-base",
        context="Beamer slide compilation",
        version_args=["--version"],
        version_pattern=r"\((.+?)\)",
    ),
    ToolCheck(
        name="pdftoppm",
        command="pdftoppm",
        hint="sudo apt install poppler-utils",
        context="PDF to image conversion",
        version_args=["-v"],
        version_pattern=r"version\s+(\S+)",
        version_on_stderr=True,
    ),
    ToolCheck(
        name="pdfunite",
        command="pdfunite",
        hint="sudo apt install poppler-utils",
        context="PDF concatenation",
        version_args=["-v"],
        version_pattern=r"version\s+(\S+)",
        version_on_stderr=True,
    ),
]

_CHECKS_BY_NAME: dict[str, ToolCheck] = {c.name: c for c in _CLI_CHECKS}


def _run_cli_check(check: ToolCheck) -> CheckResult:
    """Run a single declarative CLI check."""
    if not shutil.which(check.command):
        return CheckResult(check.name, "missing", "", check.hint, check.context)
    version = (
        _get_cli_version(
            [check.command, *check.version_args],
            check.version_pattern,
            stderr=check.version_on_stderr,
        )
        or "unknown"
    )
    return CheckResult(check.name, "ok", version, "", check.context)


def check_python() -> CheckResult:
    """Check Python version."""
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 13)
    return CheckResult(
        name="python",
        status="ok" if ok else "missing",
        version=version,
        hint="Requires Python 3.13+",
        context="Runtime",
    )


def check_ffmpeg() -> CheckResult:
    """Check for ffmpeg."""
    return _run_cli_check(_CHECKS_BY_NAME["ffmpeg"])


def check_ffprobe() -> CheckResult:
    """Check for ffprobe."""
    return _run_cli_check(_CHECKS_BY_NAME["ffprobe"])


def check_marp() -> CheckResult:
    """Check for marp-cli."""
    return _run_cli_check(_CHECKS_BY_NAME["marp-cli"])


def check_pdflatex() -> CheckResult:
    """Check for pdflatex."""
    return _run_cli_check(_CHECKS_BY_NAME["pdflatex"])


def check_pdftoppm() -> CheckResult:
    """Check for pdftoppm."""
    return _run_cli_check(_CHECKS_BY_NAME["pdftoppm"])


def check_pdfunite() -> CheckResult:
    """Check for pdfunite."""
    return _run_cli_check(_CHECKS_BY_NAME["pdfunite"])


def check_piper() -> CheckResult:
    """Check for piper TTS (PATH or venv fallback)."""
    found = shutil.which("piper")
    if not found:
        venv_piper = os.path.join(os.path.dirname(sys.executable), "piper")
        if os.path.isfile(venv_piper):
            found = venv_piper
    if not found:
        return CheckResult(
            "piper", "missing", "", "pip install slidesonnet[piper]", "Local TTS (free)"
        )
    try:
        version = importlib.metadata.version("piper-tts")
    except importlib.metadata.PackageNotFoundError:
        version = "installed"
    return CheckResult("piper", "ok", version, "", "Local TTS (free)")


def check_elevenlabs() -> CheckResult:
    """Check for elevenlabs Python package."""
    try:
        version = importlib.metadata.version("elevenlabs")
    except importlib.metadata.PackageNotFoundError:
        return CheckResult(
            "elevenlabs",
            "missing",
            "",
            "pip install slidesonnet[elevenlabs]",
            "Cloud TTS (paid)",
        )
    return CheckResult("elevenlabs", "ok", version, "", "Cloud TTS (paid)")


def check_api_key() -> CheckResult:
    """Check for ELEVENLABS_API_KEY in environment or .env."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return CheckResult("ELEVENLABS_API_KEY", "ok", "set", "", "Only needed for elevenlabs TTS")
    return CheckResult(
        "ELEVENLABS_API_KEY",
        "missing",
        "",
        "Add to .env or export in shell",
        "Only needed for elevenlabs TTS",
    )


def run_all_checks() -> list[tuple[str, list[CheckResult]]]:
    """Run all checks and return named groups of results."""
    return [
        ("Python", [check_python()]),
        ("Core (always required)", [check_ffmpeg(), check_ffprobe()]),
        ("MARP toolchain (for .md slides)", [check_marp()]),
        (
            "Beamer toolchain (for .tex slides)",
            [check_pdflatex(), check_pdftoppm(), check_pdfunite()],
        ),
        ("TTS backends (at least one required)", [check_piper(), check_elevenlabs()]),
        ("API keys", [check_api_key()]),
    ]


# Groups whose failures affect the exit code.
_CORE_GROUPS = {"Python", "Core (always required)"}


def print_report(groups: list[tuple[str, list[CheckResult]]]) -> bool:
    """Print a formatted report and return True if all core deps are OK."""
    use_color = "NO_COLOR" not in os.environ
    all_core_ok = True
    for group_name, checks in groups:
        is_core = group_name in _CORE_GROUPS
        click.echo(f"\n{group_name}")
        for check in checks:
            if check.status == "ok":
                symbol = click.style("\u2713", fg="green") if use_color else "\u2713"
                line = f"  {symbol} {check.name} {check.version}"
            elif is_core:
                symbol = click.style("\u2717", fg="red") if use_color else "\u2717"
                line = f"  {symbol} {check.name}"
                all_core_ok = False
            else:
                symbol = click.style("\u2014", fg="yellow") if use_color else "\u2014"
                line = f"  {symbol} {check.name}"
            # Append context for non-ok items
            if check.status != "ok" and check.context:
                line += f"    {check.context}"
            click.echo(line)
            if check.status != "ok" and check.hint:
                click.echo(f"    {check.hint}")

    click.echo()
    if all_core_ok:
        msg = "All core dependencies found."
        click.echo(click.style(msg, fg="green") if use_color else msg)
    else:
        msg = "Missing core dependencies \u2014 see above."
        click.echo(click.style(msg, fg="red") if use_color else msg)
    return all_core_ok
