"""The suite-wide guard against real ElevenLabs API calls (see conftest.py).

A real ``.env`` with a live key sits in the repo root, and ``doctor`` runs
``load_dotenv()`` — without the guard, one unit test running the real doctor
leaks the key into ``os.environ`` for the rest of the session, and any test
that constructs a real client (e.g. a regressed paid-engine confirm dialog)
would charge the account. These tests pin the guard itself.
"""

import os

import pytest

from slidesonnet.models import TTSConfig
from slidesonnet.tts.elevenlabs import ElevenLabsTTS
from slidesonnet.tts.inworld import InworldTTS


def test_api_key_env_is_sentinel() -> None:
    """The autouse guard replaces any real key with a sentinel for every test."""
    assert os.environ.get("ELEVENLABS_API_KEY") == "unit-test-no-real-calls"


def test_real_client_construction_fails_fast() -> None:
    """Constructing the real ElevenLabs client inside a test raises immediately."""
    tts = ElevenLabsTTS(TTSConfig(backend="elevenlabs", elevenlabs_voice_id="v1"))
    with pytest.raises(AssertionError, match="real ElevenLabs client"):
        tts._ensure_client()


def test_dotenv_cannot_override_sentinel() -> None:
    """load_dotenv (run by doctor) must not replace the sentinel with a real key."""
    from dotenv import load_dotenv

    load_dotenv()
    assert os.environ.get("ELEVENLABS_API_KEY") == "unit-test-no-real-calls"


def test_inworld_api_key_env_is_sentinel() -> None:
    """The autouse guard pins the Inworld key to a sentinel too."""
    assert os.environ.get("INWORLD_API_KEY") == "unit-test-no-real-calls"


def test_real_inworld_client_construction_fails_fast() -> None:
    """Constructing the real Inworld client inside a test raises immediately."""
    tts = InworldTTS(TTSConfig(backend="inworld", inworld_voice="Ashley"))
    with pytest.raises(AssertionError, match="real Inworld client"):
        tts._ensure_client()
