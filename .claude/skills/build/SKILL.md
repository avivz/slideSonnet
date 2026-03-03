---
name: build
description: Build slideSonnet presentations into narrated MP4 videos. Use when the user asks to "build", "compile", "render", "preview", or "clean" a lecture or presentation, or wants to check build status, export PDFs, or review utterances.
argument-hint: [playlist path or command]
---

# slideSonnet Build Skill

Build, preview, clean, and inspect slideSonnet presentations.

## Commands Reference

### `slidesonnet build` — compile playlist to MP4

```bash
slidesonnet build PLAYLIST [OPTIONS]
```

| Flag | Effect |
|------|--------|
| `--tts piper` | Use local Piper TTS (free) |
| `--tts elevenlabs` | Use ElevenLabs cloud TTS (costs money!) |
| `-n, --dry-run` | Report cache status without building |
| `--preview` | Fast low-res build (1/4 resolution, half FPS, ultrafast preset) |
| `--until slides` | Extract images only (no TTS or video) |
| `--until tts` | Generate audio only (no video composition) |
| `--until segments` | Compose segments only (no final assembly) |

Output goes to `{playlist_dir}/{playlist_stem}.mp4` (or `_preview.mp4` with `--preview`).

### `slidesonnet preview` — quick preview with Piper

```bash
slidesonnet preview PLAYLIST [--until STAGE]
```

Shortcut for `slidesonnet build PLAYLIST --tts piper --preview`. Always free, always fast.

### `slidesonnet preview-slide` — listen to one slide's narration

```bash
slidesonnet preview-slide SLIDES SLIDE_NUMBER [-p PLAYLIST]
```

Synthesizes and plays audio for a single slide (1-based index). Uses Piper TTS. Pass `-p PLAYLIST` to apply pronunciation rules and voice settings.

### `slidesonnet pdf` — export PDFs

```bash
slidesonnet pdf PLAYLIST
```

Exports all slide modules to PDF (pdflatex for Beamer, marp --pdf for MARP). Skips video passthrough modules.

### `slidesonnet list` — list slides with narration

```bash
slidesonnet list PLAYLIST [--tts BACKEND]
```

Prints a table of all slides showing slide number, source file, voice preset, and narration text (after pronunciation substitutions). Useful for discovering slide numbers before using preview-slide.

### `slidesonnet clean` — remove cached artifacts

```bash
slidesonnet clean PLAYLIST [--keep LEVEL]
```

| Level | Keeps | Removes |
|-------|-------|---------|
| `api` (default) | All cloud TTS audio | Piper audio, images, segments, build state |
| `current` | Audio matching current slide text (any engine) | Orphaned audio, build artifacts |
| `exact` | Audio matching current text + current backend + voice | Everything else |
| `nothing` | Nothing | Entire cache directory |

All levels remove: slide images, video segments, `.doit.db`, concat audio.

## Common Workflows

**Full build with Piper (free):**
```bash
slidesonnet build lecture.yaml --tts piper
```

**Quick preview iteration:**
```bash
slidesonnet preview lecture.yaml
```

**Check what needs rebuilding:**
```bash
slidesonnet build lecture.yaml -n
```

**Rebuild from scratch:**
```bash
slidesonnet clean lecture.yaml && slidesonnet build lecture.yaml --tts piper
```

**Test just the TTS without composing video:**
```bash
slidesonnet build lecture.yaml --tts piper --until tts
```

**Listen to a specific slide's narration:**
```bash
slidesonnet preview-slide slides.md 3 -p lecture.yaml
```

## Critical Rules

- **NEVER use `--tts elevenlabs` for testing** — it costs real money. Always use `--tts piper` unless the user explicitly asks for ElevenLabs.
- **Prefer `slidesonnet clean --keep api`** (the default) over `--keep nothing` to preserve expensive cloud audio.
- **Use `--dry-run` first** when unsure about cache state — it shows what would be rebuilt without doing anything.
- **Use `--preview` for iteration** — 4x faster than full-quality builds.

$ARGUMENTS
