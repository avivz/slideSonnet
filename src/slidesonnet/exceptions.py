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


class NarrationChangedOnDisk(SlideSonnetError):
    """The sidecar changed on disk since the editor loaded it; the save was refused.

    Saving would overwrite someone else's edit (typically an agent's) with the
    editor's stale copy. The editor's change loses instead: the deck is reloaded
    from disk and *lost_text* (when the change was narration text) is handed
    back so the user can copy it before it's gone.
    """

    def __init__(self, lost_text: str | None = None) -> None:
        super().__init__("The narration file changed on disk; your change was not saved.")
        self.lost_text = lost_text


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
