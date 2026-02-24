"""doit task generators for the slideSonnet build pipeline.

Text parsing is done eagerly (fast). Image extraction, TTS synthesis,
video composition, and assembly are generated as doit tasks for
incremental builds and parallel execution.

Task graph per module:
    extract_images → compose (per slide)
    tts (per slide) → compose (per slide)
    compose (all) → concat → assemble
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from doit.tools import config_changed

from slidesonnet.models import (
    ModuleType,
    PlaylistEntry,
    ProjectConfig,
)
from slidesonnet.parsers.base import SlideParser
from slidesonnet.tts.base import TTSEngine
from slidesonnet.tts.pronunciation import apply_pronunciation
from slidesonnet.video import composer


def generate_tasks(
    entries: list[PlaylistEntry],
    config: ProjectConfig,
    tts: TTSEngine,
    build_dir: Path,
    playlist_dir: Path,
    output_path: Path,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Generate doit task dicts for the full build pipeline.

    Each dict is suitable for doit.task.dict_to_task(). Task names use
    the "group:subtask" format for subtasks.
    """
    audio_cache_dir = build_dir / "audio"
    module_videos: list[Path] = []
    all_tasks: list[dict[str, Any]] = []

    for i, entry in enumerate(entries, start=1):
        source_path = playlist_dir / entry.path
        module_dir = build_dir / entry.path.parent / entry.path.stem
        module_output = module_dir / "module.mp4"
        module_videos.append(module_output)
        module_name = f"{i:02d}_{entry.path.stem}"

        if entry.module_type == ModuleType.VIDEO:
            all_tasks.append(
                {
                    "name": f"passthrough:{module_name}",
                    "actions": [(_action_passthrough, [source_path, module_output])],
                    "file_dep": [str(source_path)],
                    "targets": [str(module_output)],
                    "verbosity": 2,
                }
            )
            continue

        # Get parser and extract function
        parser_cls, extract_fn = _get_parser_and_extractor(entry.module_type)

        # Parse slides eagerly (just reading text — fast)
        slides_dir = module_dir / "slides"
        parser = parser_cls()
        slides = parser.parse(source_path, slides_dir)

        # Preprocess pronunciation and resolve voice presets
        for slide in slides:
            if slide.has_narration:
                slide.narration_processed = apply_pronunciation(
                    slide.narration_raw, config.pronunciation
                )
                if slide.voice:
                    voice_cfg = config.voices.get(slide.voice)
                    if voice_cfg:
                        slide.voice = voice_cfg.backend_voice
                    else:
                        print(
                            f"WARNING: {source_path} slide {slide.index}: "
                            f"unknown voice '{slide.voice}'",
                            file=sys.stderr,
                        )

        utterances_dir = module_dir / "utterances"
        segments_dir = module_dir / "segments"
        manifest_path = slides_dir / "manifest.json"

        # Task: extract images
        all_tasks.append(
            {
                "name": f"extract_images:{module_name}",
                "actions": [
                    (_action_extract_images, [source_path, slides_dir, extract_fn, manifest_path])
                ],
                "file_dep": [str(source_path)],
                "targets": [str(manifest_path)],
                "verbosity": 2,
            }
        )

        # Per-slide tasks
        segment_paths: list[Path] = []
        for slide in slides:
            slide_id = f"{module_name}_slide_{slide.index:03d}"

            # TTS task for narrated slides
            if slide.has_narration:
                # Include voice in hash so different voices produce different cache entries
                hash_input = slide.narration_processed
                if slide.voice:
                    hash_input += f"\0voice={slide.voice}"
                text_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]
                cached_audio = audio_cache_dir / f"{text_hash}.wav"
                slide.audio_path = cached_audio

                all_tasks.append(
                    {
                        "name": f"tts:{slide_id}",
                        "actions": [
                            (
                                _action_tts,
                                [
                                    slide.narration_processed,
                                    cached_audio,
                                    tts,
                                    utterances_dir / f"slide_{slide.index:03d}.txt",
                                    force,
                                    slide.voice,
                                ],
                            )
                        ],
                        "targets": [str(cached_audio)],
                        "uptodate": [config_changed(hash_input)],
                        "verbosity": 2,
                    }
                )

            # Skip slides don't get composed
            if slide.is_skip:
                continue

            seg_path = segments_dir / f"seg_{slide.index:03d}.mp4"
            segment_paths.append(seg_path)

            # Compose task
            task_deps = [f"extract_images:{module_name}"]
            file_deps = [str(manifest_path)]

            if slide.has_narration and slide.audio_path:
                task_deps.append(f"tts:{slide_id}")
                file_deps.append(str(slide.audio_path))

                all_tasks.append(
                    {
                        "name": f"compose:{slide_id}",
                        "actions": [
                            (
                                _action_compose_narrated,
                                [
                                    manifest_path,
                                    slide.index,
                                    slide.audio_path,
                                    seg_path,
                                    config,
                                ],
                            )
                        ],
                        "file_dep": file_deps,
                        "task_dep": task_deps,
                        "targets": [str(seg_path)],
                        "verbosity": 2,
                    }
                )
            else:
                all_tasks.append(
                    {
                        "name": f"compose:{slide_id}",
                        "actions": [
                            (
                                _action_compose_silent,
                                [
                                    manifest_path,
                                    slide.index,
                                    seg_path,
                                    config,
                                ],
                            )
                        ],
                        "file_dep": file_deps,
                        "task_dep": task_deps,
                        "targets": [str(seg_path)],
                        "verbosity": 2,
                    }
                )

        # Task: module concat
        all_tasks.append(
            {
                "name": f"concat:{module_name}",
                "actions": [(_action_concat, [segment_paths, module_output, config])],
                "file_dep": [str(p) for p in segment_paths],
                "targets": [str(module_output)],
                "uptodate": [config_changed({"crossfade": config.video.crossfade})],
                "verbosity": 2,
            }
        )

    # Task: final assembly
    all_tasks.append(
        {
            "name": "assemble",
            "actions": [(_action_assemble, [module_videos, output_path, config])],
            "file_dep": [str(p) for p in module_videos],
            "targets": [str(output_path)],
            "uptodate": [config_changed({"crossfade": config.video.crossfade})],
            "verbosity": 2,
        }
    )

    return all_tasks


# --- Action functions (executed by doit) ---


def _action_passthrough(source: Path, output: Path) -> None:
    """Copy a video file as-is."""
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)


def _action_extract_images(
    source: Path,
    slides_dir: Path,
    extract_fn: Callable[[Path, Path], list[Path]],
    manifest_path: Path,
) -> None:
    """Run image extraction and write manifest."""
    slides_dir.mkdir(parents=True, exist_ok=True)
    images = extract_fn(source, slides_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps([str(p) for p in images]),
        encoding="utf-8",
    )


def _action_tts(
    text: str,
    output_path: Path,
    tts: TTSEngine,
    utterance_path: Path,
    force: bool,
    voice: str | None = None,
) -> None:
    """Synthesize TTS audio with content-addressed caching."""
    utterance_path.parent.mkdir(parents=True, exist_ok=True)
    utterance_path.write_text(text, encoding="utf-8")

    if output_path.exists() and not force:
        print("  slide [cached]")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print("  slide synthesizing...")
    tts.synthesize(text, output_path, voice=voice)


def _action_compose_narrated(
    manifest_path: Path,
    slide_index: int,
    audio_path: Path,
    output: Path,
    config: ProjectConfig,
) -> None:
    """Compose a narrated slide segment."""
    images = json.loads(manifest_path.read_text(encoding="utf-8"))
    image = Path(images[slide_index - 1])
    duration = composer.get_duration(audio_path)
    composer.compose_segment(
        image=image,
        audio=audio_path,
        output=output,
        duration=duration,
        pad_seconds=config.video.pad_seconds,
        pre_silence=config.video.pre_silence,
        resolution=config.video.resolution,
        fps=config.video.fps,
        crf=config.video.crf,
    )


def _action_compose_silent(
    manifest_path: Path,
    slide_index: int,
    output: Path,
    config: ProjectConfig,
) -> None:
    """Compose a silent slide segment."""
    images = json.loads(manifest_path.read_text(encoding="utf-8"))
    image = Path(images[slide_index - 1])
    composer.compose_silent_segment(
        image=image,
        output=output,
        duration=config.video.silence_duration,
        resolution=config.video.resolution,
        fps=config.video.fps,
        crf=config.video.crf,
    )


def _action_concat(segments: list[Path], output: Path, config: ProjectConfig) -> None:
    """Concatenate segments into a module video."""
    if len(segments) == 1:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(segments[0], output)
    elif segments:
        if config.video.crossfade > 0:
            composer.concatenate_segments_xfade(
                segments,
                output,
                crossfade=config.video.crossfade,
                crf=config.video.crf,
            )
        else:
            composer.concatenate_segments(segments, output)


def _action_assemble(module_videos: list[Path], output: Path, config: ProjectConfig) -> None:
    """Assemble module videos into final output."""
    if len(module_videos) == 1:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(module_videos[0], output)
    elif module_videos:
        if config.video.crossfade > 0:
            composer.concatenate_segments_xfade(
                module_videos,
                output,
                crossfade=config.video.crossfade,
                crf=config.video.crf,
            )
        else:
            composer.concatenate_segments(module_videos, output)


# --- Helpers ---


def _get_parser_and_extractor(
    module_type: ModuleType,
) -> tuple[type[SlideParser], Callable[[Path, Path], list[Path]]]:
    """Get parser class and image extraction function for a module type."""
    if module_type == ModuleType.MARP:
        from slidesonnet.parsers.marp import MarpParser
        from slidesonnet.parsers.marp import extract_images as marp_extract

        return MarpParser, marp_extract
    elif module_type == ModuleType.BEAMER:
        from slidesonnet.parsers.beamer import BeamerParser
        from slidesonnet.parsers.beamer import extract_images as beamer_extract

        return BeamerParser, beamer_extract
    else:
        raise ValueError(f"No parser for module type: {module_type}")
