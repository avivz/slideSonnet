"""Kokoro TTS backend — local neural text-to-speech (82M params, Apache-2.0).

Noticeably more natural than Piper while still ~2x real-time on CPU. Voices
are named ``<lang><gender>_<name>`` (e.g. ``af_heart`` = American English
female "heart"); the first letter is the KPipeline language code. The model
(~330 MB) auto-downloads from the Hugging Face hub on first use, and is
resolved cache-first afterwards — see ``_cache_first``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import warnings
import wave
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from slidesonnet.exceptions import TTSError
from slidesonnet.tts.base import TTSEngine

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kokoro import KPipeline as _KPipelineType

_KPipeline: type[_KPipelineType] | None
try:
    from kokoro import KPipeline as _KPipelineImport

    _KPipeline = _KPipelineImport
except ImportError:
    _KPipeline = None

# Module-level alias for test mocking via @patch
KPipeline: type[_KPipelineType] | None = _KPipeline

# huggingface_hub rides along with the kokoro extra, so it's as optional as kokoro
# itself. Without it there are no downloads to intercept; FileNotFoundError (which
# LocalEntryNotFoundError subclasses) keeps the except clause well-typed either way.
_CacheMiss: type[BaseException]
try:
    from huggingface_hub.errors import LocalEntryNotFoundError as _LocalEntryNotFound

    _CacheMiss = _LocalEntryNotFound
except ImportError:  # pragma: no cover — no huggingface_hub, no cache to miss
    _CacheMiss = FileNotFoundError

_REPO_ID = "hexgrad/Kokoro-82M"
_SAMPLE_RATE = 24_000

# Set to 1 to opt out of cache-first resolution and let Kokoro revalidate its
# model files against the hub (i.e. pick up a newly published revision).
_ENV_REFRESH = "SLIDESONNET_KOKORO_REFRESH"


def _cache_first(hf_hub_download: Callable[..., str]) -> Callable[..., str]:
    """Wrap ``hf_hub_download`` so it looks in the local cache before the network.

    Kokoro fetches three things by name — ``config.json``, the model weights, and
    one ``voices/<voice>.pt`` per voice — and stock ``hf_hub_download`` revalidates
    each against huggingface.co even when the file is already on disk. That HEAD
    request is pure latency when the machine is online, and when it *isn't* (a
    laptop asleep, a WSL network drop) huggingface_hub burns ~30 s on five backoff
    retries before falling back to the very cache it started next to.

    So we probe the cache first and only reach for the hub when the file genuinely
    isn't there — a first run, or a voice this machine hasn't used yet. The cost is
    that a new upstream revision isn't picked up on its own; set ``_ENV_REFRESH``
    for that.
    """

    def download(*args: Any, **kwargs: Any) -> str:
        # The caller already made the call themselves — don't second-guess it.
        if kwargs.get("local_files_only") or kwargs.get("force_download"):
            return hf_hub_download(*args, **kwargs)
        try:
            return hf_hub_download(*args, local_files_only=True, **kwargs)
        except _CacheMiss:
            logger.info("%s not cached locally — downloading from the hub", kwargs.get("filename"))
            return hf_hub_download(*args, **kwargs)

    download._slidesonnet_cache_first = True  # type: ignore[attr-defined]
    return download


def _install_cache_first_downloads() -> None:
    """Point Kokoro's two download sites at :func:`_cache_first`. Idempotent.

    Both modules do ``from huggingface_hub import hf_hub_download``, so they hold
    their own references — patching the ``huggingface_hub`` attribute wouldn't
    reach them. Installed permanently rather than scoped to a ``with`` block: the
    editor synthesizes on background threads, and a restore racing another
    thread's call is a worse failure than a wrapper that outlives one load.
    """
    if os.environ.get(_ENV_REFRESH) == "1":
        return
    try:
        import kokoro.model
        import kokoro.pipeline
    except ImportError:  # pragma: no cover — no kokoro, no download sites to patch
        return
    for module in (kokoro.model, kokoro.pipeline):
        current = module.hf_hub_download
        if not getattr(current, "_slidesonnet_cache_first", False):
            module.hf_hub_download = _cache_first(current)


@contextlib.contextmanager
def _quiet_torch_load_warnings() -> Iterator[None]:
    """Silence the two torch warnings Kokoro's model construction always emits.

    Building the model trips an LSTM ``dropout`` UserWarning and a ``weight_norm``
    deprecation FutureWarning on every load. Both come from torch internals we
    can't change, and they bury the editor's own terminal output — so suppress
    just those two messages (anything else still surfaces).
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="dropout option adds dropout", category=UserWarning
        )
        warnings.filterwarnings(
            "ignore",
            message=r"`torch\.nn\.utils\.weight_norm` is deprecated",
            category=FutureWarning,
        )
        yield


# The Kokoro-82M v1.0 English voices (``<lang><gender>_<name>``; lang a=American,
# b=British). Offered as the voice choices in the editor — these need no extra
# language packs, unlike the es/fr/hi/it/ja/pt/zh voices the model also ships.
KOKORO_VOICES: tuple[str, ...] = (
    # American English — female
    "af_heart",
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    # American English — male
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    # British English — female
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    # British English — male
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
)


class KokoroTTS(TTSEngine):
    def __init__(self, voice: str = "am_echo", speed: float = 1.0) -> None:
        self.voice = voice
        self.speed = speed
        self._pipelines: dict[str, Any] = {}  # lang code -> KPipeline

    def _pipeline_for(self, voice: str) -> Any:
        """Get (or lazily create) the KPipeline for *voice*'s language."""
        lang_code = voice[0]  # Kokoro convention: voice prefix is the language
        if lang_code not in self._pipelines:
            if KPipeline is None:
                raise TTSError(
                    "kokoro package not installed. Install with: pip install slidesonnet[kokoro]"
                )
            logger.info("Loading Kokoro pipeline (lang '%s')...", lang_code)
            _install_cache_first_downloads()
            with _quiet_torch_load_warnings():
                self._pipelines[lang_code] = KPipeline(lang_code=lang_code, repo_id=_REPO_ID)
        return self._pipelines[lang_code]

    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        voice_name = voice if voice else self.voice
        pipeline = self._pipeline_for(voice_name)

        samples: list[float] = []
        for result in pipeline(text, voice=voice_name, speed=self.speed):
            audio = getattr(result, "audio", None)
            if audio is not None:
                samples.extend(audio.tolist())
        if not samples:
            raise TTSError(f"kokoro produced no audio for text: {text[:60]!r}")

        _write_wav(output_path, samples)
        return len(samples) / _SAMPLE_RATE

    def name(self) -> str:
        return "kokoro"

    def cache_key(self) -> str:
        key = f"kokoro:{self.voice}"
        if self.speed != 1.0:
            key += f":{self.speed}"
        return key

    def list_voices(self) -> tuple[str, ...]:
        return KOKORO_VOICES

    def default_voice(self) -> str | None:
        return self.voice


def _write_wav(path: Path, samples: list[float]) -> None:
    """Write float samples in [-1, 1] as 16-bit mono PCM at 24 kHz."""
    try:
        # numpy rides along with kokoro (via torch); vectorized conversion is
        # ~100x faster than a per-sample Python loop at 24k samples/second
        import numpy as np

        clipped = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
        frames = (clipped * 32767).astype("<i2").tobytes()
    except ImportError:  # pragma: no cover — kokoro always brings numpy
        import array
        import sys

        pcm = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in samples))
        if sys.byteorder == "big":
            pcm.byteswap()
        frames = pcm.tobytes()
    # Write to a temp file in the same directory, then atomically rename onto the
    # target. Guarantees one writer per cache file: two background jobs (or a
    # force-regenerate racing a queued job) can't corrupt each other's output, and
    # a reader never sees a half-written WAV. Mirrors the inworld backend.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as raw, wave.open(raw, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(_SAMPLE_RATE)
            wf.writeframes(frames)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
