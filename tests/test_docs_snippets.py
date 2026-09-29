"""The slidesonnet.toml snippets we publish must mean what they say when copied."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DOCS = ["README.md", "docs/authoring.md", ".claude/skills/beamer-writer/SKILL.md"]
_TOML_BLOCK = re.compile(r"```toml\n(.*?)```", re.DOTALL)


def _toml_snippets() -> list[pytest.ParameterSet]:
    return [
        pytest.param(doc, block, id=f"{doc}#{i}")
        for doc in DOCS
        for i, block in enumerate(_TOML_BLOCK.findall((ROOT / doc).read_text(encoding="utf-8")))
    ]


@pytest.mark.parametrize(("doc", "snippet"), _toml_snippets())
def test_toml_snippet_keys_land_where_documented(doc: str, snippet: str) -> None:
    data = tomllib.loads(snippet)  # parses at all
    if re.search(r"^pronunciation\s*=", snippet, re.MULTILINE):
        # TOML scopes a key to the table above it: below [voices.x] it is ignored.
        assert "pronunciation" in data, f"{doc}: pronunciation must sit above the first [table]"
