"""Parse playlist YAML files into config + module list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from slidesonnet.exceptions import ConfigError
from slidesonnet.models import PlaylistEntry


def parse_playlist(playlist_path: Path) -> tuple[dict[str, Any], list[PlaylistEntry]]:
    """Parse a playlist YAML file.

    Returns:
        (raw_config_dict, list_of_playlist_entries)
    """
    text = playlist_path.read_text(encoding="utf-8")

    # Filter out // comment lines before YAML parsing
    lines = [ln for ln in text.split("\n") if not ln.lstrip().startswith("//")]
    filtered = "\n".join(lines)

    data = yaml.safe_load(filtered)
    if data is None:
        raise ConfigError(f"Playlist file is empty: {playlist_path}")
    if not isinstance(data, dict):
        raise ConfigError(
            f"Playlist must be a YAML mapping, got {type(data).__name__}: {playlist_path}"
        )

    # Extract modules list
    modules_raw = data.pop("modules", None)
    if modules_raw is None:
        raise ConfigError(f"Playlist missing required 'modules' key: {playlist_path}")
    if not isinstance(modules_raw, list):
        raise ConfigError(
            f"'modules' must be a list, got {type(modules_raw).__name__}: {playlist_path}"
        )

    entries: list[PlaylistEntry] = []
    for i, item in enumerate(modules_raw):
        if not isinstance(item, str):
            raise ConfigError(
                f"modules[{i}] must be a string, got {type(item).__name__}: {playlist_path}"
            )
        entries.append(PlaylistEntry.from_path(item))

    config_dict: dict[str, Any] = data
    return config_dict, entries
