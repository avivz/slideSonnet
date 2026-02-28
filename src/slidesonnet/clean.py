"""Selective cache cleanup with graduated preservation levels.

Four --keep levels, each progressively more aggressive:
  nothing    — nuke entire cache directory
  api        — keep all API-generated audio, remove build artifacts + piper audio
  utterances — keep audio for current utterances (any engine), remove orphans
  exact      — keep only audio matching current text + current TTS config
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Literal

from slidesonnet.actions import get_parser_and_extractor
from slidesonnet.config import load_config
from slidesonnet.hashing import audio_filename, parse_audio_filename, text_hash
from slidesonnet.models import ModuleType
from slidesonnet.playlist import parse_playlist
from slidesonnet.tts.pronunciation import apply_pronunciation, load_pronunciation_files

logger = logging.getLogger(__name__)

KeepLevel = Literal["nothing", "api", "utterances", "exact"]

_API_BACKENDS = frozenset({"elevenlabs"})


def clean(playlist_path: Path, keep: KeepLevel = "api") -> None:
    """Clean build artifacts with the given preservation level."""
    build_dir = playlist_path.resolve().parent / "cache"
    if not build_dir.exists():
        return

    if keep == "nothing":
        _clean_all(build_dir)
    elif keep == "api":
        _clean_keep_api(build_dir)
    elif keep == "utterances":
        _clean_keep_utterances(build_dir, playlist_path)
    elif keep == "exact":
        _clean_keep_exact(build_dir, playlist_path)


def _clean_all(build_dir: Path) -> None:
    """Remove the entire cache directory."""
    shutil.rmtree(build_dir)


def _clean_keep_api(build_dir: Path) -> None:
    """Remove build artifacts + piper audio + concat + old-format. Keep API audio."""
    _remove_build_artifacts(build_dir)

    audio_dir = build_dir / "audio"
    if not audio_dir.exists():
        return

    for f in audio_dir.iterdir():
        if not f.is_file():
            continue
        parsed = parse_audio_filename(f.name)
        if parsed is not None:
            _, backend, _ = parsed
            if backend in _API_BACKENDS:
                continue  # keep API audio
        # Remove: piper audio, concat files, old-format files
        f.unlink()

    _remove_empty_dir(audio_dir)


def _clean_keep_utterances(build_dir: Path, playlist_path: Path) -> None:
    """Remove build artifacts + orphaned audio. Keep current-utterance audio (any engine)."""
    _remove_build_artifacts(build_dir)

    audio_dir = build_dir / "audio"
    if not audio_dir.exists():
        return

    current_hashes = _collect_current_text_hashes(playlist_path)

    for f in audio_dir.iterdir():
        if not f.is_file():
            continue
        parsed = parse_audio_filename(f.name)
        if parsed is not None:
            th, _, _ = parsed
            if th in current_hashes:
                continue  # keep: matches a current utterance
        # Remove: orphaned audio, concat files, old-format files
        f.unlink()

    _remove_empty_dir(audio_dir)


def _clean_keep_exact(build_dir: Path, playlist_path: Path) -> None:
    """Remove build artifacts + orphaned + stale-config audio. Keep exact matches only."""
    _remove_build_artifacts(build_dir)

    audio_dir = build_dir / "audio"
    if not audio_dir.exists():
        return

    current_filenames = _collect_current_audio_filenames(playlist_path)

    for f in audio_dir.iterdir():
        if not f.is_file():
            continue
        if f.name in current_filenames:
            continue  # keep: exact match
        f.unlink()

    _remove_empty_dir(audio_dir)


def _remove_build_artifacts(build_dir: Path) -> None:
    """Remove everything in build_dir except the audio/ directory."""
    for child in build_dir.iterdir():
        if child.name == "audio":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            # .doit.db, .doit.db.bak, etc.
            child.unlink()


def _remove_empty_dir(path: Path) -> None:
    """Remove directory if it's empty."""
    try:
        path.rmdir()  # only succeeds if empty
    except OSError:
        pass


def _collect_current_text_hashes(playlist_path: Path) -> set[str]:
    """Parse the playlist and return text_hashes for all current utterances.

    Resolves voice presets across ALL backends so that audio from any engine
    is preserved if its utterance content matches.
    """
    playlist_path = playlist_path.resolve()
    playlist_dir = playlist_path.parent
    build_dir = playlist_dir / "cache"

    raw_config, entries = parse_playlist(playlist_path)
    config = load_config(raw_config, playlist_dir)
    config.pronunciation = load_pronunciation_files(config.pronunciation_files)

    text_hashes: set[str] = set()

    for entry in entries:
        if entry.module_type == ModuleType.VIDEO:
            continue

        source_path = playlist_dir / entry.path
        parser_cls, _ = get_parser_and_extractor(entry.module_type)
        module_dir = build_dir / entry.path.parent / entry.path.stem
        slides_dir = module_dir / "slides"

        parser = parser_cls()
        slides = parser.parse(source_path, slides_dir)

        for slide in slides:
            if not slide.has_narration:
                continue

            slide.narration_processed = apply_pronunciation(
                slide.narration_raw, config.pronunciation
            )
            slide.narration_parts_processed = [
                apply_pronunciation(part, config.pronunciation) for part in slide.narration_parts
            ]

            # Collect all possible voice resolutions across all backends
            voices: set[str | None] = {None}  # always include default (no voice)
            if slide.voice:
                voice_cfg = config.voices.get(slide.voice)
                if voice_cfg:
                    for voice_id in voice_cfg.backend_voices.values():
                        voices.add(voice_id)

            # Compute text_hashes for all parts and all voice resolutions
            parts = slide.narration_parts_processed
            texts = parts if len(parts) > 1 else [slide.narration_processed]
            for utterance_text in texts:
                for voice in voices:
                    text_hashes.add(text_hash(utterance_text, voice))

    return text_hashes


def _collect_current_audio_filenames(playlist_path: Path) -> set[str]:
    """Parse the playlist and return expected audio filenames for the current TTS config.

    Only considers the currently configured backend, unlike _collect_current_text_hashes
    which considers all backends.
    """
    from slidesonnet.pipeline import _create_tts

    playlist_path = playlist_path.resolve()
    playlist_dir = playlist_path.parent
    build_dir = playlist_dir / "cache"

    raw_config, entries = parse_playlist(playlist_path)
    config = load_config(raw_config, playlist_dir)
    config.pronunciation = load_pronunciation_files(config.pronunciation_files)
    tts = _create_tts(config)

    filenames: set[str] = set()

    for entry in entries:
        if entry.module_type == ModuleType.VIDEO:
            continue

        source_path = playlist_dir / entry.path
        parser_cls, _ = get_parser_and_extractor(entry.module_type)
        module_dir = build_dir / entry.path.parent / entry.path.stem
        slides_dir = module_dir / "slides"

        parser = parser_cls()
        slides = parser.parse(source_path, slides_dir)

        for slide in slides:
            if not slide.has_narration:
                continue

            slide.narration_processed = apply_pronunciation(
                slide.narration_raw, config.pronunciation
            )
            slide.narration_parts_processed = [
                apply_pronunciation(part, config.pronunciation) for part in slide.narration_parts
            ]

            # Resolve voice for current backend only
            voice: str | None = None
            if slide.voice:
                voice_cfg = config.voices.get(slide.voice)
                if voice_cfg:
                    voice = voice_cfg.resolve(config.tts.backend)

            parts = slide.narration_parts_processed
            texts = parts if len(parts) > 1 else [slide.narration_processed]
            for utterance_text in texts:
                filenames.add(audio_filename(utterance_text, tts.name(), tts.cache_key(), voice))

    return filenames
