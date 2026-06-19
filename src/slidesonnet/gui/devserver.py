"""Auto-reload dev server behind ``slidesonnet edit --dev``.

NiceGUI's reload mode (uvicorn + watchfiles) re-imports the entry module in a
child process, so it must be a real ``python -m``-runnable module with the
``__main__``/``__mp_main__`` guard — a console-script entry point won't do.
The CLI execs this module with parameters in ``SLIDESONNET_DEV_*`` env vars
(see :func:`slidesonnet.gui.launch.dev_invocation`).

The module body runs in two processes: the watcher (``__main__``) and the
serving worker (``__mp_main__``, restarted on every source change). One-shot
side effects — the banner, opening the browser — belong to the watcher only.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Iterable
from pathlib import Path

from nicegui import app, ui

import slidesonnet
from slidesonnet.gui.app import build_editor
from slidesonnet.gui.launch import (
    app_invocation,
    browser_invocation,
    is_wsl,
    launch_browser,
)

logger = logging.getLogger(__name__)


def should_open_browser(samples: Iterable[int | None]) -> bool:
    """Decide whether the watcher should open a browser tab.

    *samples* are successive readings of the server's connected-client count
    (``None`` when a probe failed). An already-open tab reconnects to the
    restarted server on its own — as soon as any reading shows a live client,
    opening another tab would be a duplicate.
    """
    for count in samples:
        if count is not None and count > 0:
            return False
    return True


def _connected_clients(url: str) -> int | None:
    try:
        with urllib.request.urlopen(f"{url}/ss-dev/clients", timeout=2) as resp:
            return int(json.load(resp).get("connected", 0))
    except Exception:
        return None


def _open_browser_soon(url: str) -> None:
    """Open *url* unless an existing tab reconnects first.

    Mirrors ``run_editor``'s opening logic (``--browser``/``--app`` flags arrive
    via env). Runs in the watcher process only, so source reloads never re-open
    tabs; restarting the command reuses a still-open tab instead of stacking up
    new ones (it reconnects within socket.io's ~5s retry window).
    """
    browser = os.environ.get("SLIDESONNET_DEV_BROWSER")
    env_browser = os.environ.get("SLIDESONNET_BROWSER")
    wsl = is_wsl()
    use_webbrowser = False
    if os.environ.get("SLIDESONNET_DEV_APP") == "1":
        cmd = app_invocation(browser, env_browser=env_browser, wsl=wsl)
    else:
        cmd, use_webbrowser = browser_invocation(
            browser, env_browser=env_browser, wsl=wsl, wslview=shutil.which("wslview")
        )
    if cmd is None and not use_webbrowser:
        logger.info(
            "Open %s in your browser (under WSL: install 'wslview' or pass --browser).", url
        )
        return
    opener = cmd

    def probe_then_open() -> None:
        samples: list[int | None] = []
        for delay in (3.0, 3.5):  # server boot, then the old tab's reconnect window
            time.sleep(delay)
            samples.append(_connected_clients(url))
            if not should_open_browser(samples):
                return
        if opener is not None:
            launch_browser(opener, url)
        else:
            webbrowser.open(url)

    threading.Thread(target=probe_then_open, daemon=True).start()


if __name__ in {"__main__", "__mp_main__"}:
    _pdf = Path(os.environ["SLIDESONNET_DEV_PDF"])
    _sidecar_env = os.environ.get("SLIDESONNET_DEV_SIDECAR")
    _sidecar = Path(_sidecar_env) if _sidecar_env else None
    _host = os.environ.get("SLIDESONNET_DEV_HOST", "127.0.0.1")
    _port = int(os.environ.get("SLIDESONNET_DEV_PORT", "8080"))

    # This is a fresh process (the exec'd reload server), so re-establish logging
    # the CLI group set up — the level and log-file choice arrive via env.
    from slidesonnet.logging_setup import (
        ENV_LEVEL,
        attach_deck_file_logging,
        configure_console_logging,
        resolve_console_level,
    )

    configure_console_logging(resolve_console_level(env=os.environ.get(ENV_LEVEL)))
    _dev_log = os.environ.get("SLIDESONNET_DEV_LOG_FILE")
    attach_deck_file_logging(
        _pdf,
        override=Path(_dev_log) if _dev_log else None,
        disabled=os.environ.get("SLIDESONNET_DEV_NO_LOG_FILE") == "1",
    )

    @ui.page("/")
    def _index() -> None:
        build_editor(_pdf, _sidecar)

    @app.get("/ss-dev/clients")
    def _clients() -> dict[str, int]:
        from nicegui import Client

        connected = sum(1 for c in Client.instances.values() if c.has_socket_connection)
        return {"connected": connected}

    if __name__ == "__main__":  # watcher process: one-shot side effects
        _url = f"http://{_host}:{_port}"
        logger.info("slideSonnet editor (dev, auto-reload) at %s  (Ctrl-C to stop)", _url)
        if os.environ.get("SLIDESONNET_DEV_NO_BROWSER") != "1":
            _open_browser_soon(_url)

    ui.run(
        host=_host,
        port=_port,
        title="slideSonnet (dev)",
        reload=True,
        show=False,
        uvicorn_reload_dirs=str(Path(slidesonnet.__file__).parent),
    )
