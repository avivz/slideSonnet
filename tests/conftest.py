"""Shared test fixtures."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def simple_md(fixtures_dir):
    return fixtures_dir / "simple.md"


@pytest.fixture
def playlist_basic(fixtures_dir):
    return fixtures_dir / "playlist_basic.yaml"


@pytest.fixture
def pronunciation_cs(fixtures_dir):
    return fixtures_dir / "pronunciation_cs.md"
