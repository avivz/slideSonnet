"""Qwen3-TTS backend — mocked unit tests.

The real model is multi-GB and needs a GPU/XPU, so every test here mocks
``qwen_tts`` (no download, no accelerator). The real-weights path is exercised
only by a local-only integration test behind the ``[qwen3]`` extra.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

# These mocked tests still need real numpy/torch (the engine flattens waveforms
# with numpy and the fixture patches torch.load). Both ship with the heavy
# [qwen3]/[kokoro] extras, not [dev], so CI (which installs [dev] only) skips the
# whole module — it runs wherever those deps are present (local dev).
pytest.importorskip("numpy")
pytest.importorskip("torch")

from slidesonnet.exceptions import TTSError  # noqa: E402
from slidesonnet.tts.qwen3 import Qwen3TTS  # noqa: E402


@pytest.fixture
def fake_qwen3(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Patch the qwen_tts model, prompt item, and torch.load with fakes."""
    import numpy as np
    import torch

    fake_model = MagicMock(name="Qwen3Model")
    # 2400 samples @ 24 kHz = 0.1 s of audio.
    fake_model.generate_voice_clone.return_value = ([np.zeros(2400, dtype=np.float32)], 24000)
    fake_model.generate_custom_voice.return_value = ([np.zeros(2400, dtype=np.float32)], 24000)
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


_BASE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
_CUSTOM_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"


def _engine(tmp_path: Path, **kw: Any) -> Qwen3TTS:
    """A clone-mode (Base) engine — the own-voice path these tests exercise."""
    kw.setdefault("device", "cpu")  # skip the accelerator .to() path
    kw.setdefault("model", _BASE_MODEL)
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


def test_model_cache_shared_across_engine_instances(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    # The editor recreates the engine per background job; the heavy model must
    # load once per process, not once per job.
    _engine(tmp_path).synthesize("one", tmp_path / "a.wav")
    _engine(tmp_path).synthesize("two", tmp_path / "b.wav")
    assert fake_qwen3.model_cls.from_pretrained.call_count == 1


def test_is_warm_flips_after_first_load(fake_qwen3: SimpleNamespace, tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    assert engine.is_warm() is False  # cold: a heavy load is still owed
    engine.synthesize("hello", tmp_path / "a.wav")
    assert engine.is_warm() is True
    # a fresh instance for the same (model, device) is already warm
    assert _engine(tmp_path).is_warm() is True


def test_missing_package_raises_clean_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("slidesonnet.tts.qwen3.Qwen3TTSModel", None)
    engine = _engine(tmp_path)
    with pytest.raises(TTSError, match="qwen-tts package not installed"):
        engine.synthesize("hi", tmp_path / "x.wav")


def test_missing_voice_prompt_file_raises(fake_qwen3: SimpleNamespace, tmp_path: Path) -> None:
    engine = Qwen3TTS(model=_BASE_MODEL, device="cpu", voice_prompt=str(tmp_path / "nope.pt"))
    out = tmp_path / "x.wav"
    with pytest.raises(TTSError, match="voice prompt not found"):
        engine.synthesize("hi", out)
    assert not out.exists()


def test_no_voice_prompt_configured_raises_before_loading_model(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    engine = Qwen3TTS(model=_BASE_MODEL, device="cpu", voice_prompt="")
    with pytest.raises(TTSError, match="needs a voice prompt"):
        engine.synthesize("hi", tmp_path / "x.wav")
    fake_qwen3.model_cls.from_pretrained.assert_not_called()


# --- custom-voice (built-in speakers) mode ------------------------------------


def test_custom_voice_lists_shipped_speakers_without_loading_model(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    from slidesonnet.tts.qwen3 import CUSTOM_VOICE_SPEAKERS

    engine = Qwen3TTS(model=_CUSTOM_MODEL, device="cpu")
    assert engine.list_voices() == CUSTOM_VOICE_SPEAKERS
    assert "Vivian" in engine.list_voices()
    assert engine.default_voice() == "Dylan"
    fake_qwen3.model_cls.from_pretrained.assert_not_called()


def test_custom_voice_synthesizes_without_a_voice_prompt(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    # The original bug: CustomVoice must not demand a .pt clone prompt.
    engine = Qwen3TTS(model=_CUSTOM_MODEL, device="cpu", voice_prompt="")
    out = tmp_path / "clip.wav"

    duration = engine.synthesize("Hello from a shipped voice.", out)

    assert out.is_file() and duration == pytest.approx(0.1, abs=1e-3)
    fake_qwen3.model.generate_voice_clone.assert_not_called()
    _, kwargs = fake_qwen3.model.generate_custom_voice.call_args
    assert kwargs["speaker"] == "Dylan"  # the engine default


def test_custom_voice_uses_the_picked_speaker(fake_qwen3: SimpleNamespace, tmp_path: Path) -> None:
    engine = Qwen3TTS(model=_CUSTOM_MODEL, device="cpu")
    engine.synthesize("Pick me.", tmp_path / "c.wav", voice="Ryan")
    _, kwargs = fake_qwen3.model.generate_custom_voice.call_args
    assert kwargs["speaker"] == "Ryan"


def test_custom_voice_falls_back_for_an_unknown_speaker(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    """A foreign voice id (e.g. a Kokoro voice that leaked through the deck's
    default-voice) falls back to the default speaker instead of crashing the real
    model with 'Unsupported speakers'."""
    engine = Qwen3TTS(model=_CUSTOM_MODEL, device="cpu")
    engine.synthesize("Hi.", tmp_path / "c.wav", voice="af_heart")
    _, kwargs = fake_qwen3.model.generate_custom_voice.call_args
    assert kwargs["speaker"] == "Dylan"  # unknown speaker → default, not "af_heart"


def test_custom_voice_speaker_match_is_case_insensitive(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    """A known speaker in any case resolves to its canonical form the model wants."""
    engine = Qwen3TTS(model=_CUSTOM_MODEL, device="cpu")
    engine.synthesize("Hi.", tmp_path / "c.wav", voice="ryan")
    _, kwargs = fake_qwen3.model.generate_custom_voice.call_args
    assert kwargs["speaker"] == "Ryan"


def test_warm_loads_the_model_without_synthesizing(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    engine = Qwen3TTS(model=_CUSTOM_MODEL, device="cpu")
    assert engine.is_warm() is False
    engine.warm()
    assert engine.is_warm() is True
    assert fake_qwen3.model_cls.from_pretrained.call_count == 1
    # No clip was generated by warming alone.
    fake_qwen3.model.generate_custom_voice.assert_not_called()
    # Idempotent: warming again reuses the process-wide cache.
    engine.warm()
    assert fake_qwen3.model_cls.from_pretrained.call_count == 1


def test_synthesize_raises_and_writes_nothing_when_cancelled(
    fake_qwen3: SimpleNamespace, tmp_path: Path
) -> None:
    from slidesonnet.cancellation import cancel_scope
    from slidesonnet.exceptions import GenerationCancelled

    event = threading.Event()
    event.set()  # already cancelled when generation "returns"
    engine = Qwen3TTS(model=_CUSTOM_MODEL, device="cpu")
    out = tmp_path / "x.wav"
    with cancel_scope(event), pytest.raises(GenerationCancelled):
        engine.synthesize("hi", out)
    assert not out.exists()  # the (truncated) audio is discarded, not cached


def test_cancellable_injects_stopping_criteria_then_restores(
    fake_qwen3: SimpleNamespace,
) -> None:
    from slidesonnet.cancellation import cancel_scope
    from slidesonnet.tts.qwen3 import _cancellable

    model = fake_qwen3.model
    original = model.model.talker.generate
    event = threading.Event()
    with cancel_scope(event):
        with _cancellable(model):
            assert model.model.talker.generate is not original  # wrapped while active
            model.model.talker.generate("ids")  # forwards with a stopping criterion
            _, kwargs = original.call_args
            assert "stopping_criteria" in kwargs
    assert model.model.talker.generate is original  # restored on exit (event unset → no raise)


def test_cancellable_is_a_noop_without_a_token(fake_qwen3: SimpleNamespace) -> None:
    from slidesonnet.tts.qwen3 import _cancellable

    model = fake_qwen3.model
    original = model.model.talker.generate
    with _cancellable(model):  # no cancel_scope → token is None
        assert model.model.talker.generate is original  # left untouched


def test_custom_voice_cache_key_is_just_the_model(tmp_path: Path) -> None:
    # Per-utterance speaker rides the clip's text hash, so the engine config key
    # only needs the model repo (the speaker set is fixed by it).
    engine = Qwen3TTS(model=_CUSTOM_MODEL, device="cpu")
    assert engine.cache_key() == f"qwen3:{_CUSTOM_MODEL}"


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


# --- real weights (local-only; never in CI) ----------------------------------

_REAL_PROMPT = os.environ.get("SLIDESONNET_QWEN3_PROMPT", "")


@pytest.mark.integration
@pytest.mark.skipif(
    importlib.util.find_spec("qwen_tts") is None or not _REAL_PROMPT,
    reason="needs the [qwen3] extra and SLIDESONNET_QWEN3_PROMPT set to a real .pt prompt",
)
def test_real_weights_smoke(tmp_path: Path) -> None:
    """Downloads the real model and clones a real voice — heavy, opt-in, local-only.

    Run with the package installed and a prompt artifact, e.g.:
        SLIDESONNET_QWEN3_PROMPT=dev/voice-profile/aviv_calm.pt \
            pytest -m integration tests/test_qwen3.py -k real_weights
    """
    device = os.environ.get("SLIDESONNET_QWEN3_DEVICE", "cpu")
    engine = Qwen3TTS(device=device, voice_prompt=_REAL_PROMPT)
    out = tmp_path / "real.wav"
    duration = engine.synthesize("This is a real own-voice smoke test.", out)
    assert out.is_file() and duration > 0
    with wave.open(str(out), "rb") as wf:
        assert wf.getnframes() > 0
