"""Domain exceptions for slideSonnet."""


class SlideSonnetError(Exception):
    """Base exception for all slideSonnet errors."""


class ParserError(SlideSonnetError):
    """Reading the deck PDF failed (PyMuPDF open/parse, or pdftoppm rasterize)."""


class TTSError(SlideSonnetError):
    """TTS synthesis failed or configuration is missing."""


class GenerationCancelled(SlideSonnetError):
    """A synthesis was deliberately aborted mid-flight (e.g. play preempted it).

    Distinct from a failure: the partial output is discarded and the clip is
    expected to be regenerated later, so callers re-queue rather than surface it.
    """


class ConfigError(SlideSonnetError):
    """Configuration is invalid or malformed."""


class FFmpegError(SlideSonnetError):
    """FFmpeg is missing or a command failed."""


class RenderError(SlideSonnetError):
    """Track/video assembly was asked to render inconsistent inputs."""


class SubtitleTimingError(SlideSonnetError):
    """Subtitles were asked for real (tts) timing the cached audio can't supply.

    Guessing a cue's length from its word count yields a file that looks correct
    but drifts against the video, so the caller must either generate the audio,
    name the engine that holds it, or ask for guessed times on purpose.
    """
