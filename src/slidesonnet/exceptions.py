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


class ReviewError(SlideSonnetError):
    """A review operation can't proceed (bad conversation id, final build, …)."""


class ExportRefused(SlideSonnetError):
    """The deck isn't ready for a final video (plain build, or review still open).

    ``reasons`` lists every blocker in user terms; exporting a draft
    (``--draft``) bypasses the check.
    """

    def __init__(self, reasons: list[str]) -> None:
        super().__init__(
            "Not ready for the final video:\n"
            + "\n".join(f"  - {r}" for r in reasons)
            + "\nExport a draft instead with --draft (writes <name>.draft.mp4)."
        )
        self.reasons = reasons


class NarrationNotFound(SlideSonnetError):
    """An explicitly named narration sidecar doesn't exist (a typo, not a new deck)."""


class UnknownSlideId(SlideSonnetError):
    """A slide-id asked for by name isn't in the deck."""


class SynthesisDeclined(SlideSonnetError):
    """Paid synthesis needed approval and didn't get it; nothing was generated."""


class UnapprovedClips(SynthesisDeclined):
    """Paid work met clips outside the set approved for it (the narration changed since)."""

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(
            "The narration changed after you approved it; "
            f"approve again to generate {count} new clip{'s' if count != 1 else ''}."
        )
