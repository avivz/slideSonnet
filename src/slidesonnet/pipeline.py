"""Build pipeline: orchestrates doit-based incremental builds."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from dotenv import load_dotenv

from slidesonnet.actions import get_parser_and_extractor
from slidesonnet.config import load_config
from slidesonnet.exceptions import APINotAllowedError, SlideSonnetError
from slidesonnet.hashing import _BACKEND_EXTENSIONS
from slidesonnet.hashing import audio_path as _audio_path
from slidesonnet.models import (
    API_BACKENDS,
    ModuleType,
    PlaylistEntry,
    ProjectConfig,
    SlideAnnotation,
    resolve_voice,
)
from slidesonnet.playlist import parse_playlist
from slidesonnet.tasks import generate_tasks
from slidesonnet.tts import create_tts
from slidesonnet.tts.base import TTSEngine
from slidesonnet.tts.pronunciation import apply_pronunciation, load_pronunciation_dict

logger = logging.getLogger(__name__)


@dataclass
class _PreparedBuild:
    """Shared preparation result used by both build() and dry_run()."""

    playlist_path: Path
    playlist_dir: Path
    build_dir: Path
    config: ProjectConfig
    entries: list[PlaylistEntry]
    tts: TTSEngine
    output_path: Path
    pdf_output_path: Path


def _resolve_output_name(
    playlist_dir: Path,
    config_output: str,
    output_override: Path | None = None,
) -> Path:
    """Determine the output video path.

    Precedence: ``output_override`` (--output flag, resolved relative to cwd)
    > ``config_output`` (output: YAML field, resolved relative to playlist dir)
    > parent directory name + ``.mp4``.
    """
    if output_override is not None:
        p = Path(output_override)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.suffix != ".mp4":
            p = p.with_suffix(".mp4")
        return p.resolve()

    if config_output:
        p = playlist_dir / config_output
        if p.suffix != ".mp4":
            p = p.with_suffix(".mp4")
        return p.resolve()

    # Default: directory name
    dir_name = playlist_dir.name
    return (playlist_dir / (dir_name + ".mp4")).resolve()


def _prepare(
    playlist_path: Path,
    tts_override: Literal["piper", "elevenlabs"] | None = None,
    output_override: Path | None = None,
) -> _PreparedBuild:
    """Resolve paths, load config, create TTS engine.

    Shared setup for build() and dry_run(). Does NOT create directories.
    """
    playlist_path = playlist_path.resolve()
    playlist_dir = playlist_path.parent
    build_dir = playlist_dir / "cache"

    # Load .env from project root
    load_dotenv(playlist_dir / ".env")

    # Parse playlist
    raw_config, entries = parse_playlist(playlist_path)
    config = load_config(raw_config, playlist_dir)

    # Override TTS backend if requested
    if tts_override:
        config.tts.backend = tts_override

    # Load pronunciation
    config.pronunciation = load_pronunciation_dict(config.pronunciation_files)

    # Validate ElevenLabs API key early (before any build work)
    if config.tts.backend == "elevenlabs":
        api_key_env = config.tts.elevenlabs_api_key_env
        if not os.environ.get(api_key_env, ""):
            raise SlideSonnetError(
                f"ElevenLabs API key not found (${api_key_env} is not set).\n"
                f"Create a .env file with {api_key_env}=your-key, "
                f"or use --tts piper for free local TTS."
            )

    # Create TTS engine
    tts = create_tts(config)

    # Output path
    output_path = _resolve_output_name(playlist_dir, config.output, output_override)
    pdf_output_path = output_path.with_suffix(".pdf")

    return _PreparedBuild(
        playlist_path=playlist_path,
        playlist_dir=playlist_dir,
        build_dir=build_dir,
        config=config,
        entries=entries,
        tts=tts,
        output_path=output_path,
        pdf_output_path=pdf_output_path,
    )


@dataclass
class SlideInfo:
    """Per-slide metadata returned by list_slides()."""

    module_path: str
    slide_index: int
    voice: str
    text: str
    cached: bool | None  # None = not narrated (silent/unannotated)
    chars: int  # 0 for non-narrated slides


@dataclass
class ListResult:
    """Result of list_slides(): per-slide info plus project metadata."""

    slides: list[SlideInfo]
    tts_backend: str


@dataclass
class BuildResult:
    """Result of a completed build."""

    output_path: Path
    elapsed_seconds: float
    until: str | None = None
    srt_path: Path | None = None


@dataclass
class DryRunResult:
    """Summary of what a build would do, without executing anything."""

    total_narrated: int
    cached: int
    needs_tts: int
    uncached_chars: int
    tts_backend: str


def _audio_cache_exists(path: Path) -> bool:
    """Check if an audio cache file exists (read-only, no side effects).

    Unlike tasks._audio_cache_valid, this never renames files.
    Checks the given path and alternate extensions (.wav ↔ .mp3).
    """
    if path.exists() and path.stat().st_size > 0:
        return True
    suffix = path.suffix
    for ext in _BACKEND_EXTENSIONS.values():
        if ext != suffix:
            alt = path.with_suffix(ext)
            if alt.exists() and alt.stat().st_size > 0:
                return True
    return False


@dataclass
class _UncachedSlide:
    """An uncached slide found during preflight check."""

    module_path: str
    slide_index: int
    text: str
    chars: int


def _preflight_api_check(prep: _PreparedBuild) -> None:
    """Raise APINotAllowedError if the build would make paid API calls.

    Only checks API backends (e.g. ElevenLabs). Piper is free and always allowed.
    """
    if prep.config.tts.backend not in API_BACKENDS:
        return

    audio_cache_dir = prep.build_dir / "audio"
    uncached: list[_UncachedSlide] = []
    total_chars = 0

    for entry in prep.entries:
        if entry.module_type == ModuleType.VIDEO:
            continue

        source_path = prep.playlist_dir / entry.path
        module_dir = prep.build_dir / entry.path.parent / entry.path.stem
        slides_dir = module_dir / "slides"

        parser_cls, _ = get_parser_and_extractor(entry.module_type)
        parser = parser_cls()
        slides = parser.parse(source_path, slides_dir)

        for slide in slides:
            if not slide.has_narration:
                continue

            pron = prep.config.pronunciation_for(prep.config.tts.backend)
            slide.narration_processed = apply_pronunciation(slide.narration_raw, pron)
            slide.narration_parts_processed = [
                apply_pronunciation(part, pron) for part in slide.narration_parts
            ]

            if slide.voice:
                resolved = resolve_voice(slide.voice, prep.config.voices, prep.config.tts.backend)
                if resolved:
                    slide.voice = resolved
                else:
                    slide.voice = None

            parts = slide.narration_parts_processed

            if len(parts) > 1:
                slide_uncached_chars = 0
                all_cached = True
                for part_text in parts:
                    p = _audio_path(
                        audio_cache_dir,
                        part_text,
                        prep.tts.name(),
                        prep.tts.cache_key(),
                        slide.voice,
                    )
                    if not _audio_cache_exists(p):
                        all_cached = False
                        slide_uncached_chars += len(part_text)
                if not all_cached:
                    uncached.append(
                        _UncachedSlide(
                            module_path=str(entry.path),
                            slide_index=slide.index,
                            text=slide.narration_processed,
                            chars=slide_uncached_chars,
                        )
                    )
                    total_chars += slide_uncached_chars
            else:
                p = _audio_path(
                    audio_cache_dir,
                    slide.narration_processed,
                    prep.tts.name(),
                    prep.tts.cache_key(),
                    slide.voice,
                )
                if not _audio_cache_exists(p):
                    chars = len(slide.narration_processed)
                    uncached.append(
                        _UncachedSlide(
                            module_path=str(entry.path),
                            slide_index=slide.index,
                            text=slide.narration_processed,
                            chars=chars,
                        )
                    )
                    total_chars += chars

    if not uncached:
        return

    n = len(uncached)
    lines = [
        f"Build requires ElevenLabs API calls for {n} uncached "
        f"slide{'s' if n != 1 else ''} (~{total_chars:,} characters):",
        "",
    ]
    for s in uncached:
        preview = s.text
        if len(s.text) > 80:
            preview = s.text[:77] + "..."
        lines.append(f'  {s.module_path} slide {s.slide_index}: "{preview}"')
    lines.append("")
    lines.append("Pass --allow-api to allow paid API calls, or use --tts piper for free local TTS.")
    raise APINotAllowedError("\n".join(lines))


def dry_run(
    playlist_path: Path,
    tts_override: Literal["piper", "elevenlabs"] | None = None,
) -> DryRunResult:
    """Compute what a build would do without executing anything.

    Parses slides, resolves pronunciation and voices, checks audio cache,
    and returns a summary. No directories created, no TTS calls, no FFmpeg.
    """
    prep = _prepare(playlist_path, tts_override)
    audio_cache_dir = prep.build_dir / "audio"

    total_narrated = 0
    cached = 0
    needs_tts = 0
    uncached_chars = 0

    for entry in prep.entries:
        if entry.module_type == ModuleType.VIDEO:
            continue

        source_path = prep.playlist_dir / entry.path
        module_dir = prep.build_dir / entry.path.parent / entry.path.stem
        slides_dir = module_dir / "slides"

        parser_cls, _ = get_parser_and_extractor(entry.module_type)
        parser = parser_cls()
        slides = parser.parse(source_path, slides_dir)

        for slide in slides:
            if not slide.has_narration:
                continue

            # Apply pronunciation (same as generate_tasks)
            pron = prep.config.pronunciation_for(prep.config.tts.backend)
            slide.narration_processed = apply_pronunciation(slide.narration_raw, pron)
            slide.narration_parts_processed = [
                apply_pronunciation(part, pron) for part in slide.narration_parts
            ]

            # Resolve voice preset (same as generate_tasks)
            if slide.voice:
                resolved = resolve_voice(slide.voice, prep.config.voices, prep.config.tts.backend)
                if resolved:
                    slide.voice = resolved
                else:
                    slide.voice = None

            total_narrated += 1
            parts = slide.narration_parts_processed

            if len(parts) > 1:
                # Multi-part: check each part independently
                slide_uncached_chars = 0
                slide_all_cached = True
                for part_text in parts:
                    p = _audio_path(
                        audio_cache_dir,
                        part_text,
                        prep.tts.name(),
                        prep.tts.cache_key(),
                        slide.voice,
                    )
                    if not _audio_cache_exists(p):
                        slide_all_cached = False
                        slide_uncached_chars += len(part_text)

                if slide_all_cached:
                    cached += 1
                else:
                    needs_tts += 1
                    uncached_chars += slide_uncached_chars
            else:
                # Single part
                p = _audio_path(
                    audio_cache_dir,
                    slide.narration_processed,
                    prep.tts.name(),
                    prep.tts.cache_key(),
                    slide.voice,
                )
                if _audio_cache_exists(p):
                    cached += 1
                else:
                    needs_tts += 1
                    uncached_chars += len(slide.narration_processed)

    return DryRunResult(
        total_narrated=total_narrated,
        cached=cached,
        needs_tts=needs_tts,
        uncached_chars=uncached_chars,
        tts_backend=prep.config.tts.backend,
    )


_STAGE_PREFIXES: dict[str, tuple[str, ...]] = {
    "slides": ("compile_beamer:", "extract_images:", "export_pdf:", "assemble_pdf"),
    "tts": (
        "compile_beamer:",
        "extract_images:",
        "export_pdf:",
        "assemble_pdf",
        "tts:",
        "concat_audio:",
    ),
    "segments": (
        "compile_beamer:",
        "extract_images:",
        "export_pdf:",
        "assemble_pdf",
        "tts:",
        "concat_audio:",
        "compose:",
    ),
}


def _filter_tasks_until(
    task_list: list[dict[str, Any]],
    until: str | None,
) -> list[dict[str, Any]]:
    """Filter task list to include only tasks up to the given stage.

    Returns all tasks when *until* is None.
    """
    if until is None:
        return task_list
    prefixes = _STAGE_PREFIXES[until]
    return [t for t in task_list if t["name"].startswith(prefixes)]


def build(
    playlist_path: Path,
    tts_override: Literal["piper", "elevenlabs"] | None = None,
    preview: bool = False,
    until: str | None = None,
    quiet: bool = False,
    no_srt: bool = False,
    allow_api: bool = False,
    output_override: Path | None = None,
) -> BuildResult:
    """Execute the full build pipeline for a playlist.

    Returns a :class:`BuildResult` with the output path, elapsed time, and stage.
    Raises :class:`APINotAllowedError` if paid API calls are needed and
    *allow_api* is False (unless *until* is ``"slides"``).
    """
    prep = _prepare(playlist_path, tts_override, output_override)

    if not allow_api and until != "slides":
        _preflight_api_check(prep)

    # Apply preview overrides: quarter resolution, half fps, ultrafast preset, high CRF
    if preview:
        w, h = prep.config.video.resolution.split("x")
        prep.config.video.resolution = f"{int(w) // 4}x{int(h) // 4}"
        prep.config.video.fps = prep.config.video.fps // 2
        prep.config.video.preset = "ultrafast"
        prep.config.video.crf = 32
        prep.config.video.crossfade = 0.0
        stem = prep.output_path.stem
        prep.output_path = prep.output_path.with_name(stem + "_preview.mp4")

    # Create directories
    prep.build_dir.mkdir(parents=True, exist_ok=True)
    audio_cache_dir = prep.build_dir / "audio"
    audio_cache_dir.mkdir(parents=True, exist_ok=True)

    # Generate doit tasks
    task_list = generate_tasks(
        entries=prep.entries,
        config=prep.config,
        tts=prep.tts,
        build_dir=prep.build_dir,
        playlist_dir=prep.playlist_dir,
        output_path=prep.output_path,
        pdf_output_path=prep.pdf_output_path,
    )

    # Filter tasks by stage
    task_list = _filter_tasks_until(task_list, until)

    # Run doit
    elapsed = _run_doit(task_list, prep.build_dir, quiet=quiet)

    # Generate SRT subtitles (post-doit, uses cached audio durations)
    srt_path: Path | None = None
    if not no_srt and until != "slides":
        srt_path = _generate_srt(prep, quiet=quiet)

    return BuildResult(
        output_path=prep.output_path,
        elapsed_seconds=elapsed,
        until=until,
        srt_path=srt_path,
    )


def _generate_srt(prep: _PreparedBuild, quiet: bool = False) -> Path | None:
    """Generate SRT subtitles from cached audio files.

    Returns the SRT path on success, None on failure.
    """
    from slidesonnet.subtitles import format_srt, generate_subtitles

    try:
        entries = generate_subtitles(
            entries=prep.entries,
            config=prep.config,
            tts=prep.tts,
            build_dir=prep.build_dir,
            playlist_dir=prep.playlist_dir,
        )
        if not entries:
            return None
        srt_content = format_srt(entries)
        srt_path = prep.output_path.with_suffix(".srt")
        srt_path.write_text(srt_content, encoding="utf-8")
        return srt_path
    except Exception:
        logger.warning("SRT generation failed", exc_info=not quiet)
        return None


def generate_srt_file(
    playlist_path: Path,
    tts_override: Literal["piper", "elevenlabs"] | None = None,
    output: Path | None = None,
) -> Path:
    """Generate an SRT subtitle file from a previously built playlist.

    Requires a prior build (audio files must exist in cache).
    """
    from slidesonnet.subtitles import format_srt, generate_subtitles

    prep = _prepare(playlist_path, tts_override)
    entries = generate_subtitles(
        entries=prep.entries,
        config=prep.config,
        tts=prep.tts,
        build_dir=prep.build_dir,
        playlist_dir=prep.playlist_dir,
    )
    srt_content = format_srt(entries)
    srt_path = output or prep.output_path.with_suffix(".srt")
    srt_path.write_text(srt_content, encoding="utf-8")
    return srt_path


def _run_doit(
    task_list: list[dict[str, Any]],
    build_dir: Path,
    quiet: bool = False,
) -> float:
    """Run doit programmatically with the given tasks.

    Returns elapsed time in seconds.
    """
    from doit.cmd_base import TaskLoader2
    from doit.doit_cmd import DoitMain
    from doit.reporter import ConsoleReporter
    from doit.task import dict_to_task

    db_file = str(build_dir / ".doit.db")
    tasks = [dict_to_task(t) for t in task_list]
    start_time = time.monotonic()

    _SLIDE_PREFIXES = ("compile_beamer:", "extract_images:", "export_pdf:")
    _AUDIO_PREFIXES = ("tts:", "concat_audio:")
    _VIDEO_PREFIXES = ("compose:",)

    def _categorize_task(name: str) -> str | None:
        if name.startswith(_SLIDE_PREFIXES):
            return "slides"
        if name.startswith(_AUDIO_PREFIXES):
            return "audio"
        if name.startswith(_VIDEO_PREFIXES):
            return "video"
        if name == "assemble":
            return "assemble"
        return None

    class _WarningBuffer(logging.Handler):
        """Buffer WARNING+ records for replay after progress bars finish."""

        def __init__(self) -> None:
            super().__init__(level=logging.WARNING)
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    class _ProgressReporter(ConsoleReporter):  # type: ignore[misc]
        """Reporter that shows grouped progress bars for slides/audio/video."""

        def initialize(self, tasks: Any, selected_tasks: Any) -> None:
            super().initialize(tasks, selected_tasks)
            self._cached: dict[str, int] = {}
            self._ran: dict[str, int] = {}

            # Count tasks per category
            counts: dict[str, int] = {"slides": 0, "audio": 0, "video": 0, "assemble": 0}
            for name in selected_tasks:
                cat = _categorize_task(name)
                if cat:
                    counts[cat] += 1

            # Buffer warnings during progress to avoid interleaving with bars
            self._warning_buffer = _WarningBuffer()
            ss_logger = logging.getLogger("slidesonnet")
            ss_logger.addHandler(self._warning_buffer)
            # Suppress normal warning output during progress display
            self._orig_handler_levels: list[tuple[logging.Handler, int]] = []
            for handler in logging.root.handlers:
                self._orig_handler_levels.append((handler, handler.level))
                handler.setLevel(logging.ERROR)

            # Suppress action logger to avoid visual interference
            logging.getLogger("slidesonnet.actions").setLevel(logging.WARNING)

            # Create rich progress display
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
            )
            self._bar_ids: dict[str, Any] = {}
            for cat, label in [
                ("slides", "Slides"),
                ("audio", "Audio"),
                ("video", "Video"),
            ]:
                if counts[cat] > 0:
                    tid = self._progress.add_task(label, total=counts[cat])
                    self._bar_ids[cat] = tid
            if counts["assemble"] > 0:
                tid = self._progress.add_task("Assemble", total=None, visible=False)
                self._bar_ids["assemble"] = tid
            self._progress.start()

        def execute_task(self, task: Any) -> None:
            cat = _categorize_task(task.name)
            if cat == "assemble" and cat in self._bar_ids:
                self._progress.update(
                    self._bar_ids[cat],
                    description="Assembling...",
                    visible=True,
                    refresh=True,
                )

        _LABELS = {"slides": "Slides", "audio": "Audio", "video": "Video"}

        def _description(self, cat: str) -> str:
            cached = self._cached.get(cat, 0)
            ran = self._ran.get(cat, 0)
            parts: list[str] = []
            if cached:
                parts.append(f"{cached} cached")
            if ran:
                parts.append(f"{ran} {'synthesized' if cat == 'audio' else 'built'}")
            if parts:
                return f"{self._LABELS[cat]} ({', '.join(parts)})"
            return self._LABELS[cat]

        def _finish_assemble(self) -> None:
            self._progress.update(
                self._bar_ids["assemble"],
                total=1,
                completed=1,
                description="Assembled",
                visible=True,
                refresh=True,
            )

        def add_success(self, task: Any) -> None:
            cat = _categorize_task(task.name)
            if cat and cat in self._bar_ids:
                if cat == "assemble":
                    self._finish_assemble()
                else:
                    self._ran[cat] = self._ran.get(cat, 0) + 1
                    self._progress.update(
                        self._bar_ids[cat],
                        advance=1,
                        description=self._description(cat),
                        refresh=True,
                    )

        def skip_uptodate(self, task: Any) -> None:
            cat = _categorize_task(task.name)
            if cat and cat in self._bar_ids:
                if cat == "assemble":
                    self._finish_assemble()
                else:
                    self._cached[cat] = self._cached.get(cat, 0) + 1
                    self._progress.update(
                        self._bar_ids[cat],
                        advance=1,
                        description=self._description(cat),
                        refresh=True,
                    )

        def complete_run(self) -> None:
            self._progress.stop()
            # Restore normal logging and replay buffered warnings
            for handler, level in self._orig_handler_levels:
                handler.setLevel(level)
            ss_logger = logging.getLogger("slidesonnet")
            ss_logger.removeHandler(self._warning_buffer)
            for record in self._warning_buffer.records:
                logging.root.handle(record)
            # Show failures via parent
            if self.failures or self.runtime_errors:
                super().complete_run()

    class _QuietReporter(ConsoleReporter):  # type: ignore[misc]
        """Silent reporter that only shows failures."""

        def initialize(self, tasks: Any, selected_tasks: Any) -> None:
            super().initialize(tasks, selected_tasks)
            # Suppress action logger entirely
            logging.getLogger("slidesonnet.actions").setLevel(logging.WARNING)

        def execute_task(self, task: Any) -> None:
            pass

        def add_success(self, task: Any) -> None:
            pass

        def skip_uptodate(self, task: Any) -> None:
            pass

        def complete_run(self) -> None:
            if self.failures or self.runtime_errors:
                super().complete_run()

    reporter = _QuietReporter if quiet else _ProgressReporter
    doit_config: dict[str, Any] = {
        "backend": "sqlite3",
        "dep_file": db_file,
        "verbosity": 0,
        "reporter": reporter,
    }

    class _Loader(TaskLoader2):  # type: ignore[misc]
        def load_doit_config(self) -> dict[str, Any]:
            return doit_config

        def load_tasks(self, cmd: Any, pos_args: Any) -> list[Any]:
            return tasks

    result = DoitMain(_Loader()).run(["run"])
    elapsed = time.monotonic() - start_time
    if result not in (0, None):
        raise SlideSonnetError(f"Build failed (doit exit code {result})")
    return elapsed


def export_pdfs(
    playlist_path: Path,
    output_override: Path | None = None,
) -> Path:
    """Export a concatenated PDF for all slide modules in a playlist.

    Compiles Beamer sources and runs marp --pdf for MARP modules,
    then concatenates into a single output PDF.
    Returns the output PDF path.
    """
    from slidesonnet.actions import (
        action_compile_beamer,
        action_concat_pdfs,
        action_export_pdf_beamer,
        action_export_pdf_marp,
    )

    prep = _prepare(playlist_path, output_override=output_override)
    per_module_pdfs: list[Path] = []

    for i, entry in enumerate(prep.entries, start=1):
        if entry.module_type == ModuleType.VIDEO:
            continue

        source_path = prep.playlist_dir / entry.path
        module_dir = prep.build_dir / entry.path.parent / entry.path.stem
        cache_pdf = module_dir / f"{i:02d}_{entry.path.stem}.pdf"

        if entry.module_type == ModuleType.BEAMER:
            slides_dir = module_dir / "slides"
            slides_dir.mkdir(parents=True, exist_ok=True)
            compiled_pdf = slides_dir / f"{source_path.stem}.pdf"
            action_compile_beamer(source_path, slides_dir, compiled_pdf)
            action_export_pdf_beamer(compiled_pdf, cache_pdf)
        else:
            module_dir.mkdir(parents=True, exist_ok=True)
            action_export_pdf_marp(source_path, cache_pdf)

        per_module_pdfs.append(cache_pdf)

    if not per_module_pdfs:
        raise SlideSonnetError("No slide modules to export.")

    action_concat_pdfs(per_module_pdfs, prep.pdf_output_path)
    return prep.pdf_output_path


@dataclass
class UtteranceSlide:
    """Per-slide utterance info returned by export_utterances()."""

    slide_index: int
    text: str | None  # None = skipped, "[silent]" = silent, else narration text
    voice: str | None  # Non-default voice name, or None


@dataclass
class UtteranceModule:
    """Per-module utterance group."""

    module_path: str
    slides: list[UtteranceSlide]


def export_utterances(
    playlist_path: Path,
    tts_override: Literal["piper", "elevenlabs"] | None = None,
) -> list[UtteranceModule]:
    """Export narration text for all slides, grouped by module.

    Parses slides and applies pronunciation (same as list_slides),
    but returns structured data for plain-text export. Skipped slides
    are omitted; silent slides show ``[silent]``; narrated slides show
    post-pronunciation text with optional voice prefix.
    """
    prep = _prepare(playlist_path, tts_override)
    modules: list[UtteranceModule] = []

    for entry in prep.entries:
        if entry.module_type == ModuleType.VIDEO:
            continue

        source_path = prep.playlist_dir / entry.path
        module_dir = prep.build_dir / entry.path.parent / entry.path.stem
        slides_dir = module_dir / "slides"

        parser_cls, _ = get_parser_and_extractor(entry.module_type)
        parser = parser_cls()
        slides = parser.parse(source_path, slides_dir)

        pron = prep.config.pronunciation_for(prep.config.tts.backend)
        utterance_slides: list[UtteranceSlide] = []

        for slide in slides:
            if slide.is_skip:
                continue

            if slide.has_narration:
                text = apply_pronunciation(slide.narration_raw, pron)
                # Determine non-default voice
                voice: str | None = None
                if slide.voice:
                    voice = slide.voice
                utterance_slides.append(
                    UtteranceSlide(slide_index=slide.index, text=text, voice=voice)
                )
            elif slide.annotation == SlideAnnotation.SILENT:
                utterance_slides.append(
                    UtteranceSlide(slide_index=slide.index, text="[silent]", voice=None)
                )

        modules.append(UtteranceModule(module_path=str(entry.path), slides=utterance_slides))

    return modules


def list_slides(
    playlist_path: Path,
    tts_override: Literal["piper", "elevenlabs"] | None = None,
) -> ListResult:
    """List all slides from a playlist with voice, narration, and cache info.

    Parses slides, applies pronunciation, and checks audio cache.
    Returns a :class:`ListResult` with per-slide info and TTS backend name.
    Skipped slides are excluded; silent slides show ``[silent]``.
    """
    prep = _prepare(playlist_path, tts_override)
    audio_cache_dir = prep.build_dir / "audio"
    results: list[SlideInfo] = []

    for entry in prep.entries:
        if entry.module_type == ModuleType.VIDEO:
            continue

        source_path = prep.playlist_dir / entry.path
        module_dir = prep.build_dir / entry.path.parent / entry.path.stem
        slides_dir = module_dir / "slides"

        parser_cls, _ = get_parser_and_extractor(entry.module_type)
        parser = parser_cls()
        slides = parser.parse(source_path, slides_dir)

        pron = prep.config.pronunciation_for(prep.config.tts.backend)
        for slide in slides:
            if slide.is_skip:
                continue
            voice = slide.voice or "default"
            if slide.has_narration:
                text = apply_pronunciation(slide.narration_raw, pron)

                # Apply pronunciation to parts (same as dry_run)
                slide.narration_processed = text
                slide.narration_parts_processed = [
                    apply_pronunciation(part, pron) for part in slide.narration_parts
                ]

                # Resolve voice preset (same as dry_run)
                resolved_voice = slide.voice
                if resolved_voice:
                    rv = resolve_voice(resolved_voice, prep.config.voices, prep.config.tts.backend)
                    resolved_voice = rv if rv else None

                # Check cache for all parts
                parts = slide.narration_parts_processed
                all_cached = True
                total_chars = 0
                for part_text in parts:
                    total_chars += len(part_text)
                    p = _audio_path(
                        audio_cache_dir,
                        part_text,
                        prep.tts.name(),
                        prep.tts.cache_key(),
                        resolved_voice,
                    )
                    if not _audio_cache_exists(p):
                        all_cached = False

                results.append(
                    SlideInfo(
                        module_path=str(entry.path),
                        slide_index=slide.index,
                        voice=voice,
                        text=text,
                        cached=all_cached,
                        chars=total_chars,
                    )
                )
            else:
                if slide.annotation == SlideAnnotation.SILENT:
                    text = "[silent]"
                else:
                    text = "[no annotation]"
                results.append(
                    SlideInfo(
                        module_path=str(entry.path),
                        slide_index=slide.index,
                        voice=voice,
                        text=text,
                        cached=None,
                        chars=0,
                    )
                )

    return ListResult(slides=results, tts_backend=prep.config.tts.backend)
