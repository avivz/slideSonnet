"""Tests for the hashing module."""

from pathlib import Path

from slidesonnet.hashing import (
    audio_cache_is_fresh,
    audio_cache_path_or_alt,
    audio_extension,
    audio_filename,
    audio_path,
    concat_filename,
    config_hash,
    migrate_and_check_audio_cache,
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
        assert config_hash("kokoro:model:0") == config_hash("kokoro:model:0")

    def test_8_chars(self):
        assert len(config_hash("kokoro:model:0")) == 8

    def test_different_keys_different_hash(self):
        assert config_hash("kokoro:model:0") != config_hash("elevenlabs:voice:model:0.5:0.75")


class TestAudioExtension:
    def test_kokoro(self):
        assert audio_extension("kokoro") == ".wav"

    def test_elevenlabs(self):
        assert audio_extension("elevenlabs") == ".mp3"

    def test_unknown_defaults_to_wav(self):
        assert audio_extension("unknown_engine") == ".wav"


class TestAudioFilename:
    def test_format(self):
        name = audio_filename("hello", "kokoro", "kokoro:model:0")
        parts = name.split(".")
        assert len(parts) == 4
        assert parts[1] == "kokoro"
        assert parts[3] == "wav"

    def test_elevenlabs_format(self):
        name = audio_filename("hello", "elevenlabs", "elevenlabs:voice:model:0.5:0.75")
        parts = name.split(".")
        assert len(parts) == 4
        assert parts[1] == "elevenlabs"
        assert parts[3] == "mp3"

    def test_text_hash_part(self):
        name = audio_filename("hello", "kokoro", "kokoro:model:0")
        th = name.split(".")[0]
        assert th == text_hash("hello")

    def test_config_hash_part(self):
        name = audio_filename("hello", "kokoro", "kokoro:model:0")
        ch = name.split(".")[2]
        assert ch == config_hash("kokoro:model:0")

    def test_voice_affects_filename(self):
        name1 = audio_filename("hello", "kokoro", "kokoro:model:0")
        name2 = audio_filename("hello", "kokoro", "kokoro:model:0", voice="alice")
        assert name1 != name2

    def test_different_backend_same_text(self):
        name1 = audio_filename("hello", "kokoro", "kokoro:model:0")
        name2 = audio_filename("hello", "elevenlabs", "elevenlabs:voice:model:0.5:0.75")
        # Backend differs, text_hash is the same (no voice)
        assert name1.split(".")[0] == name2.split(".")[0]
        assert name1.split(".")[1] != name2.split(".")[1]


class TestAudioPath:
    def test_returns_path_in_audio_dir(self):
        p = audio_path(Path("/cache/audio"), "hello", "kokoro", "kokoro:model:0")
        assert p.parent == Path("/cache/audio")

    def test_filename_matches(self):
        p = audio_path(Path("/cache/audio"), "hello", "kokoro", "kokoro:model:0")
        assert p.name == audio_filename("hello", "kokoro", "kokoro:model:0")


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
        result = parse_audio_filename("abcdef1234567890.kokoro.12345678.wav")
        assert result == ("abcdef1234567890", "kokoro", "12345678")

    def test_elevenlabs(self):
        result = parse_audio_filename("abcdef1234567890.elevenlabs.12345678.mp3")
        assert result == ("abcdef1234567890", "elevenlabs", "12345678")

    def test_concat_returns_none(self):
        assert parse_audio_filename("abcdef1234567890_concat.wav") is None

    def test_old_format_returns_none(self):
        assert parse_audio_filename("abcdef1234567890.wav") is None

    def test_unknown_ext_returns_none(self):
        assert parse_audio_filename("abcdef1234567890.kokoro.12345678.ogg") is None

    def test_roundtrip(self):
        name = audio_filename("hello world", "kokoro", "kokoro:model:0", voice="alice")
        parsed = parse_audio_filename(name)
        assert parsed is not None
        th, backend, ch = parsed
        assert th == text_hash("hello world", "alice")
        assert backend == "kokoro"
        assert ch == config_hash("kokoro:model:0")

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


class TestAudioCacheIsFresh:
    def test_existing_non_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "clip.wav"
        p.write_bytes(b"audio")
        assert audio_cache_is_fresh(p) is True

    def test_missing_file_no_alternate(self, tmp_path: Path) -> None:
        assert audio_cache_is_fresh(tmp_path / "clip.wav") is False

    def test_empty_file_is_stale(self, tmp_path: Path) -> None:
        p = tmp_path / "clip.wav"
        p.write_bytes(b"")
        assert audio_cache_is_fresh(p) is False

    def test_alternate_extension_counts(self, tmp_path: Path) -> None:
        (tmp_path / "clip.mp3").write_bytes(b"audio")
        assert audio_cache_is_fresh(tmp_path / "clip.wav") is True

    def test_empty_primary_with_non_empty_alternate(self, tmp_path: Path) -> None:
        (tmp_path / "clip.wav").write_bytes(b"")
        (tmp_path / "clip.mp3").write_bytes(b"audio")
        assert audio_cache_is_fresh(tmp_path / "clip.wav") is True

    def test_empty_alternate_is_stale(self, tmp_path: Path) -> None:
        (tmp_path / "clip.mp3").write_bytes(b"")
        assert audio_cache_is_fresh(tmp_path / "clip.wav") is False

    def test_read_only_never_renames(self, tmp_path: Path) -> None:
        alt = tmp_path / "clip.mp3"
        alt.write_bytes(b"audio")
        audio_cache_is_fresh(tmp_path / "clip.wav")
        assert alt.exists()
        assert not (tmp_path / "clip.wav").exists()


class TestAudioCachePathOrAlt:
    def test_returns_primary_when_present(self, tmp_path: Path) -> None:
        p = tmp_path / "clip.wav"
        p.write_bytes(b"audio")
        assert audio_cache_path_or_alt(p) == p

    def test_returns_alternate_when_primary_missing(self, tmp_path: Path) -> None:
        alt = tmp_path / "clip.mp3"
        alt.write_bytes(b"audio")
        assert audio_cache_path_or_alt(tmp_path / "clip.wav") == alt

    def test_returns_none_when_nothing_cached(self, tmp_path: Path) -> None:
        assert audio_cache_path_or_alt(tmp_path / "clip.wav") is None

    def test_ignores_empty_files(self, tmp_path: Path) -> None:
        (tmp_path / "clip.wav").write_bytes(b"")
        (tmp_path / "clip.mp3").write_bytes(b"")
        assert audio_cache_path_or_alt(tmp_path / "clip.wav") is None

    def test_read_only_never_renames(self, tmp_path: Path) -> None:
        alt = tmp_path / "clip.mp3"
        alt.write_bytes(b"audio")
        audio_cache_path_or_alt(tmp_path / "clip.wav")
        assert alt.exists()
        assert not (tmp_path / "clip.wav").exists()


class TestMigrateAndCheckAudioCache:
    def test_existing_file_true_no_migration(self, tmp_path: Path) -> None:
        p = tmp_path / "clip.wav"
        p.write_bytes(b"audio")
        assert migrate_and_check_audio_cache(p) is True
        assert p.read_bytes() == b"audio"

    def test_missing_with_no_alternate_false(self, tmp_path: Path) -> None:
        assert migrate_and_check_audio_cache(tmp_path / "clip.wav") is False

    def test_migrates_alternate_to_requested_extension(self, tmp_path: Path) -> None:
        p = tmp_path / "clip.wav"
        alt = tmp_path / "clip.mp3"
        alt.write_bytes(b"mp3-audio")
        assert migrate_and_check_audio_cache(p) is True
        assert p.exists()
        assert not alt.exists()
        assert p.read_bytes() == b"mp3-audio"

    def test_migrates_wav_to_mp3_direction(self, tmp_path: Path) -> None:
        p = tmp_path / "clip.mp3"
        (tmp_path / "clip.wav").write_bytes(b"wav-audio")
        assert migrate_and_check_audio_cache(p) is True
        assert p.read_bytes() == b"wav-audio"
        assert not (tmp_path / "clip.wav").exists()

    def test_empty_alternate_not_migrated(self, tmp_path: Path) -> None:
        alt = tmp_path / "clip.mp3"
        alt.write_bytes(b"")
        assert migrate_and_check_audio_cache(tmp_path / "clip.wav") is False
        assert alt.exists()  # left untouched

    def test_empty_primary_falls_back_to_alternate(self, tmp_path: Path) -> None:
        p = tmp_path / "clip.wav"
        p.write_bytes(b"")
        (tmp_path / "clip.mp3").write_bytes(b"audio")
        assert migrate_and_check_audio_cache(p) is True
        assert p.read_bytes() == b"audio"
