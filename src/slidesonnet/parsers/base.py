"""Abstract base class for slide parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from slidesonnet.models import SlideNarration


class SlideParser(ABC):
    @abstractmethod
    def parse(self, source: Path, build_dir: Path) -> list[SlideNarration]:
        """Extract slide images and narration from a source file.

        Args:
            source: Path to the slide source file (.md or .tex).
            build_dir: Directory for build artifacts (images go here).

        Returns:
            List of SlideNarration objects, one per slide, with
            image_path, annotation, narration_raw, voice, and pace populated.
        """
        ...
