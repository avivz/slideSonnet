"""Qwen3-TTS backend — mocked unit tests.

The real model is multi-GB and needs a GPU/XPU, so every test here mocks
``qwen_tts`` (no download, no accelerator). The real-weights path is exercised
only by a local-only integration test behind the ``[qwen3]`` extra.
"""

from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from slidesonnet.exceptions import TTSError
from slidesonnet.tts.qwen3 import Qwen3TTS


@pytest.fixture
def fake_qwen3(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Patch the qwen_tts model, prompt item, and torch.load with fakes."""
    import numpy as np
    import torch

    fake_model = MagicMock(name="Qwen3Model")
    # 2400 samples @ 24 kHz = 0.1 s of audio.
    fake_model.generate_voice_clone.return_value = ([np.zeros(2400, dtype=np.float32)], 24000)
    model_cls = MagicMock(name="Qwen3TTSModel")
    model_cls.from_pretrained.return_value = fake_model

    monkeypatch.setattr("slidesonnet.tts.qwen3.Qwen3TTSModel", model_cls)
    monkeypatch.setattr("slidesonnet.tts.qwen3.VoiceClonePromptItem", MagicMock(name="VCP"))
    monkeypatch.setattr(torch, "load", lambda *a, **k: {"ref_code": [1], "ref_spk_embedding": [2]})
    return SimpleNamespace(model=fake_model, model_cls=model_cls)


def _prompt_file(tmp_path: Path) -> str:
    p = tmp_path / "voice_prompt_10s_calm.pt"
    p.write_bytes(b"fake-prompt-bytes")
    return str(p)


def _engine(tmp_path: Path, **kw: Any) -> Qwen3TTS:
    kw.setdefault("device", "cpu")  # skip the accelerator .to() path
    kw.setdefault("voice_prompt", _prompt_file(tmp_path))
    return Qwen3TTS(**kw)


def test_synthesize_writes_wav_and_returns_duration(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    engine = _engine(tmp_path)
    out = tmp_path / "out" / "clip.wav"

    duration = engine.synthesize("Hello in my own voice.", out)

    assert out.is_file()
    assert duration == pytest.approx(0.1, abs=1e-3)
    with wave.open(str(out), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 24000
        assert wf.getnframes() == 2400


def test_model_loaded_once_and_kept_warm(fake_qwen3: SimpleNamespace, tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.synthesize("one", tmp_path / "a.wav")
    engine.synthesize("two", tmp_path / "b.wav")
    # from_pretrained is the expensive load — it must happen exactly once.
    assert fake_qwen3.model_cls.from_pretrained.call_count == 1
    assert fake_qwen3.model.generate_voice_clone.call_count == 2


def test_missing_package_raises_clean_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("slidesonnet.tts.qwen3.Qwen3TTSModel", None)
    engine = _engine(tmp_path)
    with pytest.raises(TTSError, match="qwen-tts package not installed"):
        engine.synthesize("hi", tmp_path / "x.wav")


def test_missing_voice_prompt_file_raises(fake_qwen3: SimpleNamespace, tmp_path: Path) -> None:
    engine = Qwen3TTS(device="cpu", voice_prompt=str(tmp_path / "nope.pt"))
    out = tmp_path / "x.wav"
    with pytest.raises(TTSError, match="voice prompt not found"):
        engine.synthesize("hi", out)
    assert not out.exists()


def test_no_voice_prompt_configured_raises_before_loading_model(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    engine = Qwen3TTS(device="cpu", voice_prompt="")
    with pytest.raises(TTSError, match="needs a voice prompt"):
        engine.synthesize("hi", tmp_path / "x.wav")
    fake_qwen3.model_cls.from_pretrained.assert_not_called()


def test_empty_audio_raises(fake_qwen3: SimpleNamespace, tmp_path: Path) -> None:
    fake_qwen3.model.generate_voice_clone.return_value = ([], 24000)
    engine = _engine(tmp_path)
    out = tmp_path / "x.wav"
    with pytest.raises(TTSError, match="produced no audio"):
        engine.synthesize("hi", out)
    assert not out.exists()


def test_generate_failure_leaves_no_partial_or_temp_file(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    fake_qwen3.model.generate_voice_clone.side_effect = RuntimeError("xpu blew up")
    engine = _engine(tmp_path)
    out = tmp_path / "out" / "x.wav"
    with pytest.raises(RuntimeError):
        engine.synthesize("hi", out)
    assert not out.exists()
    # No leftover temp file in the target directory.
    assert list(out.parent.glob("*")) == []


def test_cache_key_folds_prompt_content_hash(tmp_path: Path) -> None:
    prompt = tmp_path / "v.pt"
    prompt.write_bytes(b"version-one")
    engine = Qwen3TTS(device="cpu", model="repoX", voice_prompt=str(prompt))
    key1 = engine.cache_key()
    assert key1.startswith("qwen3:repoX:")

    # Editing the prompt's content changes the cache key (clips go stale).
    prompt.write_bytes(b"version-two-different")
    assert engine.cache_key() != key1


def test_cache_key_stable_without_prompt(tmp_path: Path) -> None:
    engine = Qwen3TTS(device="cpu", model="repoY", voice_prompt="")
    assert engine.cache_key() == "qwen3:repoY"


def test_voice_introspection_does_not_load_model(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    engine = _engine(tmp_path, voice_prompt=str(tmp_path / "aviv_calm.pt"))
    assert engine.list_voices() == ()
    # default_voice shows the prompt's stem, never a full path.
    assert engine.default_voice() == "aviv_calm"
    assert engine.paid is False
    fake_qwen3.model_cls.from_pretrained.assert_not_called()


def test_create_tts_is_cheap_and_does_not_load_model(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    from slidesonnet.models import TTSConfig
    from slidesonnet.tts import create_tts

    engine = create_tts(
        TTSConfig(backend="qwen3", qwen3_voice_prompt=_prompt_file(tmp_path), qwen3_device="cpu")
    )
    assert engine.name() == "qwen3"
    fake_qwen3.model_cls.from_pretrained.assert_not_called()
