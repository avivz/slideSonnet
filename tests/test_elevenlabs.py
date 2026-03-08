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


# -- Speed tests ------------------------------------------------------------


@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.elevenlabs.ElevenLabs")
def test_speed_passed_to_voice_settings(mock_elevenlabs_cls, tmp_path):
    """When speed != 1.0, it is passed to VoiceSettings."""
    mock_client = MagicMock()
    mock_elevenlabs_cls.return_value = mock_client
    mock_client.text_to_speech.convert.return_value = [b"audio"]

    mock_vs_cls = MagicMock()
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_voice_id="voice-abc",
        elevenlabs_speed=1.1,
    )

    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(config)

    output = tmp_path / "speech.mp3"
    with (
        patch("slidesonnet.tts.elevenlabs._get_audio_duration", return_value=2.0),
        patch("slidesonnet.tts.elevenlabs.VoiceSettings", mock_vs_cls),
    ):
        tts.synthesize("Hello", output)

    vs_kwargs = mock_vs_cls.call_args[1]
    assert vs_kwargs["speed"] == 1.1


@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key-123"})
@patch("slidesonnet.tts.elevenlabs.ElevenLabs")
def test_speed_default_not_in_voice_settings(mock_elevenlabs_cls, tmp_path):
    """When speed == 1.0 (default), speed is not passed to VoiceSettings."""
    mock_client = MagicMock()
    mock_elevenlabs_cls.return_value = mock_client
    mock_client.text_to_speech.convert.return_value = [b"audio"]

    mock_vs_cls = MagicMock()
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_voice_id="voice-abc",
    )

    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(config)

    output = tmp_path / "speech.mp3"
    with (
        patch("slidesonnet.tts.elevenlabs._get_audio_duration", return_value=2.0),
        patch("slidesonnet.tts.elevenlabs.VoiceSettings", mock_vs_cls),
    ):
        tts.synthesize("Hello", output)

    vs_kwargs = mock_vs_cls.call_args[1]
    assert "speed" not in vs_kwargs


def test_cache_key_with_speed():
    """cache_key includes speed when != 1.0."""
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_voice_id="v",
        elevenlabs_speed=1.1,
    )
    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(config)
    assert ":1.1" in tts.cache_key()


def test_cache_key_default_speed():
    """cache_key does not include speed when == 1.0."""
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_voice_id="v",
    )
    from slidesonnet.tts.elevenlabs import ElevenLabsTTS

    tts = ElevenLabsTTS(config)
    # Default speed (1.0) → key should end with similarity_boost, no trailing speed
    parts = tts.cache_key().split(":")
    assert len(parts) == 5  # elevenlabs:voice:model:stability:similarity_boost
