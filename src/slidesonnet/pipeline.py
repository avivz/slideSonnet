"""Build pipeline: orchestrates doit-based incremental builds."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

from slidesonnet.config import load_config
from slidesonnet.models import ProjectConfig
from slidesonnet.playlist import parse_playlist
from slidesonnet.tasks import generate_tasks
from slidesonnet.tts.base import TTSEngine
from slidesonnet.tts.pronunciation import load_pronunciation_files


def build(playlist_path: Path, tts_override: Literal["piper", "elevenlabs"] | None = None, force: bool = False) -> Path:
    """Execute the full build pipeline for a playlist.

    Returns path to the final output video.
    """
    playlist_path = playlist_path.resolve()
    playlist_dir = playlist_path.parent
    build_dir = playlist_dir / ".build"
    build_dir.mkdir(parents=True, exist_ok=True)

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
    tts = _create_tts(config)

    # Ensure audio cache dir exists
    audio_cache_dir = build_dir / "audio"
    audio_cache_dir.mkdir(parents=True, exist_ok=True)

    # Output path
    output_path = build_dir / (playlist_path.stem + ".mp4")

    # Generate doit tasks
    task_list = generate_tasks(
        entries=entries,
        config=config,
        tts=tts,
        build_dir=build_dir,
        playlist_dir=playlist_dir,
        output_path=output_path,
    )

    # Run doit
    _run_doit(task_list, build_dir, force)

    print(f"Done: {output_path}")
    return output_path


def _run_doit(task_list: list[dict[str, Any]], build_dir: Path, force: bool) -> None:
    """Run doit programmatically with the given tasks."""
    from doit.cmd_base import TaskLoader2
    from doit.doit_cmd import DoitMain
    from doit.task import dict_to_task

    db_file = str(build_dir / ".doit.db")
    tasks = [dict_to_task(t) for t in task_list]

    class _Loader(TaskLoader2):  # type: ignore[misc]
        def load_doit_config(self) -> dict[str, Any]:
            return {
                "backend": "json",
                "dep_file": db_file,
                "verbosity": 2,
            }

        def load_tasks(self, cmd: Any, pos_args: Any) -> list[Any]:
            return tasks

    run_args = ["run"]
    if force:
        run_args.append("--always-execute")

    result = DoitMain(_Loader()).run(run_args)
    if result not in (0, None):
        raise SystemExit(result)


def _create_tts(config: ProjectConfig) -> TTSEngine:
    """Create TTS engine from config."""
    from slidesonnet.tts.piper import PiperTTS

    if config.tts.backend == "piper":
        return PiperTTS(model=config.tts.piper_model)
    elif config.tts.backend == "elevenlabs":
        from slidesonnet.tts.elevenlabs import ElevenLabsTTS

        return ElevenLabsTTS(config.tts)
    else:
        raise ValueError(f"Unknown TTS backend: {config.tts.backend}")
