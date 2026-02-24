"""Abstract base class for TTS backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSEngine(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> float:
        """Synthesize text to an audio file.

        Args:
            text: The text to synthesize.
            output_path: Where to write the audio file.

        Returns:
            Duration of the generated audio in seconds.
        """
        ...

    @abstractmethod
    def name(self) -> str:
        """Return backend name for logging."""
        ...
