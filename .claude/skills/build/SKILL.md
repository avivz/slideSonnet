---
name: build
description: Build slideSonnet presentations into narrated MP4 videos. Use when the user asks to "build", "compile", "render", "preview", "clean", or "doctor" a lecture or presentation, or wants to check build status, export PDFs, check dependencies, or review utterances.
argument-hint: [playlist path or command]
---

# slideSonnet Build Skill

Build, preview, clean, and inspect slideSonnet presentations.

## Commands Reference

### `slidesonnet build` — compile playlist to MP4

```bash
slidesonnet build [PLAYLIST] [OPTIONS]
```

| Flag | Effect |
|------|--------|
| `--tts piper` | Use local Piper TTS (free) |
| `--tts elevenlabs` | Use ElevenLabs cloud TTS (costs money!) |
| `-n, --dry-run` | Report cache status without building |
| `--preview` | Fast low-res build (1/4 resolution, half FPS, ultrafast preset) |
| `--no-srt` | Skip SRT subtitle generation |
| `--until slides` | Extract images only (no TTS or video) |
| `--until tts` | Generate audio only (no video composition) |
| `--until segments` | Compose segments only (no final assembly) |

Output goes to `{playlist_dir}/{dir_name}.mp4` (or custom with `--output`; `_preview.mp4` with `--preview`).

### `slidesonnet preview` — quick preview with Piper

```bash
slidesonnet preview [PLAYLIST] [--until STAGE]
```

Shortcut for `slidesonnet build --tts piper --preview`. Always free, always fast. Supports `--no-srt` to skip subtitle generation.

### `slidesonnet preview-slide` — listen to one slide's narration

```bash
slidesonnet preview-slide SLIDES SLIDE_NUMBER [-p PLAYLIST]
```

Synthesizes and plays audio for a single slide (1-based index). Uses Piper TTS. Pass `-p PLAYLIST` to apply pronunciation rules and voice settings.

### `slidesonnet pdf` — export PDFs

```bash
slidesonnet pdf [PLAYLIST]
```

Exports all slide modules to PDF (pdflatex for Beamer, marp --pdf for MARP). Skips video passthrough modules.

### `slidesonnet list` — list slides with cache status

```bash
slidesonnet list [PLAYLIST] [--tts BACKEND]
```

Prints a table of all slides showing slide number, source file, voice preset, character count, and narration text (after pronunciation substitutions). Each narrated slide is prefixed with a cache symbol: `●` = cached, `○` = needs TTS. A summary line shows totals. Useful for per-slide cache visibility and discovering slide numbers before using preview-slide.

### `slidesonnet subtitles` — generate SRT subtitles

```bash
slidesonnet subtitles [PLAYLIST] [-o OUTPUT] [--tts BACKEND]
```

Generates an SRT subtitle file from cached audio durations and narration text. Requires a prior build (audio files must exist in cache). Output defaults to `{playlist_stem}.srt` alongside the playlist.

### `slidesonnet utterances` — export narration text

```bash
slidesonnet utterances [PLAYLIST] [-o OUTPUT] [--tts BACKEND]
```

Exports all narration text (after pronunciation substitutions) for proofreading. Output defaults to stdout. Use `-o FILE` to write to a file. Useful for reviewing what TTS will actually say before building.

### `slidesonnet clean` — remove cached artifacts

```bash
slidesonnet clean [PLAYLIST] [--keep LEVEL]
```

| Level | Keeps | Removes |
|-------|-------|---------|
| `api` (default) | All cloud TTS audio | Piper audio, images, segments, build state |
| `current` | Audio matching current slide text (any engine) | Orphaned audio, build artifacts |
| `exact` | Audio matching current text + current backend + voice | Everything else |
| `nothing` | Nothing | Entire cache directory |

All levels remove: slide images, video segments, `.doit.db`, concat audio.

### `slidesonnet doctor` — check dependencies

```bash
slidesonnet doctor
```

Verifies that all external tools and Python packages are installed. Reports version info for each, grouped by category:

- **Core** (ffmpeg, ffprobe) — always required, affects exit code
- **MARP toolchain** (marp-cli) — needed for `.md` slides
- **Beamer toolchain** (pdflatex, pdftoppm) — needed for `.tex` slides
- **TTS backends** (piper, elevenlabs) — at least one required
- **API keys** (ELEVENLABS_API_KEY) — only for elevenlabs TTS

Exit code 0 if all core dependencies are found, 1 if any are missing. Optional tools are reported but don't affect the exit code.

### `slidesonnet init` — scaffold a new project

```bash
slidesonnet init FMT [TARGET]
```

Creates a new project directory with a playlist, sample slides, pronunciation files, `.gitignore`, and `.env`. FMT is `md` (MARP) or `tex` (Beamer). TARGET defaults to the current directory.

## Common Workflows

**Full build with Piper (free):**
```bash
slidesonnet build --tts piper
```

**Quick preview iteration:**
```bash
slidesonnet preview
```

**Check what needs rebuilding:**
```bash
slidesonnet build -n                     # aggregate summary
slidesonnet list                         # per-slide cache detail
```

**Rebuild from scratch:**
```bash
slidesonnet clean && slidesonnet build --tts piper
```

**Test just the TTS without composing video:**
```bash
slidesonnet build --tts piper --until tts
```

**Listen to a specific slide's narration:**
```bash
slidesonnet preview-slide slides.md 3 -p slidesonnet.yaml
```

**Regenerate subtitles from cache (e.g. after editing SRT):**
```bash
slidesonnet subtitles
slidesonnet subtitles -o lecture_en.srt
```

**Build without subtitles:**
```bash
slidesonnet build --tts piper --no-srt
```

## Critical Rules

- **NEVER use `--tts elevenlabs` for testing** — it costs real money. Always use `--tts piper` unless the user explicitly asks for ElevenLabs.
- **Prefer `slidesonnet clean --keep api`** (the default) over `--keep nothing` to preserve expensive cloud audio.
- **Use `--dry-run` first** when unsure about cache state — it shows what would be rebuilt without doing anything.
- **Use `--preview` for iteration** — 4x faster than full-quality builds.

$ARGUMENTS
