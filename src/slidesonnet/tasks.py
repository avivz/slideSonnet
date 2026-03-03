"""doit task generators for the slideSonnet build pipeline.

Text parsing is done eagerly (fast). Image extraction, TTS synthesis,
video composition, and assembly are generated as doit tasks for
incremental builds.

Task graph:
    extract_images → compose (per slide)
    tts (per slide) → compose (per slide)
    compose (all slides, all modules) → assemble
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from doit.tools import config_changed

from slidesonnet.exceptions import SlideSonnetError
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
from slidesonnet.hashing import _BACKEND_EXTENSIONS
from slidesonnet.hashing import audio_path as _audio_path
from slidesonnet.hashing import concat_filename as _concat_filename
from slidesonnet.models import (
    ModuleType,
    PlaylistEntry,
    ProjectConfig,
    resolve_voice,
)
from slidesonnet.parsers.beamer import visual_hash as beamer_visual_hash
from slidesonnet.parsers.marp import visual_hash as marp_visual_hash
from slidesonnet.tts.base import TTSEngine
from slidesonnet.tts.pronunciation import apply_pronunciation

logger = logging.getLogger(__name__)


def _audio_cache_valid(task: Any, values: Any) -> bool:  # noqa: ANN401
    """Check that target audio file exists and is non-empty.

    If the target doesn't exist, check for a file with the old extension
    (.wav ↔ .mp3) and rename it — transparently migrating existing
    ElevenLabs caches from .wav to .mp3 without re-synthesizing.
    """
    p = Path(task.targets[0])
    if p.exists() and p.stat().st_size > 0:
        return True
    # Try migrating from old extension
    _swap = {v: k for k, v in _BACKEND_EXTENSIONS.items()}
    _swap.update({k: v for v, k in _BACKEND_EXTENSIONS.items()})
    # Build a simple extension swap: .wav ↔ .mp3
    suffix = p.suffix
    alt_suffixes = {ext for ext in _BACKEND_EXTENSIONS.values() if ext != suffix}
    for alt in alt_suffixes:
        alt_path = p.with_suffix(alt)
        if alt_path.exists() and alt_path.stat().st_size > 0:
            alt_path.rename(p)
            logger.info("Migrated cache: %s → %s", alt_path.name, p.name)
            return True
    return False


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

        # Read source once for visual hashing (annotation-aware cache key)
        try:
            source_text = source_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise SlideSonnetError(f"Module file not found: {entry.path}") from None

        # Parse slides eagerly (just reading text — fast)
        slides_dir = module_dir / "slides"
        parser = parser_cls()
        slides = parser.parse(source_path, slides_dir)

        # Preprocess pronunciation and resolve voice presets
        pron = config.pronunciation_for(config.tts.backend)
        for slide in slides:
            if slide.has_narration:
                slide.narration_processed = apply_pronunciation(slide.narration_raw, pron)
                slide.narration_parts_processed = [
                    apply_pronunciation(part, pron) for part in slide.narration_parts
                ]
                if slide.voice:
                    preset = slide.voice
                    resolved = resolve_voice(preset, config.voices, config.tts.backend)
                    if resolved:
                        slide.voice = resolved
                    elif preset not in config.voices:
                        logger.warning(
                            "%s slide %d: unknown voice '%s'",
                            source_path,
                            slide.index,
                            preset,
                        )
                    else:
                        logger.warning(
                            "%s slide %d: voice '%s' has no mapping for backend '%s'",
                            source_path,
                            slide.index,
                            preset,
                            config.tts.backend,
                        )
                        slide.voice = None

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
                    "file_dep": [],
                    "targets": [str(cache_pdf)],
                    "uptodate": [config_changed({"visual_hash": beamer_visual_hash(source_text)})],
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
            # MARP: extract_images (visual-hash tracks annotation-stripped content)
            all_tasks.append(
                {
                    "name": f"extract_images:{module_name}",
                    "actions": [
                        (
                            action_extract_images,
                            [source_path, slides_dir, extract_fn, manifest_path],
                        )
                    ],
                    "file_dep": css_deps,
                    "targets": [str(manifest_path)],
                    "uptodate": [config_changed({"visual_hash": marp_visual_hash(source_text)})],
                    "verbosity": 2,
                }
            )

            # export_pdf: marp --pdf (visual-hash tracks annotation-stripped content)
            all_tasks.append(
                {
                    "name": f"export_pdf:{module_name}",
                    "actions": [(action_export_pdf_marp, [source_path, pdf_output_path])],
                    "file_dep": css_deps,
                    "targets": [str(pdf_output_path)],
                    "uptodate": [config_changed({"visual_hash": marp_visual_hash(source_text)})],
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
                        cached_part = _audio_path(
                            audio_cache_dir, part_text, tts.name(), tts.cache_key(), slide.voice
                        )
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
                                "uptodate": [_audio_cache_valid],
                                "verbosity": 2,
                            }
                        )

                    # Content-address the concat output by hashing all part paths
                    concat_audio = audio_cache_dir / _concat_filename(part_audio_paths)
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
                    cached_audio = _audio_path(
                        audio_cache_dir,
                        slide.narration_processed,
                        tts.name(),
                        tts.cache_key(),
                        slide.voice,
                    )
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
                            "uptodate": [_audio_cache_valid],
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
                        "uptodate": [
                            config_changed(
                                {
                                    "pad_seconds": config.video.pad_seconds,
                                    "pre_silence": config.video.pre_silence,
                                    "resolution": config.video.resolution,
                                    "fps": config.video.fps,
                                    "crf": config.video.crf,
                                    "preset": config.video.preset,
                                }
                            )
                        ],
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
                                    slide.silence_override,
                                ],
                            )
                        ],
                        "file_dep": file_deps,
                        "task_dep": task_deps,
                        "targets": [str(seg_path)],
                        "uptodate": [
                            config_changed(
                                {
                                    "silence_duration": config.video.silence_duration,
                                    "silence_override": slide.silence_override,
                                    "resolution": config.video.resolution,
                                    "fps": config.video.fps,
                                    "crf": config.video.crf,
                                    "preset": config.video.preset,
                                }
                            )
                        ],
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
            "uptodate": [
                config_changed(
                    {
                        "crossfade": config.video.crossfade,
                        "crf": config.video.crf,
                        "preset": config.video.preset,
                    }
                )
            ],
            "verbosity": 2,
        }
    )

    return all_tasks
