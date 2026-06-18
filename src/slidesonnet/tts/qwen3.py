"""Qwen3-TTS backend — local, free, own-voice text-to-speech (Apache-2.0).

Qwen3-TTS is a language model over audio tokens that clones a speaker from a
tiny precomputed *voice-clone prompt* (a ``.pt`` holding codec ``ref_code`` +
speaker x-vector). Given that prompt it narrates arbitrary text in the cloned
voice — the expressive / own-voice path Kokoro can't do.

It is **free but heavy**: on the laptop's Intel iGPU (XPU path) generation runs
~4x slower than real-time, so it is an offline-quality engine, not a real-time
one (``BackendSpec.realtime=False`` keeps it out of unattended auto-generate).

The model (~several GB) auto-downloads from the Hugging Face hub on first use,
so the engine loads it **lazily** and keeps it **warm** across clips — the
constructor and the voice-introspection methods never touch it, because the
editor calls them on every render tick.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Any

from slidesonnet.exceptions import TTSError
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

# Lazy, optional import (the [qwen3] extra). Module-level aliases so tests can
# @patch them; None when the package isn't installed.
_Qwen3TTSModel: Any
_VoiceClonePromptItem: Any
try:
    from qwen_tts import Qwen3TTSModel as _Qwen3Import
    from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem as _VCPImport

    _Qwen3TTSModel = _Qwen3Import
    _VoiceClonePromptItem = _VCPImport
except ImportError:
    _Qwen3TTSModel = None
    _VoiceClonePromptItem = None

Qwen3TTSModel: Any = _Qwen3TTSModel
VoiceClonePromptItem: Any = _VoiceClonePromptItem

# Process-wide model cache, keyed by (model_repo, device). The editor creates a
# fresh engine per synthesis call (and per background job), so without a cache
# the multi-GB model would reload every clip; this keeps it warm for the life of
# the process — the single most important perf property for the editor.
_MODEL_CACHE: dict[tuple[str, str], Any] = {}


class Qwen3TTS(TTSEngine):
    paid = False

    def __init__(
        self,
        model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        device: str = "xpu",
        voice_prompt: str = "",
        language: str = "English",
    ) -> None:
        self.model_repo = model
        self.device = device
        self.voice_prompt = voice_prompt
        self.language = language
        self._model: Any = None
        self._prompts: dict[str, Any] = {}  # prompt path -> [VoiceClonePromptItem]

    def is_warm(self) -> bool:
        """True once this (model, device) is loaded in the process — see base."""
        return (self.model_repo, self.device) in _MODEL_CACHE

    def _ensure_model(self) -> Any:
        """Load the model once per process, on first synthesis, and keep it warm."""
        if self._model is not None:
            return self._model
        cache_key = (self.model_repo, self.device)
        cached = _MODEL_CACHE.get(cache_key)
        if cached is not None:
            self._model = cached
            return cached
        if Qwen3TTSModel is None:
            raise TTSError(
                "qwen-tts package not installed. Install with: pip install slidesonnet[qwen3]"
            )
        import torch  # rides along with the [qwen3] extra

        logger.info("Loading Qwen3-TTS model %s on %s ...", self.model_repo, self.device)
        # Load on CPU then move to the accelerator with bf16 — the working recipe
        # on the Intel iGPU (never device_map, never fp16); see dev/voice-profile.
        model = Qwen3TTSModel.from_pretrained(self.model_repo, dtype=torch.bfloat16)
        if self.device != "cpu":
            model.model.to(f"{self.device}:0")
            model.device = next(model.model.parameters()).device
        _MODEL_CACHE[cache_key] = model
        self._model = model
        return model

    def _load_prompt(self, prompt_path: str) -> Any:
        """Load (and cache) a voice-clone prompt artifact from a ``.pt`` file."""
        cached = self._prompts.get(prompt_path)
        if cached is not None:
            return cached
        path = Path(prompt_path)
        if not path.is_file():
            raise TTSError(f"Qwen3 voice prompt not found: {prompt_path}")
        import torch

        data = torch.load(path, weights_only=True)
        prompt = [VoiceClonePromptItem(**data)]
        self._prompts[prompt_path] = prompt
        return prompt

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path = voice if voice else self.voice_prompt
        if not prompt_path:
            raise TTSError(
                "Qwen3 needs a voice prompt — set [tts.qwen3] voice_prompt to a .pt "
                "clone artifact (see dev/voice-profile), or give the utterance a voice."
            )
        model = self._ensure_model()
        prompt = self._load_prompt(prompt_path)

        wavs, sample_rate = model.generate_voice_clone(
            text=text, language=self.language, voice_clone_prompt=prompt
        )
        samples = _to_float_samples(wavs[0]) if len(wavs) else []
        if not samples:
            raise TTSError(f"qwen3 produced no audio for text: {text[:60]!r}")

        sr = int(sample_rate)
        _write_wav(output_path, samples, sr)
        return len(samples) / sr

    def name(self) -> str:
        return "qwen3"

    def cache_key(self) -> str:
        """Identify the config: model + a content hash of the default voice prompt.

        Hashing the prompt's *content* (not its path) means editing the clone
        artifact invalidates cached audio, while moving/renaming the file does
        not churn the cache.
        """
        key = f"qwen3:{self.model_repo}"
        digest = _prompt_content_hash(self.voice_prompt)
        if digest:
            key += f":{digest}"
        return key

    def default_voice(self) -> str | None:
        """Display name for the deck-default voice — the prompt's stem, not a path."""
        return Path(self.voice_prompt).stem if self.voice_prompt else None


def _prompt_content_hash(voice_prompt: str) -> str:
    """8-char content hash of a voice-prompt file ("" if missing/unset)."""
    if not voice_prompt:
        return ""
    path = Path(voice_prompt)
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def _to_float_samples(wav: Any) -> list[float]:
    """Flatten a Qwen3 waveform (torch tensor or array) to a list of floats."""
    import numpy as np

    arr = wav.detach().cpu().to("cpu").float().numpy() if hasattr(wav, "detach") else wav
    flat = np.asarray(arr, dtype=np.float64).flatten()
    return [float(x) for x in flat]


def _write_wav(path: Path, samples: list[float], sample_rate: int) -> None:
    """Write float samples in [-1, 1] as 16-bit mono PCM, atomically.

    Temp file + rename guarantees one writer per cache file, so concurrent
    background jobs can't corrupt each other's output (mirrors Kokoro).
    """
    import numpy as np

    clipped = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    frames = (clipped * 32767).astype("<i2").tobytes()

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as raw, wave.open(raw, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(frames)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
