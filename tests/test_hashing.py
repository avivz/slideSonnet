"""Tests for the hashing module."""

from pathlib import Path

from slidesonnet.hashing import (
    audio_extension,
    audio_filename,
    audio_path,
    concat_filename,
    config_hash,
    parse_audio_filename,
    text_hash,
)


class TestTextHash:
    def test_deterministic(self):
        assert text_hash("hello") == text_hash("hello")

    def test_16_chars(self):
        assert len(text_hash("hello")) == 16

    def test_hex(self):
        h = text_hash("hello")
        int(h, 16)  # should not raise

    def test_different_text_different_hash(self):
        assert text_hash("hello") != text_hash("world")

    def test_voice_changes_hash(self):
        assert text_hash("hello") != text_hash("hello", voice="alice")

    def test_different_voices_different_hash(self):
        assert text_hash("hello", "alice") != text_hash("hello", "bob")

    def test_none_voice_same_as_no_voice(self):
        assert text_hash("hello") == text_hash("hello", voice=None)


class TestConfigHash:
    def test_deterministic(self):
        assert config_hash("piper:model:0") == config_hash("piper:model:0")

    def test_8_chars(self):
        assert len(config_hash("piper:model:0")) == 8

    def test_different_keys_different_hash(self):
        assert config_hash("piper:model:0") != config_hash("elevenlabs:voice:model:0.5:0.75")


class TestAudioExtension:
    def test_piper(self):
        assert audio_extension("piper") == ".wav"

    def test_elevenlabs(self):
        assert audio_extension("elevenlabs") == ".mp3"

    def test_unknown_defaults_to_wav(self):
        assert audio_extension("unknown_engine") == ".wav"


class TestAudioFilename:
    def test_format(self):
        name = audio_filename("hello", "piper", "piper:model:0")
        parts = name.split(".")
        assert len(parts) == 4
        assert parts[1] == "piper"
        assert parts[3] == "wav"

    def test_elevenlabs_format(self):
        name = audio_filename("hello", "elevenlabs", "elevenlabs:voice:model:0.5:0.75")
        parts = name.split(".")
        assert len(parts) == 4
        assert parts[1] == "elevenlabs"
        assert parts[3] == "mp3"

    def test_text_hash_part(self):
        name = audio_filename("hello", "piper", "piper:model:0")
        th = name.split(".")[0]
        assert th == text_hash("hello")

    def test_config_hash_part(self):
        name = audio_filename("hello", "piper", "piper:model:0")
        ch = name.split(".")[2]
        assert ch == config_hash("piper:model:0")

    def test_voice_affects_filename(self):
        name1 = audio_filename("hello", "piper", "piper:model:0")
        name2 = audio_filename("hello", "piper", "piper:model:0", voice="alice")
        assert name1 != name2

    def test_different_backend_same_text(self):
        name1 = audio_filename("hello", "piper", "piper:model:0")
        name2 = audio_filename("hello", "elevenlabs", "elevenlabs:voice:model:0.5:0.75")
        # Backend differs, text_hash is the same (no voice)
        assert name1.split(".")[0] == name2.split(".")[0]
        assert name1.split(".")[1] != name2.split(".")[1]


class TestAudioPath:
    def test_returns_path_in_audio_dir(self):
        p = audio_path(Path("/cache/audio"), "hello", "piper", "piper:model:0")
        assert p.parent == Path("/cache/audio")

    def test_filename_matches(self):
        p = audio_path(Path("/cache/audio"), "hello", "piper", "piper:model:0")
        assert p.name == audio_filename("hello", "piper", "piper:model:0")


class TestConcatFilename:
    def test_ends_with_concat_wav(self):
        name = concat_filename([Path("/a.wav"), Path("/b.wav")])
        assert name.endswith("_concat.wav")

    def test_deterministic(self):
        paths = [Path("/a.wav"), Path("/b.wav")]
        assert concat_filename(paths) == concat_filename(paths)

    def test_different_paths_different_name(self):
        name1 = concat_filename([Path("/a.wav"), Path("/b.wav")])
        name2 = concat_filename([Path("/c.wav"), Path("/d.wav")])
        assert name1 != name2


class TestParseAudioFilename:
    def test_new_format(self):
        result = parse_audio_filename("abcdef1234567890.piper.12345678.wav")
        assert result == ("abcdef1234567890", "piper", "12345678")

    def test_elevenlabs(self):
        result = parse_audio_filename("abcdef1234567890.elevenlabs.12345678.mp3")
        assert result == ("abcdef1234567890", "elevenlabs", "12345678")

    def test_concat_returns_none(self):
        assert parse_audio_filename("abcdef1234567890_concat.wav") is None

    def test_old_format_returns_none(self):
        assert parse_audio_filename("abcdef1234567890.wav") is None

    def test_unknown_ext_returns_none(self):
        assert parse_audio_filename("abcdef1234567890.piper.12345678.ogg") is None

    def test_roundtrip(self):
        name = audio_filename("hello world", "piper", "piper:model:0", voice="alice")
        parsed = parse_audio_filename(name)
        assert parsed is not None
        th, backend, ch = parsed
        assert th == text_hash("hello world", "alice")
        assert backend == "piper"
        assert ch == config_hash("piper:model:0")

    def test_roundtrip_elevenlabs(self):
        name = audio_filename(
            "hello world", "elevenlabs", "elevenlabs:voice:model:0.5:0.75", voice="alice"
        )
        parsed = parse_audio_filename(name)
        assert parsed is not None
        th, backend, ch = parsed
        assert th == text_hash("hello world", "alice")
        assert backend == "elevenlabs"
        assert ch == config_hash("elevenlabs:voice:model:0.5:0.75")
