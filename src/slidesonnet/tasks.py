"""doit task generators for the slideSonnet build pipeline.

Text parsing is done eagerly (fast). Image extraction, TTS synthesis,
video composition, and assembly are generated as doit tasks for
incremental builds and parallel execution.

Task graph:
    extract_images → compose (per slide)
    tts (per slide) → compose (per slide)
    compose (all slides, all modules) → assemble
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from doit.tools import config_changed

from slidesonnet.actions import (
    action_assemble,
    action_compile_beamer,
    action_compose_narrated,
    action_compose_silent,
    action_concat_audio,
    action_export_pdf_beamer,
    action_export_pdf_marp,
    action_extract_images,
    action_extract_images_beamer,
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
    all_segments: list[Path] = []
    all_tasks: list[dict[str, Any]] = []

    for i, entry in enumerate(entries, start=1):
        source_path = playlist_dir / entry.path
        module_dir = build_dir / entry.path.parent / entry.path.stem
        module_name = f"{i:02d}_{entry.path.stem}"

        if entry.module_type == ModuleType.VIDEO:
            all_segments.append(source_path)
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
                slide.narration_parts_processed = [
                    apply_pronunciation(part, config.pronunciation)
                    for part in slide.narration_parts
                ]
                if slide.voice:
                    voice_cfg = config.voices.get(slide.voice)
                    if voice_cfg:
                        resolved = voice_cfg.resolve(config.tts.backend)
                        if resolved:
                            slide.voice = resolved
                        else:
                            logger.warning(
                                "%s slide %d: voice '%s' has no mapping for backend '%s'",
                                source_path,
                                slide.index,
                                slide.voice,
                                config.tts.backend,
                            )
                            slide.voice = None
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

        # Task: extract images (+ compile step for Beamer)
        css_deps = sorted(str(p) for p in source_path.parent.glob("*.css"))
        pdf_output_path = playlist_dir / f"{entry.path.stem}.pdf"

        if entry.module_type == ModuleType.BEAMER:
            cache_pdf = slides_dir / f"{source_path.stem}.pdf"

            # compile_beamer: pdflatex → PDF in cache
            all_tasks.append(
                {
                    "name": f"compile_beamer:{module_name}",
                    "actions": [(action_compile_beamer, [source_path, slides_dir, cache_pdf])],
                    "file_dep": [str(source_path)],
                    "targets": [str(cache_pdf)],
                    "verbosity": 2,
                }
            )

            # extract_images: pdftoppm on compiled PDF → PNGs
            all_tasks.append(
                {
                    "name": f"extract_images:{module_name}",
                    "actions": [
                        (
                            action_extract_images_beamer,
                            [cache_pdf, slides_dir, manifest_path],
                        )
                    ],
                    "file_dep": [str(cache_pdf)],
                    "task_dep": [f"compile_beamer:{module_name}"],
                    "targets": [str(manifest_path)],
                    "verbosity": 2,
                }
            )

            # export_pdf: copy compiled PDF to playlist directory
            all_tasks.append(
                {
                    "name": f"export_pdf:{module_name}",
                    "actions": [(action_export_pdf_beamer, [cache_pdf, pdf_output_path])],
                    "file_dep": [str(cache_pdf)],
                    "task_dep": [f"compile_beamer:{module_name}"],
                    "targets": [str(pdf_output_path)],
                    "verbosity": 2,
                }
            )
        else:
            # MARP: extract_images unchanged
            all_tasks.append(
                {
                    "name": f"extract_images:{module_name}",
                    "actions": [
                        (
                            action_extract_images,
                            [source_path, slides_dir, extract_fn, manifest_path],
                        )
                    ],
                    "file_dep": [str(source_path)] + css_deps,
                    "targets": [str(manifest_path)],
                    "verbosity": 2,
                }
            )

            # export_pdf: marp --pdf
            all_tasks.append(
                {
                    "name": f"export_pdf:{module_name}",
                    "actions": [(action_export_pdf_marp, [source_path, pdf_output_path])],
                    "file_dep": [str(source_path)] + css_deps,
                    "targets": [str(pdf_output_path)],
                    "verbosity": 2,
                }
            )

        # Per-slide tasks
        segment_paths: list[Path] = []
        for slide in slides:
            slide_id = f"{module_name}_slide_{slide.index:03d}"

            # TTS task for narrated slides
            if slide.has_narration:
                parts = slide.narration_parts_processed

                if len(parts) > 1:
                    # Multi-part: generate per-part TTS tasks + concat
                    part_audio_paths: list[Path] = []
                    for j, part_text in enumerate(parts):
                        hash_input = part_text
                        hash_input += f"\0tts={tts.cache_key()}"
                        if slide.voice:
                            hash_input += f"\0voice={slide.voice}"
                        text_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]
                        cached_part = audio_cache_dir / f"{text_hash}.wav"
                        part_audio_paths.append(cached_part)

                        all_tasks.append(
                            {
                                "name": f"tts:{slide_id}_part_{j:03d}",
                                "actions": [
                                    (
                                        action_tts,
                                        [
                                            part_text,
                                            cached_part,
                                            tts,
                                            utterances_dir
                                            / f"slide_{slide.index:03d}_part_{j:03d}.txt",
                                            slide.voice,
                                        ],
                                    )
                                ],
                                "targets": [str(cached_part)],
                                "uptodate": [lambda task, values: Path(task.targets[0]).exists()],
                                "verbosity": 2,
                            }
                        )

                    # Content-address the concat output by hashing all part paths
                    concat_hash_input = "\0".join(str(p) for p in part_audio_paths)
                    concat_hash = hashlib.sha256(concat_hash_input.encode("utf-8")).hexdigest()[:16]
                    concat_audio = audio_cache_dir / f"{concat_hash}_concat.wav"
                    slide.audio_path = concat_audio

                    all_tasks.append(
                        {
                            "name": f"concat_audio:{slide_id}",
                            "actions": [(action_concat_audio, [part_audio_paths, concat_audio])],
                            "file_dep": [str(p) for p in part_audio_paths],
                            "task_dep": [f"tts:{slide_id}_part_{j:03d}" for j in range(len(parts))],
                            "targets": [str(concat_audio)],
                            "verbosity": 2,
                        }
                    )
                else:
                    # Single part (or no parts): identical to previous behavior
                    hash_input = slide.narration_processed
                    hash_input += f"\0tts={tts.cache_key()}"
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
                            "uptodate": [lambda task, values: Path(task.targets[0]).exists()],
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
                # For multi-part, depend on concat_audio; for single-part, depend on tts
                if len(slide.narration_parts_processed) > 1:
                    task_deps.append(f"concat_audio:{slide_id}")
                else:
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
                                    slide.image_index,
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
                                    slide.image_index,
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

        all_segments.extend(segment_paths)

    # Task: final assembly (directly from all per-slide segments)
    all_tasks.append(
        {
            "name": "assemble",
            "actions": [(action_assemble, [all_segments, output_path, config])],
            "file_dep": [str(p) for p in all_segments],
            "targets": [str(output_path)],
            "uptodate": [config_changed({"crossfade": config.video.crossfade})],
            "verbosity": 2,
        }
    )

    return all_tasks
