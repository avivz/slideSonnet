"""Dependency checker for the slideSonnet narration editor."""

from __future__ import annotations

import importlib.metadata
import importlib.util
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        text = result.stderr if stderr else result.stdout
        first_line = text.strip().split("\n", 1)[0]
        m = re.search(pattern, first_line)
        return m.group(1) if m else first_line.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


@dataclass(frozen=True)
class ToolCheck:
    """Declarative CLI-tool dependency check."""

    name: str
    command: str
    hint: str
    context: str
    version_args: list[str] = field(default_factory=list)
    version_pattern: str = ""
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
        name="pdftoppm",
        command="pdftoppm",
        hint="sudo apt install poppler-utils",
        context="PDF to image rasterization",
        version_args=["-v"],
        version_pattern=r"version\s+(\S+)",
        version_on_stderr=True,
    ),
    ToolCheck(
        name="latexmk",
        command="latexmk",
        hint="sudo apt install latexmk",
        context="Compiling your Beamer deck (your job, not the tool's)",
        version_args=["--version"],
        version_pattern=r"Version\s+(\S+)",
    ),
    ToolCheck(
        name="pdflatex",
        command="pdflatex",
        hint="sudo apt install texlive-latex-base",
        context="LaTeX engine invoked by latexmk",
        version_args=["--version"],
        version_pattern=r"\((.+?)\)",
    ),
]

_CHECKS_BY_NAME: dict[str, ToolCheck] = {c.name: c for c in _CLI_CHECKS}


def _run_cli_check(check: ToolCheck) -> CheckResult:
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
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 12)
    return CheckResult(
        "python", "ok" if ok else "missing", version, "Requires Python 3.12+", "Runtime"
    )


def _check_python_package(dist: str, import_name: str, hint: str, context: str) -> CheckResult:
    if importlib.util.find_spec(import_name) is None:
        return CheckResult(dist, "missing", "", hint, context)
    try:
        version = importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        version = "installed"
    return CheckResult(dist, "ok", version, "", context)


def check_pymupdf() -> CheckResult:
    return _check_python_package(
        "PyMuPDF", "fitz", "pip install pymupdf", "PDF slide-id extraction"
    )


def check_nicegui() -> CheckResult:
    return _check_python_package("nicegui", "nicegui", "pip install nicegui", "GUI editor")


def check_kokoro() -> CheckResult:
    return _check_python_package(
        "kokoro", "kokoro", "pip install slidesonnet[kokoro]", "Local TTS (free)"
    )


def check_elevenlabs() -> CheckResult:
    return _check_python_package(
        "elevenlabs", "elevenlabs", "pip install slidesonnet[elevenlabs]", "Cloud TTS (paid)"
    )


def check_qwen3() -> CheckResult:
    return _check_python_package(
        "qwen-tts", "qwen_tts", "pip install slidesonnet[qwen3]", "Local own-voice TTS (free)"
    )


def check_api_key() -> CheckResult:
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
        "Only for elevenlabs TTS",
    )


def run_all_checks() -> list[tuple[str, list[CheckResult]]]:
    """Run all checks and return named groups of results."""
    return [
        ("Python", [check_python()]),
        (
            "Core (always required)",
            [check_ffmpeg(), check_ffprobe(), check_pdftoppm(), check_pymupdf()],
        ),
        ("Editor GUI", [check_nicegui()]),
        ("Beamer toolchain (for compiling your deck)", [check_latexmk(), check_pdflatex()]),
        (
            "TTS backends (at least one required)",
            [check_kokoro(), check_qwen3(), check_elevenlabs()],
        ),
        ("API keys", [check_api_key()]),
    ]


def check_ffmpeg() -> CheckResult:
    return _run_cli_check(_CHECKS_BY_NAME["ffmpeg"])


def check_ffprobe() -> CheckResult:
    return _run_cli_check(_CHECKS_BY_NAME["ffprobe"])


def check_pdftoppm() -> CheckResult:
    return _run_cli_check(_CHECKS_BY_NAME["pdftoppm"])


def check_latexmk() -> CheckResult:
    return _run_cli_check(_CHECKS_BY_NAME["latexmk"])


def check_pdflatex() -> CheckResult:
    return _run_cli_check(_CHECKS_BY_NAME["pdflatex"])


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
                symbol = click.style("✓", fg="green") if use_color else "✓"
                line = f"  {symbol} {check.name} {check.version}"
            elif is_core:
                symbol = click.style("✗", fg="red") if use_color else "✗"
                line = f"  {symbol} {check.name}"
                all_core_ok = False
            else:
                symbol = click.style("—", fg="yellow") if use_color else "—"
                line = f"  {symbol} {check.name}"
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
        msg = "Missing core dependencies — see above."
        click.echo(click.style(msg, fg="red") if use_color else msg)
    return all_core_ok
