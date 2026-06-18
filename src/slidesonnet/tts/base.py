"""Abstract base class for TTS backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSEngine(ABC):
    #: True when synthesis spends money (metered API credits). The editor uses
    #: this to ask before synthesizing uncached audio; local engines are free.
    paid: bool = False

    @abstractmethod
    def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
        """Synthesize text to an audio file.

        Args:
            text: The text to synthesize.
            output_path: Where to write the audio file.
            voice: Optional backend-specific voice override (voice name for Kokoro,
                   voice_id for ElevenLabs). None uses the default.

        Returns:
            Duration of the generated audio in seconds.
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Return backend name for logging."""
        ...

    @abstractmethod
    def cache_key(self) -> str:
        """Return a string that uniquely identifies the TTS configuration.

        Included in the audio cache hash so that switching backends or
        changing backend parameters invalidates cached audio files.
        """
        ...

    def list_voices(self) -> tuple[str, ...]:
        """Voice names this engine can offer in a picker (empty if open-ended).

        Cloud engines with account-specific voice ids return () — the editor
        then offers only the deck's named presets.
        """
        return ()

    def default_voice(self) -> str | None:
        """The voice used when an utterance has no explicit one, if known."""
        return None

    def is_warm(self) -> bool:
        """False when a first synthesis must pay a heavy one-time model load.

        Light engines are always "warm" (nothing to load). A heavy local engine
        (Qwen3) returns False until its multi-GB model is loaded into the
        process, so the editor can show a distinct "Loading model…" status
        before the first generation rather than a silent long pause.
        """
        return True

    def warm(self) -> None:
        """Pay the heavy one-time model load now, so the first synth is quick.

        Blocking and safe to call off the event loop (the editor warms a heavy
        engine in the background when you pick it). A no-op for light engines,
        which have nothing to load; idempotent once warm.
        """
        return None
