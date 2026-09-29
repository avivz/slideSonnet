"""Tests for the hashing module — and the golden cache-key table.

The golden table freezes the *exact* cached-audio filename each engine config
produces today. Every paid Inworld clip (and every slow Qwen3 clip) on disk is
addressed by these bytes, so a change to text normalisation, the key format, an
engine's ``cache_key()`` or the pace→speed mapping would silently orphan them all.
If a row here fails, the change is a cache migration — not a test to update.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from slidesonnet.hashing import (
    audio_cache_path_or_alt,
    audio_extension,
    audio_filename,
    audio_path,
    parse_audio_filename,
)
from slidesonnet.models import TTSConfig
from slidesonnet.tts.base import TTSEngine

_BASE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"


def _kokoro(**kw: object) -> Callable[[Path], TTSEngine]:
    def make(_tmp: Path) -> TTSEngine:
        from slidesonnet.tts.kokoro import KokoroTTS

        return KokoroTTS(**kw)  # type: ignore[arg-type]

    return make


def _paced(backend: str, pace: str, **cfg: object) -> Callable[[Path], TTSEngine]:
    """The engine synthesis builds for a paced utterance (pins pace → speed too)."""

    def make(_tmp: Path) -> TTSEngine:
        from slidesonnet.audio.synth import engine_for_pace

        tts = TTSConfig(backend=backend, **cfg)  # type: ignore[arg-type]
        return engine_for_pace(tts, pace, {})  # type: ignore[arg-type]

    return make


def _inworld(**cfg: object) -> Callable[[Path], TTSEngine]:
    def make(_tmp: Path) -> TTSEngine:
        from slidesonnet.tts.inworld import InworldTTS

        return InworldTTS(TTSConfig(backend="inworld", **cfg))  # type: ignore[arg-type]

    return make


_PROMPT = "<calm.pt>"  # stands for the absolute path of the golden prompt file


def _qwen3(*, prompt: bool = False, **kw: object) -> Callable[[Path], TTSEngine]:
    """A Qwen3 engine; the golden prompt file is always written, and with
    ``prompt=True`` it is also the engine's default ``voice_prompt``."""

    def make(tmp: Path) -> TTSEngine:
        from slidesonnet.tts.qwen3 import Qwen3TTS

        p = tmp / "calm.pt"
        p.write_bytes(b"golden-prompt-bytes")
        if prompt:
            kw["voice_prompt"] = str(p)
        return Qwen3TTS(**kw)  # type: ignore[arg-type]

    return make


# (text, voice, engine factory) -> exact cached filename. Computed once from the
# code as it stood when the table was written; never regenerate these.
GOLDEN: list[tuple[str, str | None, Callable[[Path], TTSEngine], str]] = [
    ("Hello, world.", None, _kokoro(), "f8c3bf62a9aa3e6f.kokoro.8746f0a4.wav"),
    (
        "Déjà vu — π ≈ 3.14",
        "af_heart",
        _kokoro(voice="af_heart"),
        "f2e0da5796d525e1.kokoro.387ace0b.wav",
    ),
    ("Hello, world.", None, _paced("kokoro", "fast"), "f8c3bf62a9aa3e6f.kokoro.97a3a8aa.wav"),
    (
        "Hello, world.",
        "Ashley",
        _inworld(inworld_voice="Ashley"),
        "1155b3b8d79c379a.inworld.b2ce7e91.mp3",
    ),
    ("Hello, world.", None, _paced("inworld", "slow"), "f8c3bf62a9aa3e6f.inworld.10d7a799.mp3"),
    ("Hello, world.", "Ryan", _qwen3(), "ed6902b3ccf73e32.qwen3.070c5297.wav"),
    (
        "Hello, world.",
        None,
        _qwen3(model=_BASE_MODEL, prompt=True),
        "f8c3bf62a9aa3e6f.qwen3.701c8f1b.wav",
    ),
    # A per-utterance .pt voice is keyed by the file's bytes, not its path.
    ("Hello, world.", _PROMPT, _qwen3(model=_BASE_MODEL), "dcfb77b59c04cb7b.qwen3.80dbcfff.wav"),
    ("Hello, world.", "Ryan", _qwen3(language="Chinese"), "ed6902b3ccf73e32.qwen3.2f03a4fc.wav"),
]


@pytest.mark.parametrize(
    ("text", "voice", "make_engine", "expected"),
    GOLDEN,
    ids=[
        "kokoro-default",
        "kokoro-voice-unicode",
        "kokoro-pace-fast",
        "inworld-voice",
        "inworld-pace-slow",
        "qwen3-speaker",
        "qwen3-clone-prompt",
        "qwen3-voice-file",
        "qwen3-language",
    ],
)
def test_golden_cache_filename(
    tmp_path: Path,
    text: str,
    voice: str | None,
    make_engine: Callable[[Path], TTSEngine],
    expected: str,
) -> None:
    from slidesonnet.tts import BACKENDS

    engine = make_engine(tmp_path)
    if voice == _PROMPT:
        voice = str(tmp_path / "calm.pt")
    name = audio_filename(text, engine.name(), engine.cache_key(), voice)
    assert name == expected
    assert audio_path(tmp_path, text, engine.name(), engine.cache_key(), voice) == tmp_path / name
    th, backend, ch = expected.split(".")[:3]
    assert parse_audio_filename(name) == (th, backend, ch)
    # The engine's own paid flag agrees with the registry clean/the editor use.
    assert engine.paid is BACKENDS[engine.name()].paid


def test_every_backend_has_an_extension_and_unknown_defaults_to_wav() -> None:
    from slidesonnet.hashing import BACKEND_EXTENSIONS
    from slidesonnet.tts import BACKENDS

    assert set(BACKENDS) <= set(BACKEND_EXTENSIONS)
    assert audio_extension("unknown_engine") == ".wav"


def test_hashing_does_not_import_the_tts_package() -> None:
    """Naming a cache file must not drag in the engine registry (and its imports)."""
    import subprocess
    import sys

    code = "import sys, slidesonnet.hashing\nprint('slidesonnet.tts' in sys.modules)\n"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("abcdef1234567890.kokoro.12345678.wav", ("abcdef1234567890", "kokoro", "12345678")),
        ("abcdef1234567890.inworld.12345678.mp3", ("abcdef1234567890", "inworld", "12345678")),
        ("abcdef1234567890_concat.wav", None),  # legacy pre-1.0 concat
        ("abcdef1234567890.wav", None),  # old plain-hash format
        ("abcdef1234567890.kokoro.12345678.ogg", None),  # unknown extension
    ],
)
def test_parse_audio_filename(filename: str, expected: tuple[str, str, str] | None) -> None:
    assert parse_audio_filename(filename) == expected


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
