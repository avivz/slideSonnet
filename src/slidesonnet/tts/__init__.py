"""TTS package: speech synthesis backends, their registry, and a factory.

``BACKENDS`` is the single place a TTS engine is described — name, paid flag,
constructor, and (read back from ``hashing``, which owns it) cached-audio file
extension. The CLI's ``--engine`` choices, config validation, and clean's
paid-audio set all derive from it, so adding an engine means one new
``BackendSpec`` (plus its extension in ``hashing.BACKEND_EXTENSIONS`` and the
``Backend`` Literal in models.py, which mypy can't derive at runtime — tests pin
both in sync).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from slidesonnet.hashing import audio_extension
from slidesonnet.models import TTSConfig
from slidesonnet.tts.base import TTSEngine


def _make_kokoro(tts: TTSConfig) -> TTSEngine:
    from slidesonnet.tts.kokoro import KokoroTTS

    return KokoroTTS(voice=tts.kokoro_voice, speed=tts.kokoro_speed)


def _make_inworld(tts: TTSConfig) -> TTSEngine:
    from slidesonnet.tts.inworld import InworldTTS

    return InworldTTS(tts)


def _make_qwen3(tts: TTSConfig) -> TTSEngine:
    from slidesonnet.tts.qwen3 import Qwen3TTS

    return Qwen3TTS(
        model=tts.qwen3_model,
        device=tts.qwen3_device,
        voice_prompt=tts.qwen3_voice_prompt,
        language=tts.qwen3_language,
    )


@dataclass(frozen=True)
class BackendSpec:
    """Everything the rest of the tool needs to know about a TTS backend."""

    name: str
    paid: bool  # synthesis spends metered API credits
    factory: Callable[[TTSConfig], TTSEngine]
    #: Synthesis runs at ~real-time or faster — cheap enough to fire unattended
    #: on every edit. False for a heavy local model (Qwen3) that, while free,
    #: is too slow to auto-generate; the editor gates "Auto-generate as I edit"
    #: on ``paid OR not realtime``.
    realtime: bool = True
    #: Python module that must be importable for this backend to run (its extra).
    #: Used to offer only installed engines in the editor's engine picker.
    import_name: str = ""
    #: This backend's voices are *file paths* (e.g. a Qwen3 ``.pt`` clone prompt),
    #: not opaque ids — so a voice-map value is resolved relative to the deck dir
    #: when the deck loads, keeping the sidecar portable.
    file_voices: bool = False
    #: Rough generation time ÷ audio seconds (real-time factor) — only used to
    #: *estimate* a clip's progress in the editor (elapsed vs ~expected). Fast
    #: engines are well under 1×; Qwen3 on the laptop iGPU is ~3.3×.
    rtf: float = 0.3
    #: May the *silent on-edit* orphan sweep (``clean.prune_local_orphans``)
    #: delete this backend's now-orphaned clips? True only for audio that is
    #: cheap to regenerate (Kokoro, real-time local). False for *paid* audio
    #: (would re-bill) **and** for *expensive* free-but-slow local audio (Qwen3,
    #: seconds per clip) — discarding a Qwen3 orphan on an unrelated edit silently
    #: throws away minutes of own-voice generation. This governs only the
    #: automatic sweep; an explicit ``clean --keep nothing`` still removes
    #: everything. A single per-engine knob so a new backend declares its policy
    #: in one place rather than the prune path hardcoding a ``paid`` check.
    auto_prune_orphans: bool = True

    @property
    def extension(self) -> str:
        """Cached-audio file extension (".wav", ".mp3") — owned by ``hashing``."""
        return audio_extension(self.name)


BACKENDS: dict[str, BackendSpec] = {
    "kokoro": BackendSpec("kokoro", paid=False, factory=_make_kokoro, import_name="kokoro"),
    "inworld": BackendSpec(
        "inworld",
        paid=True,
        factory=_make_inworld,
        import_name="inworld_tts",
        auto_prune_orphans=False,  # paid — never auto-discard (would re-bill to rebuild)
    ),
    "qwen3": BackendSpec(
        "qwen3",
        paid=False,
        factory=_make_qwen3,
        realtime=False,
        import_name="qwen_tts",
        file_voices=True,
        rtf=3.3,
        auto_prune_orphans=False,  # free but slow — don't silently discard own-voice audio
    ),
}

#: Backend names whose voice-map values are file paths (resolved per-deck).
FILE_VOICE_BACKENDS: frozenset[str] = frozenset(n for n, s in BACKENDS.items() if s.file_voices)


def available_backends() -> list[str]:
    """Backend names whose Python package is importable (the editor picker's set).

    A backend the user hasn't installed the extra for can't generate, so the
    editor offers only the installed ones (plus whatever's currently active).
    """
    import importlib.util

    return [
        name
        for name, spec in BACKENDS.items()
        if spec.import_name and importlib.util.find_spec(spec.import_name) is not None
    ]


#: Backends whose cached audio cost money to produce (clean keeps these).
API_BACKENDS: frozenset[str] = frozenset(n for n, spec in BACKENDS.items() if spec.paid)

#: Backends whose orphaned clips the silent on-edit sweep may delete — only audio
#: cheap to regenerate (real-time local). Paid and expensive-local backends are
#: excluded, so ``prune_local_orphans`` keeps their orphans without a ``paid`` check.
AUTO_PRUNE_BACKENDS: frozenset[str] = frozenset(
    n for n, spec in BACKENDS.items() if spec.auto_prune_orphans
)


def create_tts(tts: TTSConfig) -> TTSEngine:
    """Create a TTS engine from a :class:`TTSConfig`.

    Loads ``.env`` first so a cloud engine's API key (which the engine reads from
    ``os.environ``) is present no matter which path — CLI, GUI preview, or the
    background queue — reached here.
    """
    spec = BACKENDS.get(tts.backend)
    if spec is None:
        raise ValueError(f"Unknown TTS backend: {tts.backend}")
    return spec.factory(tts)
