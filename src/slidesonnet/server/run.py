"""Running the editor: build the deck library, serve it, open a browser.

``slidesonnet edit`` lands here. The server is Uvicorn on the loopback address
by default. Binding beyond this machine is deliberate (:func:`check_bind`): a
specific ``--host`` address is accepted as a Host name and warned about; a
wildcard (``0.0.0.0``/``::``) needs the names other machines will use, given
with ``--allow-host``. The browser opens once the server is listening — under WSL in the
*Windows* browser via ``wslview`` (never a Linux one), with ``--browser`` for
any command, or as a chromeless app window with ``--app``.

``--dev`` runs the same app under Uvicorn's reloader, restarting on changes to
slideSonnet's own source; parameters reach the reloaded worker through
``SLIDESONNET_DEV_*`` environment variables (see :func:`dev_app`).
"""

from __future__ import annotations

import ipaddress
import logging
import os
import shutil
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, cast

import uvicorn
from fastapi import FastAPI

import slidesonnet
from slidesonnet.server.app import create_app
from slidesonnet.server.context import context_of
from slidesonnet.server.launch import app_invocation, browser_invocation, is_wsl, launch_browser
from slidesonnet.server.library import DeckRegistry

logger = logging.getLogger(__name__)

#: How the run-log was configured on the command line, so opening another deck
#: re-applies the same choice to the deck it lands on.
_log_prefs: dict[str, Any] = {"override": None, "disabled": False}


def set_log_preferences(*, override: Path | None, disabled: bool) -> None:
    """Remember the CLI's ``--log-file``/``--no-log-file`` choice for later decks."""
    _log_prefs["override"] = override
    _log_prefs["disabled"] = disabled


def retarget_deck_log(pdf_path: Path) -> None:
    """Point the run-log at the deck now being edited (an explicit --log-file wins)."""
    from slidesonnet.logging_setup import attach_deck_file_logging

    attach_deck_file_logging(
        pdf_path,
        override=cast(Path | None, _log_prefs["override"]),
        disabled=bool(_log_prefs["disabled"]),
    )


def build_registry(
    pdf_path: Path | None, *, sidecar_path: Path | None, root: Path | None
) -> DeckRegistry:
    """The deck library: scanned from *root* (else the deck's folder, else the cwd)."""
    scan_root = (root or (pdf_path.parent if pdf_path else Path.cwd())).resolve()
    registry = DeckRegistry(scan_root)
    result = registry.rescan()
    if pdf_path is not None:
        registry.register(pdf_path, sidecar_path=sidecar_path)
    logger.info(
        "Deck library: %d deck(s) under %s%s",
        len(registry.entries()),
        scan_root,
        " (scan truncated — pass --root to narrow it)" if result.truncated else "",
    )
    return registry


def editor_app(
    registry: DeckRegistry, *, host: str, allow_hosts: list[str] | None = None
) -> FastAPI:
    app = create_app(registry, host=host)
    ctx = context_of(app)
    ctx.on_deck_open = retarget_deck_log
    for name in allow_hosts or ():
        ctx.allow_host(name)
    return app


_WILDCARDS = frozenset({"0.0.0.0", "::"})


class BindRefused(ValueError):
    """A bind that would expose the editor without saying who may reach it."""


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def check_bind(host: str, port: int, allow_hosts: list[str]) -> str | None:
    """A warning for a bind beyond this machine (None on loopback).

    Raises :class:`BindRefused` for a wildcard bind without ``--allow-host``:
    it would listen on the network yet answer only ``localhost`` (the Host check
    refuses every other name), so it is either a mistake or unusable.
    """
    if is_loopback(host):
        return None
    if host in _WILDCARDS and not allow_hosts:
        raise BindRefused(
            f"--host {host} listens on every network interface, but the editor only "
            "answers to the names it is told. Add --allow-host with the address or name "
            "other machines will use (e.g. --allow-host 192.168.1.20), or drop --host "
            "to stay on this machine."
        )
    names = ", ".join([h for h in [host] if h not in _WILDCARDS] + allow_hosts)
    return (
        f"Warning: the editor on port {port} is reachable from other machines ({names}). "
        "Anyone who can reach it can read and change your decks and generate audio "
        "(including paid clips). Use it only on a network you trust."
    )


def start_url(pdf_path: Path | None, host: str, port: int) -> str:
    """Open the deck that was asked for, else the library."""
    from slidesonnet.server.library import deck_token

    shown = "localhost" if host in _WILDCARDS else host
    if ":" in shown and not shown.startswith("["):
        shown = f"[{shown}]"  # an IPv6 literal
    base = f"http://{shown}:{port}"
    return f"{base}/d/{deck_token(pdf_path)}" if pdf_path is not None else f"{base}/"


def open_when_ready(
    url: str, *, browser: str | None, app_window: bool, timeout: float = 30.0
) -> None:
    """Open *url* in a browser once the server answers (in a background thread)."""
    env_browser = os.environ.get("SLIDESONNET_BROWSER")
    wsl = is_wsl()
    opener: list[str] | None
    use_default = False
    if app_window:
        opener = app_invocation(browser, env_browser=env_browser, wsl=wsl)
        if opener is None:
            logger.warning(
                "--app needs a Chromium browser (Edge/Chrome) and none was found. "
                "Pass --browser with its path, or drop --app. Open %s manually.",
                url,
            )
            return
    else:
        opener, use_default = browser_invocation(
            browser, env_browser=env_browser, wsl=wsl, wslview=shutil.which("wslview")
        )
        if opener is None and not use_default:
            logger.info(
                "WSL detected and no browser configured — open %s in your Windows browser "
                "(install 'wslview', or pass --browser / --app to auto-open).",
                url,
            )
            return

    def wait_then_open() -> None:
        deadline = time.monotonic() + timeout
        probe = url.split("/d/")[0].rstrip("/") + "/api/v1/session"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(probe, timeout=1):
                    break
            except OSError:
                time.sleep(0.2)
        if opener is not None:
            launch_browser(opener, url)
        else:
            webbrowser.open(url)

    threading.Thread(target=wait_then_open, daemon=True, name="ss-open-browser").start()


def run_editor(
    pdf_path: Path | None = None,
    *,
    sidecar_path: Path | None = None,
    root: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
    browser: str | None = None,
    app_window: bool = False,
    allow_hosts: list[str] | None = None,
) -> None:
    """Serve the editor until Ctrl-C (blocking)."""
    registry = build_registry(pdf_path, sidecar_path=sidecar_path, root=root)
    app = editor_app(registry, host=host, allow_hosts=allow_hosts)
    url = start_url(pdf_path, host, port)
    if open_browser:
        open_when_ready(url, browser=browser, app_window=app_window)
    logger.info("slideSonnet editor running at %s  (Ctrl-C to stop)", url)
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ---- --dev: the same app under Uvicorn's reloader ----------------------------------
_DEV_PREFIX = "SLIDESONNET_DEV_"


def dev_environment(
    pdf_path: Path | None,
    *,
    root: Path | None,
    sidecar_path: Path | None,
    host: str,
    port: int,
    allow_hosts: list[str] | None = None,
) -> dict[str, str]:
    """The ``SLIDESONNET_DEV_*`` variables :func:`dev_app` rebuilds the app from."""
    env = {f"{_DEV_PREFIX}HOST": host, f"{_DEV_PREFIX}PORT": str(port)}
    if allow_hosts:
        env[f"{_DEV_PREFIX}ALLOW_HOSTS"] = ",".join(allow_hosts)
    if pdf_path is not None:
        env[f"{_DEV_PREFIX}PDF"] = str(pdf_path.resolve())
    if root is not None:
        env[f"{_DEV_PREFIX}ROOT"] = str(root.resolve())
    if sidecar_path is not None:
        env[f"{_DEV_PREFIX}SIDECAR"] = str(sidecar_path.resolve())
    return env


def dev_app() -> FastAPI:
    """App factory for the reloaded worker (``uvicorn --factory``).

    The worker is a fresh process, so it re-establishes the logging the CLI set
    up — the console level and the log-file choice arrive via the environment.
    """
    from slidesonnet.logging_setup import (
        ENV_LEVEL,
        configure_console_logging,
        resolve_console_level,
    )

    configure_console_logging(resolve_console_level(env=os.environ.get(ENV_LEVEL)))
    log_file = os.environ.get(f"{_DEV_PREFIX}LOG_FILE")
    set_log_preferences(
        override=Path(log_file) if log_file else None,
        disabled=os.environ.get(f"{_DEV_PREFIX}NO_LOG_FILE") == "1",
    )
    pdf = os.environ.get(f"{_DEV_PREFIX}PDF")
    sidecar = os.environ.get(f"{_DEV_PREFIX}SIDECAR")
    root = os.environ.get(f"{_DEV_PREFIX}ROOT")
    registry = build_registry(
        Path(pdf) if pdf else None,
        sidecar_path=Path(sidecar) if sidecar else None,
        root=Path(root) if root else None,
    )
    allowed = os.environ.get(f"{_DEV_PREFIX}ALLOW_HOSTS", "")
    return editor_app(
        registry,
        host=os.environ.get(f"{_DEV_PREFIX}HOST", "127.0.0.1"),
        allow_hosts=[h for h in allowed.split(",") if h],
    )


def run_dev(
    pdf_path: Path | None,
    *,
    sidecar_path: Path | None,
    root: Path | None,
    host: str,
    port: int,
    open_browser: bool,
    browser: str | None,
    app_window: bool,
    allow_hosts: list[str] | None = None,
) -> None:
    """Serve with auto-reload on slideSonnet's own source changes (blocking)."""
    from slidesonnet.logging_setup import ENV_LEVEL

    os.environ.update(
        dev_environment(
            pdf_path,
            root=root,
            sidecar_path=sidecar_path,
            host=host,
            port=port,
            allow_hosts=allow_hosts,
        )
    )
    os.environ[ENV_LEVEL] = logging.getLevelName(
        logging.getLogger("slidesonnet").getEffectiveLevel()
    )
    if _log_prefs["disabled"]:
        os.environ[f"{_DEV_PREFIX}NO_LOG_FILE"] = "1"
    elif _log_prefs["override"] is not None:
        os.environ[f"{_DEV_PREFIX}LOG_FILE"] = str(Path(_log_prefs["override"]).resolve())
    url = start_url(pdf_path, host, port)
    if open_browser:  # the reloader process only: a code change never opens another tab
        open_when_ready(url, browser=browser, app_window=app_window)
    logger.info("slideSonnet editor (dev, auto-reload) at %s  (Ctrl-C to stop)", url)
    uvicorn.run(
        "slidesonnet.server.run:dev_app",
        factory=True,
        host=host,
        port=port,
        reload=True,
        reload_dirs=[str(Path(slidesonnet.__file__).parent)],
        log_level="warning",
    )
