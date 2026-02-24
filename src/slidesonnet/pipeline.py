"""Build pipeline: orchestrates parsing, TTS, composition, and assembly."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from slidesonnet.config import load_config
from slidesonnet.models import (
    ModuleType,
    PlaylistEntry,
    ProjectConfig,
    SlideAnnotation,
    SlideNarration,
)
from slidesonnet.parsers.marp import MarpParser
from slidesonnet.parsers.marp import extract_images as marp_extract_images
from slidesonnet.playlist import parse_playlist
from slidesonnet.tts.base import TTSEngine
from slidesonnet.tts.piper import PiperTTS
from slidesonnet.tts.pronunciation import apply_pronunciation, load_pronunciation_files
from slidesonnet.video import composer


def build(playlist_path: Path, tts_override: str | None = None, force: bool = False) -> Path:
    """Execute the full build pipeline for a playlist.

    Returns path to the final output video.
    """
    playlist_path = playlist_path.resolve()
    playlist_dir = playlist_path.parent
    build_dir = playlist_dir / ".build"
    build_dir.mkdir(parents=True, exist_ok=True)

    # Parse playlist
    raw_config, entries = parse_playlist(playlist_path)
    config = load_config(raw_config, playlist_dir)

    # Override TTS backend if requested
    if tts_override:
        config.tts.backend = tts_override

    # Load pronunciation
    config.pronunciation = load_pronunciation_files(config.pronunciation_files)

    # Create TTS engine
    tts = _create_tts(config)

    # Audio cache directory (content-addressed)
    audio_cache_dir = build_dir / "audio"
    audio_cache_dir.mkdir(parents=True, exist_ok=True)

    # Build each module
    module_videos: list[Path] = []
    for i, entry in enumerate(entries, start=1):
        module_video = _build_module(
            entry=entry,
            index=i,
            config=config,
            tts=tts,
            build_dir=build_dir,
            playlist_dir=playlist_dir,
            audio_cache_dir=audio_cache_dir,
            force=force,
        )
        module_videos.append(module_video)

    # Final assembly
    output_name = playlist_path.stem + ".mp4"
    output_path = build_dir / output_name
    if len(module_videos) == 1:
        shutil.copy2(module_videos[0], output_path)
    else:
        composer.concatenate_segments(module_videos, output_path)

    print(f"Done: {output_path}")
    return output_path


def _build_module(
    entry: PlaylistEntry,
    index: int,
    config: ProjectConfig,
    tts: TTSEngine,
    build_dir: Path,
    playlist_dir: Path,
    audio_cache_dir: Path,
    force: bool,
) -> Path:
    """Build a single module and return path to its video."""
    source_path = playlist_dir / entry.path
    module_dir = build_dir / entry.path.parent / entry.path.stem

    if entry.module_type == ModuleType.VIDEO:
        return _build_video_module(source_path, module_dir)

    if entry.module_type == ModuleType.MARP:
        return _build_slides_module(
            source_path, module_dir, config, tts, audio_cache_dir, force,
            parser_cls=MarpParser, extract_fn=marp_extract_images,
        )

    if entry.module_type == ModuleType.BEAMER:
        from slidesonnet.parsers.beamer import BeamerParser
        from slidesonnet.parsers.beamer import extract_images as beamer_extract_images

        return _build_slides_module(
            source_path, module_dir, config, tts, audio_cache_dir, force,
            parser_cls=BeamerParser, extract_fn=beamer_extract_images,
        )

    raise ValueError(f"Unsupported module type: {entry.module_type}")


def _build_video_module(source_path: Path, module_dir: Path) -> Path:
    """Passthrough: copy/link pre-existing video."""
    module_dir.mkdir(parents=True, exist_ok=True)
    output = module_dir / "module.mp4"
    shutil.copy2(source_path, output)
    return output


def _build_slides_module(
    source_path: Path,
    module_dir: Path,
    config: ProjectConfig,
    tts: TTSEngine,
    audio_cache_dir: Path,
    force: bool,
    parser_cls: type,
    extract_fn: callable,
) -> Path:
    """Build a slide module (MARP or Beamer): parse → TTS → compose → concat."""
    module_dir.mkdir(parents=True, exist_ok=True)
    slides_dir = module_dir / "slides"
    utterances_dir = module_dir / "utterances"
    segments_dir = module_dir / "segments"
    slides_dir.mkdir(parents=True, exist_ok=True)
    utterances_dir.mkdir(parents=True, exist_ok=True)
    segments_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: Parse
    parser = parser_cls()
    slides = parser.parse(source_path, slides_dir)

    # Extract images
    images = extract_fn(source_path, slides_dir)

    # Assign images to slides
    for slide, img_path in zip(slides, images):
        slide.image_path = img_path

    # Stage 2: Preprocess narration
    for slide in slides:
        if slide.has_narration:
            slide.narration_processed = apply_pronunciation(
                slide.narration_raw, config.pronunciation
            )

    # Stage 3: TTS synthesis (content-addressed cache)
    for slide in slides:
        if slide.has_narration:
            _synthesize_slide(slide, tts, audio_cache_dir, utterances_dir, force)

    # Stage 4: Compose segments
    segments: list[Path] = []
    for slide in slides:
        if slide.is_skip:
            continue

        seg_path = segments_dir / f"seg_{slide.index:03d}.mp4"

        if slide.has_narration and slide.audio_path:
            composer.compose_segment(
                image=slide.image_path,
                audio=slide.audio_path,
                output=seg_path,
                duration=slide.duration_seconds,
                pad_seconds=config.video.pad_seconds,
                resolution=config.video.resolution,
                fps=config.video.fps,
                crf=config.video.crf,
            )
        elif slide.image_path:
            composer.compose_silent_segment(
                image=slide.image_path,
                output=seg_path,
                duration=config.video.silence_duration,
                resolution=config.video.resolution,
                fps=config.video.fps,
                crf=config.video.crf,
            )
        else:
            continue

        segments.append(seg_path)

    # Stage 5: Module concat
    module_output = module_dir / "module.mp4"
    if len(segments) == 1:
        shutil.copy2(segments[0], module_output)
    elif segments:
        composer.concatenate_segments(segments, module_output)

    return module_output


def _synthesize_slide(
    slide: SlideNarration,
    tts: TTSEngine,
    audio_cache_dir: Path,
    utterances_dir: Path,
    force: bool,
) -> None:
    """Synthesize TTS for a slide, using content-addressed cache."""
    text = slide.narration_processed
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    cached_audio = audio_cache_dir / f"{text_hash}.wav"

    # Save utterance text for debugging
    utterance_file = utterances_dir / f"slide_{slide.index:03d}.txt"
    utterance_file.write_text(text, encoding="utf-8")

    if cached_audio.exists() and not force:
        slide.audio_path = cached_audio
        slide.duration_seconds = composer.get_duration(cached_audio)
        print(f"  slide {slide.index} [cached]")
        return

    print(f"  slide {slide.index} synthesizing...")
    slide.duration_seconds = tts.synthesize(text, cached_audio)
    slide.audio_path = cached_audio


def _create_tts(config: ProjectConfig) -> TTSEngine:
    """Create TTS engine from config."""
    if config.tts.backend == "piper":
        return PiperTTS(model=config.tts.piper_model)
    elif config.tts.backend == "elevenlabs":
        # Lazy import to avoid requiring elevenlabs for piper-only use
        from slidesonnet.tts.elevenlabs import ElevenLabsTTS

        return ElevenLabsTTS(config.tts)
    else:
        raise ValueError(f"Unknown TTS backend: {config.tts.backend}")
