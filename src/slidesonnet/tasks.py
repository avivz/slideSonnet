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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doit.tools import config_changed

from slidesonnet.models import SlideNarration

from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.actions import (
    action_assemble,
    action_compile_beamer,
    action_compose_narrated,
    action_compose_silent,
    action_concat_audio,
    action_concat_pdfs,
    action_export_pdf_beamer,
    action_export_pdf_marp,
    action_extract_images,
    action_extract_images_beamer,
    action_tts,
    get_module_handlers,
)
from slidesonnet.hashing import audio_path as _audio_path
from slidesonnet.hashing import concat_filename as _concat_filename
from slidesonnet.hashing import migrate_and_check_audio_cache
from slidesonnet.models import (
    ModuleType,
    PlaylistEntry,
    ProjectConfig,
    resolve_voice,
)
from slidesonnet.tts.base import TTSEngine
from slidesonnet.tts.pronunciation import apply_pronunciation

logger = logging.getLogger(__name__)


def _audio_cache_valid(task: Any, values: Any) -> bool:  # noqa: ANN401
    """Check that target audio file exists and is non-empty.

    doit uptodate callable: delegates to the shared cache migration helper
    in hashing.py, which transparently renames .wav ↔ .mp3 so engine
    switches don't re-synthesize.
    """
    return migrate_and_check_audio_cache(Path(task.targets[0]))


@dataclass
class _ModuleContext:
    """Resolved paths + helpers for one slide module.

    Bundles the per-module state that ``generate_tasks`` reuses across
    its three stages (slides, tts, compose) so each helper function has
    one argument instead of many.
    """

    entry_index: int  # 1-based index in the playlist
    source_path: Path
    module_dir: Path
    module_name: str  # e.g. "01_intro"
    slides_dir: Path
    utterances_dir: Path
    segments_dir: Path
    manifest_path: Path
    module_pdf_path: Path
    css_deps: list[str]
    visual_hash: str
    slides: list[SlideNarration]


def _apply_pronunciation_and_voices(
    slides: list[SlideNarration],
    config: ProjectConfig,
    source_path: Path,
) -> None:
    """Mutate *slides* in place: apply pronunciation and resolve voice presets.

    Unlike ``iter_prepared_slides`` this variant logs warnings for unknown
    voice presets and presets without a backend mapping — behavior that's
    only meaningful when we are actually building (i.e. from ``generate_tasks``).
    """
    pron = config.pronunciation_for(config.tts.backend)
    for slide in slides:
        if not slide.has_narration:
            continue
        slide.narration_processed = apply_pronunciation(slide.narration_raw, pron)
        slide.narration_parts_processed = [
            apply_pronunciation(part, pron) for part in slide.narration_parts
        ]
        if not slide.voice:
            continue
        preset = slide.voice
        resolved = resolve_voice(preset, config.voices, config.tts.backend)
        if resolved:
            slide.voice = resolved
        elif preset not in config.voices:
            logger.warning("%s slide %d: unknown voice '%s'", source_path, slide.index, preset)
        else:
            logger.warning(
                "%s slide %d: voice '%s' has no mapping for backend '%s'",
                source_path,
                slide.index,
                preset,
                config.tts.backend,
            )
            slide.voice = None


def _build_module_context(
    entry_index: int,
    entry: PlaylistEntry,
    build_dir: Path,
    playlist_dir: Path,
    config: ProjectConfig,
) -> _ModuleContext:
    """Read the source, parse slides, resolve paths for one module."""
    source_path = playlist_dir / entry.path
    module_dir = build_dir / entry.path.parent / entry.path.stem
    module_name = f"{entry_index:02d}_{entry.path.stem}"
    slides_dir = module_dir / "slides"

    try:
        source_text = source_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SlideSonnetError(f"Module file not found: {entry.path}") from None

    handlers = get_module_handlers(entry.module_type)
    parser = handlers.parser_cls()
    slides = parser.parse(source_path, slides_dir)
    _apply_pronunciation_and_voices(slides, config, source_path)

    return _ModuleContext(
        entry_index=entry_index,
        source_path=source_path,
        module_dir=module_dir,
        module_name=module_name,
        slides_dir=slides_dir,
        utterances_dir=module_dir / "utterances",
        segments_dir=module_dir / "segments",
        manifest_path=slides_dir / "manifest.json",
        module_pdf_path=module_dir / f"{entry.path.stem}.pdf",
        css_deps=sorted(str(p) for p in source_path.parent.glob("*.css")),
        visual_hash=handlers.visual_hash_fn(source_text),
        slides=slides,
    )


def _build_slides_tasks(ctx: _ModuleContext, entry: PlaylistEntry) -> list[dict[str, Any]]:
    """Build extract_images + export_pdf (+ compile_beamer) tasks for one module."""
    tasks: list[dict[str, Any]] = []
    visual_uptodate = [config_changed({"visual_hash": ctx.visual_hash})]

    if entry.module_type == ModuleType.BEAMER:
        cache_pdf = ctx.slides_dir / f"{ctx.source_path.stem}.pdf"
        compile_name = f"compile_beamer:{ctx.module_name}"

        tasks.append(
            {
                "name": compile_name,
                "actions": [(action_compile_beamer, [ctx.source_path, ctx.slides_dir, cache_pdf])],
                "file_dep": [],
                "targets": [str(cache_pdf)],
                "uptodate": visual_uptodate,
                "verbosity": 2,
            }
        )
        tasks.append(
            {
                "name": f"extract_images:{ctx.module_name}",
                "actions": [
                    (
                        action_extract_images_beamer,
                        [cache_pdf, ctx.slides_dir, ctx.manifest_path],
                    )
                ],
                "file_dep": [str(cache_pdf)],
                "task_dep": [compile_name],
                "targets": [str(ctx.manifest_path)],
                "verbosity": 2,
            }
        )
        tasks.append(
            {
                "name": f"export_pdf:{ctx.module_name}",
                "actions": [(action_export_pdf_beamer, [cache_pdf, ctx.module_pdf_path])],
                "file_dep": [str(cache_pdf)],
                "task_dep": [compile_name],
                "targets": [str(ctx.module_pdf_path)],
                "verbosity": 2,
            }
        )
    else:
        handlers = get_module_handlers(entry.module_type)
        extract_fn = handlers.extract_fn
        tasks.append(
            {
                "name": f"extract_images:{ctx.module_name}",
                "actions": [
                    (
                        action_extract_images,
                        [ctx.source_path, ctx.slides_dir, extract_fn, ctx.manifest_path],
                    )
                ],
                "file_dep": ctx.css_deps,
                "targets": [str(ctx.manifest_path)],
                "uptodate": visual_uptodate,
                "verbosity": 2,
            }
        )
        tasks.append(
            {
                "name": f"export_pdf:{ctx.module_name}",
                "actions": [(action_export_pdf_marp, [ctx.source_path, ctx.module_pdf_path])],
                "file_dep": ctx.css_deps,
                "targets": [str(ctx.module_pdf_path)],
                "uptodate": visual_uptodate,
                "verbosity": 2,
            }
        )

    return tasks


def _build_tts_tasks(
    ctx: _ModuleContext,
    tts: TTSEngine,
    audio_cache_dir: Path,
) -> list[dict[str, Any]]:
    """Build TTS + concat_audio tasks for each narrated slide in the module.

    Also sets ``slide.audio_path`` so downstream compose tasks know what
    audio file to depend on.
    """
    tasks: list[dict[str, Any]] = []

    for slide in ctx.slides:
        if not slide.has_narration:
            continue

        slide_id = f"{ctx.module_name}_slide_{slide.index:03d}"
        parts = slide.narration_parts_processed

        if len(parts) > 1:
            # Multi-part: per-part TTS tasks + a concat task.
            part_audio_paths: list[Path] = []
            for j, part_text in enumerate(parts):
                cached_part = _audio_path(
                    audio_cache_dir, part_text, tts.name(), tts.cache_key(), slide.voice
                )
                part_audio_paths.append(cached_part)
                utterance_path = ctx.utterances_dir / f"slide_{slide.index:03d}_part_{j:03d}.txt"
                tasks.append(
                    {
                        "name": f"tts:{slide_id}_part_{j:03d}",
                        "actions": [
                            (
                                action_tts,
                                [part_text, cached_part, tts, utterance_path, slide.voice],
                            )
                        ],
                        "targets": [str(cached_part)],
                        "uptodate": [_audio_cache_valid],
                        "verbosity": 2,
                    }
                )

            # Concat output is content-addressed by the hash of all part paths.
            concat_audio = audio_cache_dir / _concat_filename(part_audio_paths)
            slide.audio_path = concat_audio

            tasks.append(
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
            # Single part (or none): one TTS task keyed on the processed text.
            cached_audio = _audio_path(
                audio_cache_dir,
                slide.narration_processed,
                tts.name(),
                tts.cache_key(),
                slide.voice,
            )
            slide.audio_path = cached_audio
            utterance_path = ctx.utterances_dir / f"slide_{slide.index:03d}.txt"
            tasks.append(
                {
                    "name": f"tts:{slide_id}",
                    "actions": [
                        (
                            action_tts,
                            [
                                slide.narration_processed,
                                cached_audio,
                                tts,
                                utterance_path,
                                slide.voice,
                            ],
                        )
                    ],
                    "targets": [str(cached_audio)],
                    "uptodate": [_audio_cache_valid],
                    "verbosity": 2,
                }
            )

    return tasks


def _build_compose_tasks(
    ctx: _ModuleContext,
    config: ProjectConfig,
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Build per-slide compose tasks. Returns (tasks, segment_paths)."""
    tasks: list[dict[str, Any]] = []
    segment_paths: list[Path] = []

    video_uptodate_fields = {
        "visual_hash": ctx.visual_hash,
        "resolution": config.video.resolution,
        "fps": config.video.fps,
        "crf": config.video.crf,
        "preset": config.video.preset,
    }

    for slide in ctx.slides:
        if slide.is_skip:
            continue

        slide_id = f"{ctx.module_name}_slide_{slide.index:03d}"
        seg_path = ctx.segments_dir / f"seg_{slide.index:03d}.mp4"
        segment_paths.append(seg_path)

        task_deps = [f"extract_images:{ctx.module_name}"]
        file_deps = [str(ctx.manifest_path)]

        if slide.has_narration and slide.audio_path:
            # Multi-part depends on concat_audio; single-part depends on tts.
            if len(slide.narration_parts_processed) > 1:
                task_deps.append(f"concat_audio:{slide_id}")
            else:
                task_deps.append(f"tts:{slide_id}")
            file_deps.append(str(slide.audio_path))

            tasks.append(
                {
                    "name": f"compose:{slide_id}",
                    "actions": [
                        (
                            action_compose_narrated,
                            [
                                ctx.manifest_path,
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
                                **video_uptodate_fields,
                                "pad_seconds": config.video.pad_seconds,
                                "pre_silence": config.video.pre_silence,
                            }
                        )
                    ],
                    "verbosity": 2,
                }
            )
        else:
            tasks.append(
                {
                    "name": f"compose:{slide_id}",
                    "actions": [
                        (
                            action_compose_silent,
                            [
                                ctx.manifest_path,
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
                                **video_uptodate_fields,
                                "silence_duration": config.video.silence_duration,
                                "silence_override": slide.silence_override,
                            }
                        )
                    ],
                    "verbosity": 2,
                }
            )

    return tasks, segment_paths


def _build_assemble_task(
    segments: list[Path],
    output_path: Path,
    config: ProjectConfig,
) -> dict[str, Any]:
    """Build the final-assembly task that merges all segments into output.mp4."""
    return {
        "name": "assemble",
        "actions": [(action_assemble, [segments, output_path, config])],
        "file_dep": [str(p) for p in segments],
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


def _build_assemble_pdf_task(
    module_pdfs: list[Path],
    pdf_output_path: Path,
    export_pdf_task_names: list[str],
) -> dict[str, Any]:
    """Build the task that concatenates per-module PDFs into a single output PDF."""
    return {
        "name": "assemble_pdf",
        "actions": [(action_concat_pdfs, [module_pdfs, pdf_output_path])],
        "file_dep": [str(p) for p in module_pdfs],
        "task_dep": export_pdf_task_names,
        "targets": [str(pdf_output_path)],
        "verbosity": 2,
    }


def generate_tasks(
    entries: list[PlaylistEntry],
    config: ProjectConfig,
    tts: TTSEngine,
    build_dir: Path,
    playlist_dir: Path,
    output_path: Path,
    pdf_output_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Generate doit task dicts for the full build pipeline.

    Each dict is suitable for doit.task.dict_to_task(). Task names use
    the "group:subtask" format for subtasks.
    """
    audio_cache_dir = build_dir / "audio"
    all_segments: list[Path] = []
    all_tasks: list[dict[str, Any]] = []
    all_module_pdfs: list[Path] = []

    for i, entry in enumerate(entries, start=1):
        if entry.module_type == ModuleType.VIDEO:
            all_segments.append(playlist_dir / entry.path)
            continue

        ctx = _build_module_context(i, entry, build_dir, playlist_dir, config)
        all_tasks.extend(_build_slides_tasks(ctx, entry))
        all_tasks.extend(_build_tts_tasks(ctx, tts, audio_cache_dir))
        compose_tasks, segment_paths = _build_compose_tasks(ctx, config)
        all_tasks.extend(compose_tasks)
        all_segments.extend(segment_paths)
        all_module_pdfs.append(ctx.module_pdf_path)

    all_tasks.append(_build_assemble_task(all_segments, output_path, config))

    if all_module_pdfs and pdf_output_path is not None:
        export_pdf_task_names = [
            t["name"] for t in all_tasks if t["name"].startswith("export_pdf:")
        ]
        all_tasks.append(
            _build_assemble_pdf_task(all_module_pdfs, pdf_output_path, export_pdf_task_names)
        )

    return all_tasks
