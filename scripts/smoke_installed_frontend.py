"""Smoke-test an *installed* slideSonnet: the bundled frontend loads without Node.

Run with the interpreter of a clean venv that has the wheel or sdist installed
(CI does this right after building). It serves the app in-process, fetches the
shell at ``/``, and fetches every script and stylesheet the shell references.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from slidesonnet.gui.library import DeckRegistry
from slidesonnet.server import frontend
from slidesonnet.server.app import create_api_app


def main() -> int:
    if shutil.which("node"):
        print("warning: node is on PATH; this check is meant to run without it")
    if not frontend.is_built():
        print(f"FAIL: no bundled frontend at {frontend.STATIC_DIR}")
        return 1
    with tempfile.TemporaryDirectory() as root, TestClient(create_api_app(DeckRegistry(Path(root)))) as c:
        shell = c.get("/")
        if shell.status_code != 200:
            print(f"FAIL: / answered {shell.status_code}")
            return 1
        assets = re.findall(r'(?:src|href)="(/ui/[^"]+)"', shell.text)
        if not assets:
            print("FAIL: the shell references no /ui/ assets")
            return 1
        for url in assets:
            r = c.get(url)
            if r.status_code != 200 or not r.content:
                print(f"FAIL: {url} answered {r.status_code}")
                return 1
        lib = c.get("/api/v1/library")
        if lib.status_code != 200:
            print(f"FAIL: /api/v1/library answered {lib.status_code}")
            return 1
    print(f"OK: shell + {len(assets)} asset(s) served from {frontend.STATIC_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
