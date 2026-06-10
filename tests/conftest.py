"""Shared test fixtures."""

from pathlib import Path

import pytest

# NiceGUI's in-process `user` fixture (no selenium). The combined plugin pulls
# in selenium for the `screen` fixture, so load only the user plugin.
pytest_plugins = ["nicegui.testing.user_plugin"]

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def marked_pdf(fixtures_dir):
    return fixtures_dir / "marked.pdf"


@pytest.fixture
def pronunciation_cs(fixtures_dir):
    return fixtures_dir / "pronunciation_cs.md"
