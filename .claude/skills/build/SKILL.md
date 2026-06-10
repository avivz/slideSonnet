---
name: build
description: Run the slideSonnet CLI — scaffold, check, synthesize, export, and preview narrated videos from a PDF + narration sidecar. Use when the user asks to "render", "export", "build", "check", "synthesize", "preview", "clean", or "doctor" a slideSonnet deck.
argument-hint: [deck.pdf or command]
---

# slideSonnet CLI Skill

slideSonnet renders a finished **PDF** (with invisible `\ssid` slide-ids) plus a
plain-text **`<deck>.narration`** sidecar into a narrated MP4 with subtitles.
There is no playlist, no `build` command, no MARP — you bring the PDF.

## Command reference

### `slidesonnet sty` — write the LaTeX macro

```bash
slidesonnet sty [-o PATH]      # default: ./slidesonnet.sty
```

Drops `slidesonnet.sty` next to your Beamer source. `\usepackage{slidesonnet}`
and mark pages with `\ssid<step>{id}` / `\ssid{id}`, then compile (`latexmk -pdf`).

### `slidesonnet init` — scaffold the narration sidecar

```bash
slidesonnet init deck.pdf [--narration PATH] [--merge] [--force]
```

Reads the slide-ids from the PDF and writes a blank `deck.narration` (one `@id`
block per page). `--merge` appends blocks for ids missing from an existing
sidecar (safe to re-run after the deck drifts); `--force` overwrites.

### `slidesonnet check` — reconcile ids

```bash
slidesonnet check deck.pdf [--narration PATH]
```

Reports duplicate / `auto-…` / missing / orphan / order issues. **Exits non-zero
on errors** — use it in an LLM/CI loop after editing slides or narration.

### `slidesonnet tts` — synthesize into the cache

```bash
slidesonnet tts deck.pdf [--engine piper|elevenlabs] [--id ID ...]
```

Synthesizes narration into the content-addressed cache (only missing/changed
clips). `--id` restricts to specific slides. Cache lives in `<deck-dir>/.slidesonnet/`.

### `slidesonnet export` — render the video

```bash
slidesonnet export deck.pdf -o OUT.mp4 [OPTIONS]
```

| Flag | Effect |
|------|--------|
| `--engine piper` | Local Piper TTS (free) |
| `--engine elevenlabs` | ElevenLabs cloud TTS (**costs money!**) |
| `--silent` | No TTS: silent video; timing from the model below |
| `--timing tts` | Real synthesized audio (default) |
| `--timing estimate [--wpm N]` | Approximate from word count — fast rough cut, no TTS |
| `--timing fixed:N` | Hold every page N seconds |
| `--subtitles srt\|vtt\|both\|none` | Subtitle files beside the video (default srt) |
| `--sub-granularity segment\|slide` | One cue per speech segment (default) or per slide |

### `slidesonnet subs` — subtitles without rendering video

```bash
slidesonnet subs deck.pdf -o OUT.srt [--format srt|vtt] [--sub-granularity ...] [--timing ...]
```

Uses cached audio durations where available, else the timing model. Never triggers TTS.

### `slidesonnet edit` — launch the GUI editor

```bash
slidesonnet edit deck.pdf [--narration PATH] [--host H] [--port P] [--no-browser]
```

Local NiceGUI app: page nav, narration editing, per-slide TTS, whole-deck preview
(silence-respecting), diagnostics panel.

### `slidesonnet clean` — prune the cache

```bash
slidesonnet clean deck.pdf [--keep nothing|api|current|exact] [-y]
```

| Level | Keeps | Removes |
|-------|-------|---------|
| `api` (default) | All cloud (ElevenLabs) audio | Piper audio + renders |
| `current` | Audio matching current sidecar text (any engine) | Orphans + renders |
| `exact` | Audio matching current text + active engine config | Everything else |
| `nothing` | Nothing | The entire `.slidesonnet/` cache |

### `slidesonnet doctor` — check dependencies

```bash
slidesonnet doctor
```

Checks ffmpeg/ffprobe/pdftoppm/PyMuPDF (core), NiceGUI, latexmk/pdflatex (to
compile your deck), piper/elevenlabs, and `ELEVENLABS_API_KEY`. Exit 1 if a core
dependency is missing.

## Common workflows

**From a marked Beamer source to a video:**
```bash
slidesonnet sty                              # drop the macro
latexmk -pdf deck.tex                         # compile (your job)
slidesonnet init  deck.pdf                    # scaffold narration
# ...write deck.narration...
slidesonnet check deck.pdf                     # reconcile ids
slidesonnet export deck.pdf -o deck.mp4 --engine piper
```

**Fast visual rough cut (no TTS):**
```bash
slidesonnet export deck.pdf -o deck.mp4 --silent
```

**Iterate on one slide's narration:**
```bash
slidesonnet tts deck.pdf --id euler-setup --engine piper
slidesonnet edit deck.pdf            # or preview the whole deck in the GUI
```

**Rebuild audio from scratch:**
```bash
slidesonnet clean deck.pdf --keep nothing -y && slidesonnet export deck.pdf -o deck.mp4 --engine piper
```

Every command is also a typed function in `slidesonnet.api` (`init_sidecar`,
`check_deck`, `synthesize_deck`, `export`, `write_subs`, `build_preview`).

## Critical rules

- **NEVER use `--engine elevenlabs` for testing** — it costs real money. Use
  `--engine piper` unless the user explicitly asks for ElevenLabs.
- **Prefer `slidesonnet clean --keep api`** (default) over `--keep nothing` to
  preserve paid cloud audio.
- **`slidesonnet check` before rendering** — it catches duplicate/orphan ids that
  would otherwise misbind narration.
- **Example videos are hosted on GitHub Releases** (`v0.0.0`), not in the repo.
  After rebuilding, upload with `gh release upload v0.0.0 path/to/video.mp4 --clobber`.

$ARGUMENTS
