"""Qwen3-TTS backend — local, free text-to-speech (Apache-2.0), in two modes.

Qwen3-TTS is a language model over audio tokens. Two model variants drive two
voice modes, picked by the configured repo:

- **CustomVoice** (the default): nine built-in *named speakers* shipped with the
  model — ready to narrate with no setup, the picker's voice list. This is what
  makes Qwen3 work out of the box.
- **Base**: clones a speaker from a tiny precomputed *voice-clone prompt* (a
  ``.pt`` holding codec ``ref_code`` + speaker x-vector) — the expressive /
  own-voice path Kokoro can't do. Selected by pointing the config at a ``-Base``
  repo with a ``voice_prompt`` (or a ``.pt`` mapped per voice).

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
import threading
import wave
from pathlib import Path
from typing import Any

from slidesonnet.cancellation import current_cancel
from slidesonnet.exceptions import GenerationCancelled, TTSError
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

# Serializes the heavy load so a background warm-up and a concurrent synthesis
# don't both pull the multi-GB model into memory at once (the editor may warm on
# engine switch while a generation is queued).
_LOAD_LOCK = threading.Lock()

# The CustomVoice variant ships ready-to-use named speakers (no reference audio
# needed) — the default, so Qwen3 works out of the box. The Base variant instead
# clones a voice from a ``.pt`` prompt (own-voice path); point ``qwen3_model`` at
# a ``...-Base`` repo to use it.
DEFAULT_CUSTOM_VOICE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"

# The built-in speakers shipped with the 1.7B CustomVoice model (its model card).
# Hardcoded so the editor can offer them in the voice picker without paying the
# multi-GB model load that ``get_supported_speakers()`` would require.
CUSTOM_VOICE_SPEAKERS: tuple[str, ...] = (
    "Vivian",
    "Serena",
    "Uncle_Fu",
    "Dylan",
    "Eric",
    "Ryan",
    "Aiden",
    "Ono_Anna",
    "Sohee",
)
DEFAULT_CUSTOM_VOICE_SPEAKER = "Vivian"


def _is_custom_voice_model(model_repo: str) -> bool:
    """True for a CustomVoice repo (built-in speakers) vs a Base clone repo.

    Inferred from the repo name so the editor can branch without loading the
    model (the real signal, ``model.tts_model_type``, needs the weights).
    """
    return "customvoice" in model_repo.lower()


class Qwen3TTS(TTSEngine):
    paid = False

    def __init__(
        self,
        model: str = DEFAULT_CUSTOM_VOICE_MODEL,
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
        if Qwen3TTSModel is None:
            raise TTSError(
                "qwen-tts package not installed. Install with: pip install slidesonnet[qwen3]"
            )
        with _LOAD_LOCK:
            # Re-check under the lock: another thread may have loaded it while we
            # waited (a warm-up racing a synthesis), so we never load twice.
            cached = _MODEL_CACHE.get(cache_key)
            if cached is not None:
                self._model = cached
                return cached
            import torch  # rides along with the [qwen3] extra

            logger.info("Loading Qwen3-TTS model %s on %s ...", self.model_repo, self.device)
            # Load on CPU then move to the accelerator with bf16 — the working
            # recipe on the Intel iGPU (never device_map, never fp16); see
            # dev/voice-profile.
            model = Qwen3TTSModel.from_pretrained(self.model_repo, dtype=torch.bfloat16)
            if self.device != "cpu":
                model.model.to(f"{self.device}:0")
                model.device = next(model.model.parameters()).device
            _MODEL_CACHE[cache_key] = model
            self._model = model
            return model

    def warm(self) -> None:
        """Load the multi-GB model now (e.g. on engine switch) so play is quick."""
        self._ensure_model()

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
        if _is_custom_voice_model(self.model_repo):
            wavs, sample_rate = self._synthesize_custom_voice(text, voice)
        else:
            wavs, sample_rate = self._synthesize_clone(text, voice)
        samples = _to_float_samples(wavs[0]) if len(wavs) else []
        if not samples:
            raise TTSError(f"qwen3 produced no audio for text: {text[:60]!r}")

        sr = int(sample_rate)
        _write_wav(output_path, samples, sr)
        return len(samples) / sr

    def _synthesize_custom_voice(self, text: str, voice: str | None) -> tuple[Any, Any]:
        """Built-in-speaker path: narrate as a named shipped speaker (no prompt).

        The requested voice may be a foreign engine's id (e.g. a Kokoro ``af_heart``
        that rode in via the deck's ``default-voice``) or just wrong case. Match it
        case-insensitively against the shipped speakers and fall back to the default
        rather than letting the model reject it with "Unsupported speakers". The
        editor's ``voice-unmapped`` warnings nudge the user to map it properly.
        """
        known = {s.lower(): s for s in CUSTOM_VOICE_SPEAKERS}
        requested = voice or DEFAULT_CUSTOM_VOICE_SPEAKER
        speaker = known.get(requested.lower())
        if speaker is None:
            logger.warning(
                "Qwen3 CustomVoice has no speaker %r — using %s. Map this voice to a "
                "Qwen3 speaker (%s) in the Voices dialog.",
                requested,
                DEFAULT_CUSTOM_VOICE_SPEAKER,
                ", ".join(CUSTOM_VOICE_SPEAKERS),
            )
            speaker = DEFAULT_CUSTOM_VOICE_SPEAKER
        model = self._ensure_model()
        with _cancellable(model):
            return model.generate_custom_voice(  # type: ignore[no-any-return]
                text=text, language=self.language, speaker=speaker
            )

    def _synthesize_clone(self, text: str, voice: str | None) -> tuple[Any, Any]:
        """Own-voice path: clone the speaker from a ``.pt`` voice-clone prompt."""
        prompt_path = voice if voice else self.voice_prompt
        if not prompt_path:
            raise TTSError(
                "Qwen3 needs a voice prompt — set [tts.qwen3] voice_prompt to a .pt "
                "clone artifact (see dev/voice-profile), or give the utterance a voice."
            )
        model = self._ensure_model()
        prompt = self._load_prompt(prompt_path)
        with _cancellable(model):
            return model.generate_voice_clone(  # type: ignore[no-any-return]
                text=text, language=self.language, voice_clone_prompt=prompt
            )

    def name(self) -> str:
        return "qwen3"

    def cache_key(self) -> str:
        """Identify the config: model + a content hash of the default voice prompt.

        Hashing the prompt's *content* (not its path) means editing the clone
        artifact invalidates cached audio, while moving/renaming the file does
        not churn the cache.
        """
        key = f"qwen3:{self.model_repo}"
        if _is_custom_voice_model(self.model_repo):
            # Built-in speakers are opaque ids folded into each clip's text hash;
            # the model repo already pins the speaker set, so nothing to add.
            return key
        digest = _prompt_content_hash(self.voice_prompt)
        if digest:
            key += f":{digest}"
        return key

    def list_voices(self) -> tuple[str, ...]:
        """Pickable voices: the shipped speakers for CustomVoice, none for clone.

        Clone (Base) voices are arbitrary ``.pt`` files, so the picker offers no
        fixed set there — the deck's voice map points at the artifacts instead.
        """
        return CUSTOM_VOICE_SPEAKERS if _is_custom_voice_model(self.model_repo) else ()

    def default_voice(self) -> str | None:
        """The deck-default voice: a shipped speaker (CustomVoice) or prompt stem."""
        if _is_custom_voice_model(self.model_repo):
            return DEFAULT_CUSTOM_VOICE_SPEAKER
        return Path(self.voice_prompt).stem if self.voice_prompt else None


@contextlib.contextmanager
def _cancellable(model: Any) -> Any:
    """Make the wrapped generation abortable via the active cancel token.

    If a token is bound (the editor preempting for play) we slip a stopping
    criterion into the talker's HF ``generate`` so it halts within a step or two
    of the token being set; on exit we restore the original method and, if the
    token fired, raise :class:`GenerationCancelled` so the truncated audio is
    discarded rather than written. With no token — or if the talker isn't shaped
    as we expect (a future qwen-tts change) — this is a transparent no-op, so the
    clip simply finishes instead of aborting (a safe degradation).
    """
    event = current_cancel()
    talker = getattr(getattr(model, "model", None), "talker", None)
    original = getattr(talker, "generate", None)
    if event is None or talker is None or not callable(original):
        yield
        return
    evt: threading.Event = event  # narrowed; captured by the criterion below

    import torch
    from transformers import StoppingCriteria, StoppingCriteriaList

    # transformers is an optional ([qwen3]-extra) dep, so CI typechecks without it
    # installed — there StoppingCriteria is Any and strict mypy rejects subclassing
    # it. Pin the base to Any so the type-checked shape is identical with or without
    # the package, keeping the one ignore below "used" in both environments.
    _StoppingCriteria: Any = StoppingCriteria

    class _EventStop(_StoppingCriteria):  # type: ignore[misc]  # base is Any (see above)
        def __call__(self, input_ids: Any, scores: Any = None, **kwargs: Any) -> Any:
            return torch.full(
                (input_ids.shape[0],), evt.is_set(), dtype=torch.bool, device=input_ids.device
            )

    criteria = StoppingCriteriaList([_EventStop()])

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("stopping_criteria", criteria)
        return original(*args, **kwargs)

    talker.generate = _wrapped
    try:
        yield
    finally:
        talker.generate = original
        if evt.is_set():
            raise GenerationCancelled("qwen3 synthesis cancelled before completion")


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
