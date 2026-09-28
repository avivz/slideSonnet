"""Write the ``/api/v1`` OpenAPI schema — the source the frontend's TS types are generated from.

``python -m slidesonnet.server.openapi frontend/openapi.json`` (``make api-types``
runs this and the TypeScript generator; CI fails when the committed copies drift).
The file is written directly, never through stdout: a library printing at
import time (PyMuPDF warns about its old ``fitz`` name) would corrupt it.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from slidesonnet.server.app import create_api_app
from slidesonnet.server.library import DeckRegistry


def api_schema() -> dict[str, Any]:
    """The API's OpenAPI document, independent of any deck on disk."""
    with tempfile.TemporaryDirectory() as root:
        schema: dict[str, Any] = create_api_app(DeckRegistry(Path(root))).openapi()
    schema["paths"] = {k: v for k, v in schema["paths"].items() if k.startswith("/api/")}
    return schema


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    text = json.dumps(api_schema(), indent=2, sort_keys=True) + "\n"
    if args:
        Path(args[0]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
