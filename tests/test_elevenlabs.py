"""Tests for ElevenLabs TTS backend (mocked API)."""

import os
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.models import TTSConfig


def test_missing_api_key(monkeypatch):
    """Should exit if API key env var is not set."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_api_key_env="ELEVENLABS_API_KEY",
        elevenlabs_voice_id="test-voice",
    )

    with pytest.raises(SystemExit):
        from slidesonnet.tts.elevenlabs import ElevenLabsTTS

        ElevenLabsTTS(config)


@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.elevenlabs.ElevenLabs")
def test_synthesize_calls_api(mock_elevenlabs_cls, tmp_path):
    """Should call ElevenLabs API and write audio to file."""
    # Setup mock
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

    output = tmp_path / "speech.mp3"
    with patch("slidesonnet.tts.elevenlabs._get_audio_duration", return_value=3.5):
        duration = tts.synthesize("Hello world", output)

    assert output.exists()
    assert output.read_bytes() == b"fake-audio-data"
    assert duration == 3.5

    mock_client.text_to_speech.convert.assert_called_once_with(
        text="Hello world",
        voice_id="voice-abc",
        model_id="eleven_v2",
        output_format="mp3_44100_128",
    )


@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"})
@patch("slidesonnet.tts.elevenlabs.ElevenLabs", None)
def test_missing_package(capsys):
    """Should exit if elevenlabs package is not installed."""
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_api_key_env="ELEVENLABS_API_KEY",
        elevenlabs_voice_id="test-voice",
    )

    with pytest.raises(SystemExit):
        from slidesonnet.tts.elevenlabs import ElevenLabsTTS

        ElevenLabsTTS(config)

    captured = capsys.readouterr()
    assert "elevenlabs package not installed" in captured.err


@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"})
@patch("slidesonnet.tts.elevenlabs.ElevenLabs")
def test_name(mock_cls):
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_api_key_env="ELEVENLABS_API_KEY",
        elevenlabs_voice_id="v",
    )
    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(config)
    assert tts.name() == "elevenlabs"
