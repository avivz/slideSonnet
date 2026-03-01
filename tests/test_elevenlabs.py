"""Tests for ElevenLabs TTS backend (mocked API)."""

import os
from unittest.mock import ANY, MagicMock, patch

import pytest

from slidesonnet.exceptions import TTSError
from slidesonnet.models import TTSConfig


def test_missing_api_key(monkeypatch):
    """Init succeeds without API key; synthesize() raises TTSError."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_api_key_env="ELEVENLABS_API_KEY",
        elevenlabs_voice_id="test-voice",
    )

    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(config)

    with pytest.raises(TTSError, match="not set"):
        tts.synthesize("Hello", MagicMock())


@patch("slidesonnet.tts.elevenlabs.ElevenLabs", None)
@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"})
def test_missing_package():
    """Init succeeds without package; synthesize() raises TTSError."""
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_api_key_env="ELEVENLABS_API_KEY",
        elevenlabs_voice_id="test-voice",
    )

    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(config)

    with pytest.raises(TTSError, match="elevenlabs package not installed"):
        tts.synthesize("Hello", MagicMock())


@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.elevenlabs.VoiceSettings", MagicMock)
@patch("slidesonnet.tts.elevenlabs.ElevenLabs")
def test_synthesize_calls_api(mock_elevenlabs_cls, tmp_path):
    """Client is created lazily during synthesize(); API called correctly."""
    mock_client = MagicMock()
    mock_elevenlabs_cls.return_value = mock_client
    mock_client.text_to_speech.convert.return_value = [b"fake-audio-data"]

    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_api_key_env="ELEVENLABS_API_KEY",
        elevenlabs_voice_id="voice-abc",
        elevenlabs_model_id="eleven_v2",
        elevenlabs_stability=0.5,
        elevenlabs_similarity_boost=0.75,
    )

    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(config)

    # Client not created yet
    mock_elevenlabs_cls.assert_not_called()

    output = tmp_path / "speech.mp3"
    with patch("slidesonnet.tts.elevenlabs._get_audio_duration", return_value=3.5):
        duration = tts.synthesize("Hello world", output)

    # Client created lazily
    mock_elevenlabs_cls.assert_called_once_with(api_key="test-key-123")

    assert output.exists()
    assert output.read_bytes() == b"fake-audio-data"
    assert duration == 3.5

    mock_client.text_to_speech.convert.assert_called_once_with(
        text="Hello world",
        voice_id="voice-abc",
        model_id="eleven_v2",
        output_format="mp3_44100_128",
        voice_settings=ANY,
        request_options={"max_retries": 5},
    )


@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.elevenlabs.VoiceSettings", MagicMock)
@patch("slidesonnet.tts.elevenlabs.ElevenLabs")
def test_atomic_write_on_failure(mock_elevenlabs_cls, tmp_path):
    """Mid-stream failure leaves no file at output_path (atomic write)."""
    mock_client = MagicMock()
    mock_elevenlabs_cls.return_value = mock_client

    def _failing_generator():
        yield b"partial-data"
        raise ConnectionError("stream interrupted")

    mock_client.text_to_speech.convert.return_value = _failing_generator()

    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_api_key_env="ELEVENLABS_API_KEY",
        elevenlabs_voice_id="voice-abc",
    )

    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(config)
    output = tmp_path / "speech.mp3"

    with pytest.raises(ConnectionError, match="stream interrupted"):
        tts.synthesize("Hello world", output)

    # No file should exist at the output path
    assert not output.exists()
    # No temp files should remain
    assert not list(tmp_path.glob("*.tmp"))


def test_name():
    """name() works without API key or package."""
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_voice_id="v",
    )
    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(config)
    assert tts.name() == "elevenlabs"
