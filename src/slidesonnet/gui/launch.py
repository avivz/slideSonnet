"""Launching the editor: browser/app-window resolution and the dev server argv.

Pure plumbing, no NiceGUI imports — how to open a URL on a desktop, under WSL
(prefer ``wslview``; never launch a Linux browser), or as a chromeless
Chromium app window, plus the ``edit --dev`` reload-server invocation.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


def is_wsl() -> bool:
    """True when running under Windows Subsystem for Linux."""
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def browser_invocation(
    browser: str | None,
    *,
    env_browser: str | None = None,
    wsl: bool = False,
    wslview: str | None = None,
) -> tuple[list[str] | None, bool]:
    """Decide how to open the editor URL.

    Returns ``(opener, use_nicegui_show)``:
    - ``opener`` is a command (argv list) we launch ourselves with the URL
      (substituted for ``{url}`` if present, else appended), or ``None`` if we
      won't open a browser ourselves.
    - ``use_nicegui_show`` is whether to let NiceGUI open its default browser.

    An explicit ``--browser`` / ``SLIDESONNET_BROWSER`` wins. Under WSL we prefer
    ``wslview`` (opens the *Windows* default browser) and otherwise refuse to
    launch a Linux browser — just print the URL. On a normal desktop we let
    NiceGUI handle it.
    """
    chosen = browser or env_browser
    if chosen:
        return shlex.split(chosen), False
    if wsl:
        return ([wslview] if wslview else None), False
    return None, True


def apply_url(cmd: list[str], url: str) -> list[str]:
    """Substitute *url* for a ``{url}`` token in *cmd*, or append it if absent."""
    if any("{url}" in tok for tok in cmd):
        return [tok.replace("{url}", url) for tok in cmd]
    return [*cmd, url]


# Common Windows install paths for Chromium browsers (seen from WSL under /mnt/c).
_WINDOWS_CHROMIUM = [
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
]
# Linux/native Chromium executables (for --app on a non-WSL desktop).
_LINUX_CHROMIUM = ["google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave"]


def find_chromium(
    *,
    wsl: bool,
    exists: Callable[[str], bool],
    which: Callable[[str], str | None],
) -> str | None:
    """Locate a Chromium-based browser executable for app-window mode.

    Under WSL, look for Edge/Chrome under ``/mnt/c``; otherwise search PATH.
    Returns the executable path, or ``None`` if none is found.
    """
    if wsl:
        return next((p for p in _WINDOWS_CHROMIUM if exists(p)), None)
    for name in _LINUX_CHROMIUM:
        found = which(name)
        if found:
            return found
    return None


def app_invocation(
    browser: str | None,
    *,
    env_browser: str | None = None,
    wsl: bool = False,
    exists: Callable[[str], bool] = os.path.exists,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str] | None:
    """Build a chromeless app-window command (`<chromium> --app={url}`).

    Uses an explicit ``--browser``/env executable if given (shlex-split, so it
    may carry args), else auto-detects Edge/Chrome (kept as a single token since
    Windows paths contain spaces). Returns the argv (with a ``{url}`` placeholder)
    or ``None`` if no Chromium browser could be found.
    """
    explicit = browser or env_browser
    if explicit:
        base = shlex.split(explicit)
    else:
        exe = find_chromium(wsl=wsl, exists=exists, which=which)
        if not exe:
            return None
        base = [exe]
    return [*base, "--app={url}"]


def dev_invocation(
    pdf_path: Path | None,
    *,
    root: Path | None = None,
    sidecar_path: Path | None,
    host: str,
    port: int,
    browser: str | None = None,
    app_window: bool = False,
    no_browser: bool = False,
) -> tuple[list[str], dict[str, str]]:
    """Argv + extra env to launch the auto-reload dev server (``edit --dev``).

    NiceGUI's reload mode re-imports its entry module in a child process, so it
    needs a ``python -m``-runnable module (``slidesonnet.gui.devserver``) rather
    than the console-script entry point; parameters travel via environment.
    """
    env = {
        "SLIDESONNET_DEV_HOST": host,
        "SLIDESONNET_DEV_PORT": str(port),
    }
    if pdf_path is not None:
        env["SLIDESONNET_DEV_PDF"] = str(pdf_path.resolve())
    if root is not None:
        env["SLIDESONNET_DEV_ROOT"] = str(root.resolve())
    if sidecar_path is not None:
        env["SLIDESONNET_DEV_SIDECAR"] = str(sidecar_path.resolve())
    if browser:
        env["SLIDESONNET_DEV_BROWSER"] = browser
    if app_window:
        env["SLIDESONNET_DEV_APP"] = "1"
    if no_browser:
        env["SLIDESONNET_DEV_NO_BROWSER"] = "1"
    return [sys.executable, "-m", "slidesonnet.gui.devserver"], env


def launch_browser(opener: list[str], url: str) -> None:
    """Open *url* with the configured command, swallowing launch errors."""
    cmd = apply_url(opener, url)
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        logger.warning("Could not launch browser %r: %s — open %s manually.", cmd, exc, url)
