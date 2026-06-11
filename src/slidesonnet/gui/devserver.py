"""Auto-reload dev server behind ``slidesonnet edit --dev``.

NiceGUI's reload mode (uvicorn + watchfiles) re-imports the entry module in a
child process, so it must be a real ``python -m``-runnable module with the
``__main__``/``__mp_main__`` guard — a console-script entry point won't do.
The CLI execs this module with parameters in ``SLIDESONNET_DEV_*`` env vars
(see :func:`slidesonnet.gui.app.dev_invocation`).

The module body runs in two processes: the watcher (``__main__``) and the
serving worker (``__mp_main__``, restarted on every source change). One-shot
side effects — the banner, opening the browser — belong to the watcher only.
"""

from __future__ import annotations

import os
import shutil
import threading
import webbrowser
from pathlib import Path

from nicegui import ui

import slidesonnet
from slidesonnet.gui.app import (
    _launch_browser,
    app_invocation,
    browser_invocation,
    build_editor,
    is_wsl,
)


def _open_browser_soon(url: str) -> None:
    """Open *url* once the worker has had a moment to bind the port.

    Mirrors ``run_editor``'s opening logic (``--browser``/``--app`` flags arrive
    via env). Runs in the watcher process only, so reloads never re-open tabs.
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
    if cmd is not None:
        opener = cmd
        threading.Timer(1.5, lambda: _launch_browser(opener, url)).start()
    elif use_webbrowser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    else:
        print(f"Open {url} in your browser (under WSL: install 'wslview' or pass --browser).")


if __name__ in {"__main__", "__mp_main__"}:
    _pdf = Path(os.environ["SLIDESONNET_DEV_PDF"])
    _sidecar_env = os.environ.get("SLIDESONNET_DEV_SIDECAR")
    _sidecar = Path(_sidecar_env) if _sidecar_env else None
    _host = os.environ.get("SLIDESONNET_DEV_HOST", "127.0.0.1")
    _port = int(os.environ.get("SLIDESONNET_DEV_PORT", "8080"))

    @ui.page("/")
    def _index() -> None:
        build_editor(_pdf, _sidecar)

    if __name__ == "__main__":  # watcher process: one-shot side effects
        _url = f"http://{_host}:{_port}"
        print(f"slideSonnet editor (dev, auto-reload) at {_url}  (Ctrl-C to stop)")
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
