"""Parse playlist markdown files into config + module list."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from slidesonnet.models import PlaylistEntry


# Match: 1. [label](path)  or  2. [label](path) <!-- options -->
_LIST_ITEM_RE = re.compile(r"^\s*\d+\.\s+\[([^\]]+)\]\(([^)]+)\)")


def parse_playlist(playlist_path: Path) -> tuple[dict[str, Any], list[PlaylistEntry]]:
    """Parse a playlist markdown file.

    Returns:
        (raw_config_dict, list_of_playlist_entries)
    """
    text = playlist_path.read_text(encoding="utf-8")
    config_dict, body = _split_front_matter(text)
    entries = _parse_body(body, playlist_path.parent)
    return config_dict, entries


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML front matter from markdown text.

    Returns (config_dict, remaining_body).
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text

    # Find closing ---
    # First --- is at the start; find the second one
    lines = stripped.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    front_matter_lines = lines[1:end_idx]
    # Filter out // comment lines from YAML
    yaml_lines = [ln for ln in front_matter_lines if not ln.lstrip().startswith("//")]
    yaml_text = "\n".join(yaml_lines)
    body = "\n".join(lines[end_idx + 1 :])

    config_dict = yaml.safe_load(yaml_text) or {}
    return config_dict, body


def _parse_body(body: str, base_dir: Path) -> list[PlaylistEntry]:
    """Parse the playlist body into PlaylistEntry objects.

    Only numbered markdown list items with [label](path) are parsed.
    Lines starting with // are comments and ignored.
    All other lines (headings, blank lines, prose) are ignored.
    """
    entries = []
    for line in body.split("\n"):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("//"):
            continue

        # Try to match a list item
        match = _LIST_ITEM_RE.match(stripped)
        if match:
            label = match.group(1)
            path_str = match.group(2)
            entry = PlaylistEntry.from_link(label, path_str)
            entries.append(entry)

    return entries
