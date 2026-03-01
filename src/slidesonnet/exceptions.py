"""Domain exceptions for slideSonnet."""


class SlideSonnetError(Exception):
    """Base exception for all slideSonnet errors."""


class ParserError(SlideSonnetError):
    """Slide parser external tool (marp, pdflatex, pdftoppm) is missing or failed."""


class TTSError(SlideSonnetError):
    """TTS synthesis failed or configuration is missing."""


class ConfigError(SlideSonnetError):
    """Configuration is invalid or malformed."""


class FFmpegError(SlideSonnetError):
    """FFmpeg is missing or a command failed."""
