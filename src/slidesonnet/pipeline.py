"""Build pipeline: orchestrates doit-based incremental builds."""

from __future__ import annotations

import logging
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
    TimeElapsedColumn,
)

from dotenv import load_dotenv

from slidesonnet.actions import get_parser_and_extractor
from slidesonnet.config import load_config
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.hashing import _BACKEND_EXTENSIONS
from slidesonnet.hashing import audio_path as _audio_path
from slidesonnet.models import (
    ModuleType,
    PlaylistEntry,
    ProjectConfig,
    resolve_voice,
)
from slidesonnet.playlist import parse_playlist
from slidesonnet.tasks import generate_tasks
from slidesonnet.tts import create_tts
from slidesonnet.tts.base import TTSEngine
from slidesonnet.tts.pronunciation import apply_pronunciation, load_pronunciation_files

logger = logging.getLogger(__name__)

_DEFAULT_JOBS = 3
# ElevenLabs concurrent request limits by plan:
# Free=2, Starter=3, Creator=5, Pro=10, Scale/Business=15
_ELEVENLABS_MAX_JOBS = 2


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


def _prepare(
    playlist_path: Path,
    tts_override: Literal["piper", "elevenlabs"] | None = None,
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
    config.pronunciation = load_pronunciation_files(config.pronunciation_files)

    # Create TTS engine
    tts = create_tts(config)

    # Output path
    output_path = playlist_dir / (playlist_path.stem + ".mp4")

    return _PreparedBuild(
        playlist_path=playlist_path,
        playlist_dir=playlist_dir,
        build_dir=build_dir,
        config=config,
        entries=entries,
        tts=tts,
        output_path=output_path,
    )


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
            slide.narration_processed = apply_pronunciation(
                slide.narration_raw, prep.config.pronunciation
            )
            slide.narration_parts_processed = [
                apply_pronunciation(part, prep.config.pronunciation)
                for part in slide.narration_parts
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


def build(
    playlist_path: Path,
    tts_override: Literal["piper", "elevenlabs"] | None = None,
    force: bool = False,
    jobs: int | None = None,
) -> Path:
    """Execute the full build pipeline for a playlist.

    Returns path to the final output video.
    """
    prep = _prepare(playlist_path, tts_override)

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
    )

    # Run doit
    _run_doit(task_list, prep.build_dir, force, jobs=jobs, tts_backend=prep.config.tts.backend)

    logger.info("Done: %s", prep.output_path)
    return prep.output_path


def _run_doit(
    task_list: list[dict[str, Any]],
    build_dir: Path,
    force: bool,
    jobs: int | None = None,
    tts_backend: str = "piper",
) -> None:
    """Run doit programmatically with the given tasks."""
    from doit.cmd_base import TaskLoader2
    from doit.doit_cmd import DoitMain
    from doit.reporter import ConsoleReporter
    from doit.task import dict_to_task

    # Resolve effective job count
    effective_jobs = _DEFAULT_JOBS if jobs is None else jobs
    if tts_backend == "elevenlabs" and effective_jobs > _ELEVENLABS_MAX_JOBS:
        effective_jobs = _ELEVENLABS_MAX_JOBS

    db_file = str(build_dir / ".doit.db")
    tasks = [dict_to_task(t) for t in task_list]

    _SLIDE_PREFIXES = ("compile_beamer:", "extract_images:", "export_pdf:")
    _AUDIO_PREFIXES = ("tts:", "concat_audio:")
    _VIDEO_PREFIXES = ("compose:",)
    _VIDEO_EXACT = ("assemble",)

    def _categorize_task(name: str) -> str | None:
        if name.startswith(_SLIDE_PREFIXES):
            return "slides"
        if name.startswith(_AUDIO_PREFIXES):
            return "audio"
        if name.startswith(_VIDEO_PREFIXES) or name in _VIDEO_EXACT:
            return "video"
        return None

    class _ProgressReporter(ConsoleReporter):  # type: ignore[misc]
        """Reporter that shows grouped progress bars for slides/audio/video."""

        def initialize(self, tasks: Any, selected_tasks: Any) -> None:
            super().initialize(tasks, selected_tasks)
            self._start_time = time.monotonic()

            # Count tasks per category
            counts: dict[str, int] = {"slides": 0, "audio": 0, "video": 0}
            for name in selected_tasks:
                cat = _categorize_task(name)
                if cat:
                    counts[cat] += 1

            # Suppress action logger to avoid visual interference
            logging.getLogger("slidesonnet.actions").setLevel(logging.WARNING)

            # Create rich progress display
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
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
            self._progress.start()

        def execute_task(self, task: Any) -> None:
            pass

        def add_success(self, task: Any) -> None:
            cat = _categorize_task(task.name)
            if cat and cat in self._bar_ids:
                self._progress.advance(self._bar_ids[cat])

        def skip_uptodate(self, task: Any) -> None:
            cat = _categorize_task(task.name)
            if cat and cat in self._bar_ids:
                self._progress.advance(self._bar_ids[cat])

        def complete_run(self) -> None:
            self._progress.stop()
            elapsed = time.monotonic() - self._start_time
            self.write(f"Build complete ({elapsed:.1f}s)\n")
            # Still show failures via parent
            if self.failures or self.runtime_errors:
                super().complete_run()

    doit_config: dict[str, Any] = {
        "backend": "sqlite3",
        "dep_file": db_file,
        "verbosity": 0,
        "reporter": _ProgressReporter,
    }
    if effective_jobs > 0:
        doit_config["num_process"] = effective_jobs
        doit_config["par_type"] = "thread"

    class _Loader(TaskLoader2):  # type: ignore[misc]
        def load_doit_config(self) -> dict[str, Any]:
            return doit_config

        def load_tasks(self, cmd: Any, pos_args: Any) -> list[Any]:
            return tasks

    run_args = ["run"]
    if force:
        run_args.append("--always-execute")

    result = DoitMain(_Loader()).run(run_args)
    if result not in (0, None):
        raise SlideSonnetError(f"Build failed (doit exit code {result})")
