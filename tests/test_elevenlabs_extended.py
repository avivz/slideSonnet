"""Extended tests for ElevenLabs TTS backend — covers cache_key, duration, voice override, caching."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.models import TTSConfig
from slidesonnet.tts.elevenlabs import ElevenLabsTTS


def _make_tts(
    voice_id: str = "voice-abc",
    model_id: str = "eleven_v2",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> ElevenLabsTTS:
    config = TTSConfig(
        backend="elevenlabs",
        elevenlabs_api_key_env="ELEVENLABS_API_KEY",
        elevenlabs_voice_id=voice_id,
        elevenlabs_model_id=model_id,
        elevenlabs_stability=stability,
        elevenlabs_similarity_boost=similarity_boost,
    )
    return ElevenLabsTTS(config)


class TestCacheKey:
    def test_format(self) -> None:
        tts = _make_tts()
        assert tts.cache_key() == "elevenlabs:voice-abc:eleven_v2:0.5:0.75"

    @pytest.mark.parametrize(
        "override",
        [
            {"voice_id": "other-voice"},
            {"model_id": "eleven_v3"},
            {"stability": 0.9},
            {"similarity_boost": 0.1},
        ],
    )
    def test_changes_with_config(self, override: dict[str, object]) -> None:
        default_key = _make_tts().cache_key()
        changed_key = _make_tts(**override).cache_key()
        assert changed_key != default_key


class TestGetAudioDuration:
    @patch("slidesonnet.video.composer.get_duration", return_value=4.2)
    def test_delegates_to_composer(self, mock_get_duration: MagicMock) -> None:
        from slidesonnet.tts.elevenlabs import _get_audio_duration

        result = _get_audio_duration(Path("/fake/audio.mp3"))
        mock_get_duration.assert_called_once_with(Path("/fake/audio.mp3"))
        assert result == 4.2


class TestSynthesizeVoiceOverride:
    @patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"})
    @patch("slidesonnet.tts.elevenlabs.VoiceSettings", MagicMock)
    @patch("slidesonnet.tts.elevenlabs.ElevenLabs")
    @patch("slidesonnet.tts.elevenlabs._get_audio_duration", return_value=1.0)
    def test_voice_param_overrides_default(
        self, _mock_dur: MagicMock, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.text_to_speech.convert.return_value = [b"data"]

        tts = _make_tts(voice_id="default-voice")
        tts.synthesize("Hi", tmp_path / "out.mp3", voice="override")

        call_kwargs = mock_client.text_to_speech.convert.call_args.kwargs
        assert call_kwargs["voice_id"] == "override"

    @patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"})
    @patch("slidesonnet.tts.elevenlabs.VoiceSettings", MagicMock)
    @patch("slidesonnet.tts.elevenlabs.ElevenLabs")
    @patch("slidesonnet.tts.elevenlabs._get_audio_duration", return_value=1.0)
    def test_voice_param_none_uses_default(
        self, _mock_dur: MagicMock, mock_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.text_to_speech.convert.return_value = [b"data"]

        tts = _make_tts(voice_id="default-voice")
        tts.synthesize("Hi", tmp_path / "out.mp3", voice=None)

        call_kwargs = mock_client.text_to_speech.convert.call_args.kwargs
        assert call_kwargs["voice_id"] == "default-voice"


class TestClientCaching:
    @patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"})
    @patch("slidesonnet.tts.elevenlabs.ElevenLabs")
    def test_client_created_once(self, mock_cls: MagicMock) -> None:
        mock_cls.return_value = MagicMock()
        tts = _make_tts()

        client1 = tts._ensure_client()
        client2 = tts._ensure_client()

        mock_cls.assert_called_once()
        assert client1 is client2
