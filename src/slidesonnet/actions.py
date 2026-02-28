"""Action functions executed by doit tasks.

These are the actual build steps (image extraction, TTS synthesis,
video composition, concatenation, assembly) that doit invokes.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from slidesonnet.models import ModuleType, ProjectConfig
from slidesonnet.parsers.base import SlideParser
from slidesonnet.tts.base import TTSEngine
from slidesonnet.video import composer

logger = logging.getLogger(__name__)


def action_extract_images(
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


def action_tts(
    text: str,
    output_path: Path,
    tts: TTSEngine,
    utterance_path: Path,
    voice: str | None = None,
) -> None:
    """Synthesize TTS audio.

    Caching is handled by doit's uptodate/targets mechanism;
    force-rebuild is handled by doit's --always-execute flag.
    """
    utterance_path.parent.mkdir(parents=True, exist_ok=True)
    utterance_path.write_text(text, encoding="utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("  slide synthesizing...")
    tts.synthesize(text, output_path, voice=voice)


def action_concat_audio(audio_paths: list[Path], output_path: Path) -> None:
    """Concatenate multiple audio files into a single file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    composer.concatenate_audio(audio_paths, output_path)


def action_compose_narrated(
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
    logger.debug("slide %d: audio=%.3fs image=%s", slide_index, duration, image.name)
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


def action_compose_silent(
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


def action_assemble(segments: list[Path], output: Path, config: ProjectConfig) -> None:
    """Assemble all segments into final output."""
    if not segments:
        raise RuntimeError("No segments to assemble — the playlist may be empty.")
    _merge_videos(segments, output, config)


def _merge_videos(inputs: list[Path], output: Path, config: ProjectConfig) -> None:
    """Merge one or more video files into a single output."""
    if len(inputs) == 1:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inputs[0], output)
    else:
        if config.video.crossfade > 0:
            composer.concatenate_segments_xfade(
                inputs,
                output,
                crossfade=config.video.crossfade,
                crf=config.video.crf,
            )
        else:
            composer.concatenate_segments(inputs, output)


def action_compile_beamer(
    source: Path,
    slides_dir: Path,
    pdf_path: Path,
) -> None:
    """Compile Beamer source to PDF."""
    from slidesonnet.parsers.beamer import compile_pdf

    compile_pdf(source, slides_dir)
    if not pdf_path.exists():
        raise RuntimeError(f"Expected PDF not produced: {pdf_path}")


def action_extract_images_beamer(
    pdf_path: Path,
    slides_dir: Path,
    manifest_path: Path,
) -> None:
    """Extract images from a compiled Beamer PDF."""
    from slidesonnet.parsers.beamer import extract_images_from_pdf

    images = extract_images_from_pdf(pdf_path, slides_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps([str(p) for p in images]),
        encoding="utf-8",
    )


def action_export_pdf_marp(
    source: Path,
    output_path: Path,
) -> None:
    """Export a MARP presentation to PDF."""
    from slidesonnet.parsers.marp import export_pdf

    export_pdf(source, output_path)


def action_export_pdf_beamer(
    cache_pdf: Path,
    output_path: Path,
) -> None:
    """Copy compiled Beamer PDF to the output directory."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cache_pdf, output_path)


def get_parser_and_extractor(
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
