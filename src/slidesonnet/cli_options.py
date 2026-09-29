"""Click options shared by the main CLI and the ``review`` group (no import cycle)."""

from __future__ import annotations

from pathlib import Path

import click

_NARRATION_HELP = "Sidecar path (default: <deck>.narration)"

NARRATION_OPT = click.option("--narration", type=click.Path(path_type=Path), help=_NARRATION_HELP)
#: For commands that only read the sidecar: a mistyped path is an error, not an empty deck.
EXISTING_NARRATION_OPT = click.option(
    "--narration",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=_NARRATION_HELP,
)
