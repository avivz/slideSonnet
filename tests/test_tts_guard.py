"""The suite-wide guard against real Inworld API calls (see conftest.py).

A real ``.env`` with a live key sits in the repo root, and ``doctor`` runs
``load_dotenv()`` — without the guard, one unit test running the real doctor
leaks the key into ``os.environ`` for the rest of the session, and any test
that constructs a real client (e.g. a regressed paid-engine confirm dialog)
would charge the account. These tests pin the guard itself.
"""

import os

import pytest

from slidesonnet.models import TTSConfig
from slidesonnet.tts.inworld import InworldTTS


def test_dotenv_cannot_override_sentinel() -> None:
    """load_dotenv (run by doctor) must not replace the sentinel with a real key."""
    from dotenv import load_dotenv

    load_dotenv()
    assert os.environ.get("INWORLD_API_KEY") == "unit-test-no-real-calls"


def test_inworld_api_key_env_is_sentinel() -> None:
    """The autouse guard pins the Inworld key to a sentinel."""
    assert os.environ.get("INWORLD_API_KEY") == "unit-test-no-real-calls"


def test_real_inworld_client_construction_fails_fast() -> None:
    """Constructing the real Inworld client inside a test raises immediately."""
    tts = InworldTTS(TTSConfig(backend="inworld", inworld_voice="Ashley"))
    with pytest.raises(AssertionError, match="real Inworld client"):
        tts._ensure_client()
