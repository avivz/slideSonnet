"""Smoke-test an *installed* slideSonnet: the bundled frontend loads without Node.

Run with the interpreter of a clean venv that has the wheel or sdist installed
(CI does this right after building). It starts the real server on a free port,
fetches the app shell at ``/``, every script and stylesheet the shell
references, and the library API — using nothing but the standard library.
"""

from __future__ import annotations

import re
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn

from slidesonnet.server import frontend
from slidesonnet.server.app import create_app
from slidesonnet.server.library import DeckRegistry


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=5) as r:
        return int(r.status), r.read()


def main() -> int:
    if not frontend.is_built():
        print(f"FAIL: no bundled frontend at {frontend.STATIC_DIR}")
        return 1
    port = _free_port()
    with tempfile.TemporaryDirectory() as root:
        app = create_app(DeckRegistry(Path(root)))
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    status, shell = _get(base + "/")
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                print("FAIL: the server never answered")
                return 1
            if status != 200:
                print(f"FAIL: / answered {status}")
                return 1
            assets = re.findall(r'(?:src|href)="(/ui/[^"]+)"', shell.decode())
            if not assets:
                print("FAIL: the shell references no /ui/ assets")
                return 1
            for url in assets:
                status, body = _get(base + url)
                if status != 200 or not body:
                    print(f"FAIL: {url} answered {status}")
                    return 1
            status, _ = _get(base + "/api/v1/library")
            if status != 200:
                print(f"FAIL: /api/v1/library answered {status}")
                return 1
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    print(f"OK: shell + {len(assets)} asset(s) served from {frontend.STATIC_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
