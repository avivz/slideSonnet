---
paths:
  - "src/**/*.py"
---

# Architecture

## Pipeline Data Flow

```
Playlist (.yaml)
  → parse_playlist() → PlaylistEntry[] + config dict
  → load_config() → ProjectConfig
  → Per module: SlideParser.parse() → SlideNarration[]
  → apply_pronunciation() on narration text
  → generate_tasks() → doit task graph
  → _run_doit(): extract_images → tts → compose → concat → assemble
  → cache/output.mp4
  → subtitles → output.srt
```

## Key Modules

- **cli.py** — Click CLI entry point (build, preview, preview-slide, init, clean, doctor, list, utterances, subtitles, pdf)
- **pipeline.py** — Build orchestrator; `_prepare()` shared setup, `build()` runs doit, `dry_run()` reports cache status without executing
- **tasks.py** — doit task generation for incremental builds
- **hashing.py** — Audio filename computation (text_hash, config_hash, parse_audio_filename)
- **clean.py** — Selective cache cleanup with graduated `--keep` levels
- **doctor.py** — Dependency checker; verifies external tools (ffmpeg, marp, pdflatex, etc.) and Python packages
- **models.py** — Dataclasses: SlideAnnotation, SlideNarration, PlaylistEntry, ProjectConfig, TTSConfig, VideoConfig, VoiceConfig
- **config.py** — Loads ProjectConfig from playlist YAML
- **playlist.py** — Parses playlist YAML into PlaylistEntry list
- **preview.py** — Single-slide audio preview (preview-slide command)
- **parsers/base.py** — Abstract base class for slide parsers
- **parsers/marp.py** — Regex-based MARP parser; uses marp-cli + Playwright for image extraction
- **parsers/beamer.py** — Regex-based Beamer parser; uses pdflatex + pdftoppm; handles nested braces manually
- **parsers/expansion.py** — Fragment expansion: splits multi-say slides into sub-slides
- **tts/base.py** — Abstract base class for TTS backends
- **tts/piper.py** — Subprocess calls to `piper` CLI, outputs WAV
- **tts/elevenlabs.py** — Uses ElevenLabs SDK, outputs MP3
- **tts/pronunciation.py** — Loads `**word**: replacement` dictionaries, applies substitutions before TTS
- **subtitles.py** — SRT subtitle generation from narration text and cached audio durations
- **video/composer.py** — FFmpeg subprocess calls: compose_segment, compose_silent_segment, concatenate_segments, get_duration

## Build System (doit)

The pipeline programmatically generates doit task graphs (not a `dodo.py` file). Task hierarchy per module:
1. `compile_beamer:{module}` — Compile Beamer LaTeX to PDF (Beamer only)
2. `extract_images:{module}` — Parse slides → PNGs (marp-cli + Playwright for MARP, pdftoppm for Beamer)
3. `export_pdf:{module}` — Export presentation to PDF
4. `tts:{slide_id}` — Synthesize audio (content-hash cached; voice is part of hash)
5. `concat_audio:{slide_id}` — Concatenate multi-part audio (for slides with multiple narration parts)
6. `compose:{slide_id}` — Image + audio → MP4 segment
7. `assemble` — Merge segments into final output video

State tracked in `cache/.doit.db` (SQLite3 format).

## Playlist Modules

Playlists support three module types distinguished by file extension:
- `.md` → MARP Markdown slides
- `.tex` → Beamer LaTeX slides
- `.mp4` / `.mkv` / `.webm` / `.mov` → Video passthrough (no parsing/TTS)
