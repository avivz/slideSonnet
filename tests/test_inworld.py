"""Tests for the Inworld TTS backend (mocked SDK — never a real paid call)."""

import os
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import TTSError
from slidesonnet.models import TTSConfig


def test_missing_api_key(monkeypatch):
    """Init succeeds without API key; synthesize() raises TTSError."""
    monkeypatch.delenv("INWORLD_API_KEY", raising=False)
    config = TTSConfig(backend="inworld", inworld_voice="Ashley")

    from slidesonnet.tts.inworld import InworldTTS

    tts = InworldTTS(config)

    with pytest.raises(TTSError, match="not set"):
        tts.synthesize("Hello", MagicMock())


@patch("slidesonnet.tts.inworld.InworldClient", None)
@patch.dict(os.environ, {"INWORLD_API_KEY": "test-key"})
def test_missing_package():
    """Init succeeds without the SDK; synthesize() raises TTSError."""
    config = TTSConfig(backend="inworld", inworld_voice="Ashley")

    from slidesonnet.tts.inworld import InworldTTS

    tts = InworldTTS(config)

    with pytest.raises(TTSError, match="inworld-tts package not installed"):
        tts.synthesize("Hello", MagicMock())


@patch.dict(os.environ, {"INWORLD_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.inworld.InworldClient")
def test_synthesize_calls_api(mock_client_cls, tmp_path):
    """Client is created lazily during synthesize(); SDK called correctly."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.generate.return_value = b"fake-audio-data"

    config = TTSConfig(
        backend="inworld",
        inworld_voice="voice-abc",
        inworld_model="inworld-tts-1.5-max",
    )

    from slidesonnet.tts.inworld import InworldTTS

    tts = InworldTTS(config)

    # Client not created until first synthesize()
    mock_client_cls.assert_not_called()

    output = tmp_path / "speech.mp3"
    with patch("slidesonnet.tts.inworld._get_audio_duration", return_value=3.5):
        duration = tts.synthesize("Hello world", output)

    mock_client_cls.assert_called_once_with(api_key="test-key-123")

    assert output.exists()
    assert output.read_bytes() == b"fake-audio-data"
    assert duration == 3.5

    mock_client.generate.assert_called_once_with(
        "Hello world",
        voice="voice-abc",
        model="inworld-tts-1.5-max",
    )


@patch.dict(os.environ, {"INWORLD_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.inworld.InworldClient")
def test_voice_override(mock_client_cls, tmp_path):
    """An explicit per-utterance voice overrides the configured default."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.generate.return_value = b"audio"

    config = TTSConfig(backend="inworld", inworld_voice="default-voice")

    from slidesonnet.tts.inworld import InworldTTS

    tts = InworldTTS(config)
    output = tmp_path / "speech.mp3"
    with patch("slidesonnet.tts.inworld._get_audio_duration", return_value=1.0):
        tts.synthesize("Hi", output, voice="override-voice")

    assert mock_client.generate.call_args.kwargs["voice"] == "override-voice"


def test_default_voice_is_a_real_built_in():
    """Inworld carries a built-in default voice (like Kokoro's am_echo / Qwen3's
    Dylan), so an unvoiced utterance has something to fall back to instead of an
    empty voice id the API would reject."""
    from slidesonnet.tts.inworld import InworldTTS

    tts = InworldTTS(TTSConfig(backend="inworld"))  # nothing configured
    assert tts.default_voice() == "Simon"


@patch.dict(os.environ, {"INWORLD_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.inworld.InworldClient")
def test_unvoiced_synthesis_uses_built_in_default(mock_client_cls, tmp_path):
    """With no voice configured and none passed, synthesis uses the built-in
    default — not an empty voice id."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.generate.return_value = b"audio"

    from slidesonnet.tts.inworld import InworldTTS

    tts = InworldTTS(TTSConfig(backend="inworld"))  # default inworld_voice
    output = tmp_path / "s.mp3"
    with patch("slidesonnet.tts.inworld._get_audio_duration", return_value=1.0):
        tts.synthesize("Hi", output)  # no voice override

    assert mock_client.generate.call_args.kwargs["voice"] == "Simon"


@patch.dict(os.environ, {"INWORLD_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.inworld.InworldClient")
def test_api_failure_is_clean_tts_error(mock_client_cls, tmp_path):
    """An SDK failure surfaces as TTSError and leaves no file behind."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.generate.side_effect = ConnectionError("network down")

    config = TTSConfig(backend="inworld", inworld_voice="voice-abc")

    from slidesonnet.tts.inworld import InworldTTS

    tts = InworldTTS(config)
    output = tmp_path / "speech.mp3"

    with pytest.raises(TTSError, match="Inworld"):
        tts.synthesize("Hello world", output)

    assert not output.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_name():
    """name() works without API key or package."""
    config = TTSConfig(backend="inworld", inworld_voice="v")
    from slidesonnet.tts.inworld import InworldTTS

    assert InworldTTS(config).name() == "inworld"


# -- Speed (pace) tests -----------------------------------------------------


@patch.dict(os.environ, {"INWORLD_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.inworld.InworldClient")
def test_speed_passed_as_speaking_rate(mock_client_cls, tmp_path):
    """When speed != 1.0, it is passed as speaking_rate."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.generate.return_value = b"audio"

    config = TTSConfig(backend="inworld", inworld_voice="voice-abc", inworld_speed=1.1)

    from slidesonnet.tts.inworld import InworldTTS

    tts = InworldTTS(config)
    output = tmp_path / "speech.mp3"
    with patch("slidesonnet.tts.inworld._get_audio_duration", return_value=2.0):
        tts.synthesize("Hello", output)

    assert mock_client.generate.call_args.kwargs["speaking_rate"] == 1.1


@patch.dict(os.environ, {"INWORLD_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.inworld.InworldClient")
def test_speed_default_not_passed(mock_client_cls, tmp_path):
    """When speed == 1.0 (default), speaking_rate is not passed (natural rate)."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.generate.return_value = b"audio"

    config = TTSConfig(backend="inworld", inworld_voice="voice-abc")

    from slidesonnet.tts.inworld import InworldTTS

    tts = InworldTTS(config)
    output = tmp_path / "speech.mp3"
    with patch("slidesonnet.tts.inworld._get_audio_duration", return_value=2.0):
        tts.synthesize("Hello", output)

    assert "speaking_rate" not in mock_client.generate.call_args.kwargs


@patch.dict(os.environ, {"INWORLD_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.inworld.InworldClient")
def test_speed_clamped_to_api_range(mock_client_cls, tmp_path):
    """A pace-multiplied speed beyond [0.5, 1.5] is clamped to the API range."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.generate.return_value = b"audio"

    config = TTSConfig(backend="inworld", inworld_voice="voice-abc", inworld_speed=2.0)

    from slidesonnet.tts.inworld import InworldTTS

    tts = InworldTTS(config)
    output = tmp_path / "speech.mp3"
    with patch("slidesonnet.tts.inworld._get_audio_duration", return_value=2.0):
        tts.synthesize("Hello", output)

    assert mock_client.generate.call_args.kwargs["speaking_rate"] == 1.5


def test_cache_key_with_speed():
    """cache_key includes speed when != 1.0."""
    config = TTSConfig(backend="inworld", inworld_voice="v", inworld_speed=1.1)
    from slidesonnet.tts.inworld import InworldTTS

    assert ":1.1" in InworldTTS(config).cache_key()


def test_cache_key_default_speed():
    """cache_key omits speed at the default (1.0): inworld:voice:model."""
    config = TTSConfig(backend="inworld", inworld_voice="v")
    from slidesonnet.tts.inworld import InworldTTS

    parts = InworldTTS(config).cache_key().split(":")
    assert len(parts) == 3  # inworld:voice:model


def test_inworld_is_paid():
    from slidesonnet.tts.inworld import InworldTTS

    assert InworldTTS(TTSConfig()).paid is True


def test_default_voice():
    config = TTSConfig(backend="inworld", inworld_voice="Ashley")
    from slidesonnet.tts.inworld import InworldTTS

    assert InworldTTS(config).default_voice() == "Ashley"
