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
