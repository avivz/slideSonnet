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
import logging
from pathlib import Path
from typing import Any

from doit.tools import config_changed

from slidesonnet.actions import (
    action_assemble,
    action_compose_narrated,
    action_compose_silent,
    action_concat,
    action_extract_images,
    action_passthrough,
    action_tts,
    get_parser_and_extractor,
)
from slidesonnet.models import (
    ModuleType,
    PlaylistEntry,
    ProjectConfig,
)
from slidesonnet.tts.base import TTSEngine
from slidesonnet.tts.pronunciation import apply_pronunciation

logger = logging.getLogger(__name__)


def generate_tasks(
    entries: list[PlaylistEntry],
    config: ProjectConfig,
    tts: TTSEngine,
    build_dir: Path,
    playlist_dir: Path,
    output_path: Path,
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
                    "actions": [(action_passthrough, [source_path, module_output])],
                    "file_dep": [str(source_path)],
                    "targets": [str(module_output)],
                    "verbosity": 2,
                }
            )
            continue

        # Get parser and extract function
        parser_cls, extract_fn = get_parser_and_extractor(entry.module_type)

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
                        logger.warning(
                            "%s slide %d: unknown voice '%s'",
                            source_path,
                            slide.index,
                            slide.voice,
                        )

        utterances_dir = module_dir / "utterances"
        segments_dir = module_dir / "segments"
        manifest_path = slides_dir / "manifest.json"

        # Task: extract images
        all_tasks.append(
            {
                "name": f"extract_images:{module_name}",
                "actions": [
                    (action_extract_images, [source_path, slides_dir, extract_fn, manifest_path])
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
                                action_tts,
                                [
                                    slide.narration_processed,
                                    cached_audio,
                                    tts,
                                    utterances_dir / f"slide_{slide.index:03d}.txt",
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
                                action_compose_narrated,
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
                                action_compose_silent,
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
                "actions": [(action_concat, [segment_paths, module_output, config])],
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
            "actions": [(action_assemble, [module_videos, output_path, config])],
            "file_dep": [str(p) for p in module_videos],
            "targets": [str(output_path)],
            "uptodate": [config_changed({"crossfade": config.video.crossfade})],
            "verbosity": 2,
        }
    )

    return all_tasks
