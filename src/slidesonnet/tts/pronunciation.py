"""Pronunciation dictionary: load from .md files and apply substitutions."""

from __future__ import annotations

import re
import sys
from pathlib import Path


# Match: **word**: replacement
_ENTRY_RE = re.compile(r"^\*\*(.+?)\*\*\s*:\s*(.+)$")


def load_pronunciation_file(path: Path) -> dict[str, str]:
    """Parse a pronunciation .md file into a word -> replacement dict.

    Format:
        **Dijkstra**: DYKE-struh
        **Euler**: OY-ler

    Section headings (## ...) are ignored (for human readability only).
    """
    if not path.exists():
        print(f"WARNING: {path}: pronunciation file not found", file=sys.stderr)
        return {}

    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ENTRY_RE.match(line.strip())
        if match:
            word = match.group(1).strip()
            replacement = match.group(2).strip()
            entries[word] = replacement
    return entries


def load_pronunciation_files(paths: list[Path]) -> dict[str, str]:
    """Load and merge multiple pronunciation files."""
    merged: dict[str, str] = {}
    for path in paths:
        merged.update(load_pronunciation_file(path))
    return merged


def apply_pronunciation(text: str, dictionary: dict[str, str]) -> str:
    """Apply pronunciation substitutions to text.

    Replaces whole words only (word boundaries), case-insensitive.
    Uses a single regex pass to avoid double-substitution when a
    replacement produces text that matches another dictionary entry.
    """
    if not dictionary:
        return text

    # Build a single pattern matching all words at once (longest first)
    sorted_words = sorted(dictionary.keys(), key=len, reverse=True)
    pattern = "|".join(rf"\b{re.escape(word)}\b" for word in sorted_words)

    # Case-insensitive lookup table
    lower_dict = {word.lower(): replacement for word, replacement in dictionary.items()}

    def _replacer(match: re.Match[str]) -> str:
        return lower_dict[match.group(0).lower()]

    return re.sub(pattern, _replacer, text, flags=re.IGNORECASE)
