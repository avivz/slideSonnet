# slideSonnet

Compile text-based slide presentations into narrated MP4 videos.

Write your slides in [MARP](https://marp.app/) Markdown or LaTeX Beamer, add narration with `<!-- say: -->` comments, and slideSonnet handles TTS synthesis, video composition, and assembly — with incremental builds that only re-synthesize changed slides.

## How it works

```
lecture.yaml (playlist)
    |
    ├── 01-intro/slides.md   → [parse → TTS → compose] → module_01.mp4
    ├── animations/euler.mp4  → [passthrough]            → module_02.mp4
    ├── 02-proofs/slides.tex  → [parse → TTS → compose] → module_03.mp4
    └── [assemble] ─────────────────────────────────────→ lecture.mp4
```

A **playlist** file chains modules together — MARP slides, Beamer slides, and pre-existing video files. Each module is built independently, then concatenated into the final video. [pydoit](https://pydoit.org/) manages the build graph with content-hash caching, so only changed slides trigger TTS.

## Installation

### External dependencies

Install these system packages first:

| Tool | Required? | What it does | Install |
|---|---|---|---|
| **ffmpeg** | Yes | Video composition and concatenation | `sudo apt install ffmpeg` |
| **marp-cli** | Yes (for MARP slides) | Converts Markdown slides to PNG images | `npm install -g @marp-team/marp-cli` |
| **pdflatex + pdftoppm** | Only for Beamer | Compiles LaTeX and extracts slide images | `sudo apt install texlive-latex-base poppler-utils` |

After installing, run `slidesonnet doctor` to verify everything is set up correctly.

### Install slideSonnet

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv tool install slidesonnet[piper]
```

With [pipx](https://pipx.pypa.io/):

```bash
pipx install slidesonnet[piper]
```

The `[piper]` extra includes [Piper TTS](https://github.com/rhasspy/piper) for free local speech synthesis. Omit it if you plan to use ElevenLabs instead.

## Quick start

```bash
# Create an example project (MARP Markdown)
slidesonnet init md myproject
cd myproject

# Build the video
slidesonnet build lecture.yaml
```

## Showcase example

The `examples/showcase/` directory is a full-featured project that exercises every slideSonnet capability:

| Module | Format | Features demonstrated |
|---|---|---|
| `part1.md` | MARP | Basic say, multiline say, multiple say blocks, nonarration |
| `part2.tex` | Beamer | `\say{}` with LaTeX, voice/pace overrides, `\nonarration`, `\slidesonnetskip` |
| `part3.md` | MARP | Voice presets, pace control, skip, pronunciation triggers |
| `animations/transition.mp4` | Video | Passthrough (no parsing/TTS) |

It also includes two pronunciation dictionaries (`pronunciation/general.md` and `pronunciation/names.md`) and a playlist with all configuration options (`lecture.yaml`).

```bash
cd examples/showcase
slidesonnet build lecture.yaml
```

## Writing slides

### MARP Markdown

Add narration with `<!-- say: -->` HTML comments:

```markdown
---
marp: true
---

# Introduction

<!-- say: Welcome to the lecture. Today we cover graph theory basics. -->

---

# Euler's Theorem

<!-- say(voice=alice): Let me explain this theorem carefully. -->

---

# Diagram

<!-- nonarration -->

---

# Hidden Notes

<!-- skip -->
```

| Annotation | Effect |
|---|---|
| `<!-- say: text -->` | Narrate with default voice |
| `<!-- say(voice=alice): text -->` | Narrate with a named voice preset |
| `<!-- nonarration -->` | Show slide with silence (uses global `silence_duration`) |
| `<!-- nonarration(5) -->` | Show slide with silence for 5 seconds (per-slide override) |
| `<!-- skip -->` | Omit slide from video entirely |
| *(none)* | Treated as silent, emits a warning |

Multi-line narration is supported. Slides with multiple `<!-- say: -->` directives are expanded into animated sub-slides with progressive fragment reveal — see [MARP documentation](docs/marp.md) for details.

### Beamer LaTeX

Use the `\say` command (defined as a no-op by `slidesonnet.sty` so LaTeX compiles normally):

```latex
\usepackage{slidesonnet}

\begin{frame}
  \frametitle{Euler's Theorem}
  \say{The sum of all vertex degrees equals twice the number of edges.}
  \say[voice=alice]{Let me explain more carefully.}
\end{frame}
```

Beamer equivalents: `\say{}`, `\say[voice=alice]{}`, `\nonarration`, `\nonarration[5]` (per-slide duration override), `\slidesonnetskip`. Frames with `\pause` produce multiple sub-slides that can be narrated independently — see [Beamer documentation](docs/beamer.md) for details.

## Playlist format

A single `.yaml` file per presentation. Configuration and module list in pure YAML:

```yaml
title: Graph Theory Lecture 1
tts:
  backend: piper
  piper:
    model: en_US-lessac-medium
  elevenlabs:
    api_key_env: ELEVENLABS_API_KEY
    voice_id: pNInz6obpgDQGcFmaJgB
voices:
  alice:
    piper: en_US-amy-medium
    elevenlabs: 21m00Tcm4TlvDq8ikWAM
pronunciation:
  shared:
    - pronunciation/cs-terms.md
    - pronunciation/math-terms.md
  # piper:
  #   - pronunciation/piper-hacks.md
  # elevenlabs:
  #   - pronunciation/elevenlabs-hacks.md
video:
  resolution: 1920x1080
  fps: 24
  crf: 23
  pad_seconds: 1.5
  pre_silence: 1.0
  silence_duration: 3.0
  crossfade: 0.5
modules:
  - 01-intro/slides.md
  - animations/euler.mp4
  - 02-proofs/slides.tex
  - 03-summary/slides.md
```

- Module type is auto-detected from extension (`.md` → MARP, `.tex` → Beamer, `.mp4` / `.mkv` / `.webm` / `.mov` → video passthrough)
- Lines starting with `//` are comments (filtered before YAML parsing)
- Video files are used as-is

## Pronunciation files

Reusable `.md` files with `**word**: replacement` pairs:

```markdown
# CS Pronunciation Guide

## People
**Dijkstra**: DYKE-struh
**Euler**: OY-ler

## Terms
**adjacency**: uh-JAY-suhn-see
```

Replacements are word-boundary aware (won't change "Eulerian") and case-insensitive. Reference them in the playlist under `pronunciation:`.

### Per-backend pronunciation

Pronunciation workarounds that fix one TTS engine often break another. You can specify separate files per backend:

```yaml
pronunciation:
  shared:
    - pronunciation/names.md
  piper:
    - pronunciation/piper-hacks.md
  elevenlabs:
    - pronunciation/elevenlabs-hacks.md
```

When building with `--tts piper`, the effective dictionary is `shared + piper`. With `--tts elevenlabs`, it's `shared + elevenlabs`. Backend-specific entries override shared entries for the same word.

The flat list format still works and is treated as `shared`:

```yaml
pronunciation:
  - pronunciation/names.md
```

## Voice presets

Define named voices in the playlist. Each preset can map to different voice IDs per TTS backend, so `--tts piper` and `--tts elevenlabs` both resolve correctly:

```yaml
voices:
  alice:
    piper: en_US-amy-medium
    elevenlabs: 21m00Tcm4TlvDq8ikWAM
  bob:
    piper: en_US-joe-medium
    elevenlabs: pNInz6obpgDQGcFmaJgB
```

A simple string value is also supported — it is used as-is regardless of backend:

```yaml
voices:
  alice: en_US-amy-medium
```

Then use presets per-slide: `<!-- say(voice=alice): ... -->`. If a preset has no mapping for the active backend, the slide falls back to the default voice with a warning.

## API keys

For ElevenLabs, store keys in a `.env` file at the project root (auto-loaded at build time):

```
ELEVENLABS_API_KEY=sk-xxx-your-key
```

The playlist references env var names, never values: `api_key_env: ELEVENLABS_API_KEY`.

## CLI reference

```
slidesonnet build lecture.yaml              # build video + SRT subtitles
slidesonnet build lecture.yaml --tts piper  # override TTS backend
slidesonnet build lecture.yaml --no-srt     # build without generating subtitles
slidesonnet build lecture.yaml --dry-run    # show what would be built (no TTS/FFmpeg)
slidesonnet preview lecture.yaml            # quick build with local Piper TTS
slidesonnet subtitles lecture.yaml          # regenerate SRT from cached audio
slidesonnet preview-slide slides.md 3       # play one slide's audio
slidesonnet preview-slide slides.md 3 -p lecture.yaml  # with playlist config
slidesonnet init md myproject               # MARP Markdown project
slidesonnet init tex myproject              # Beamer LaTeX project
slidesonnet list lecture.yaml               # list slides with cache status per slide
slidesonnet utterances lecture.yaml         # export narration text for proofreading
slidesonnet clean lecture.yaml              # clean cache (keeps API audio by default)
slidesonnet doctor                         # check installed dependencies
```

## Incremental builds

TTS audio is cached by content hash of the narration text, not by slide number. This means:

- **No changes** → entire build is skipped
- **Edit one slide** → only that slide's audio is re-synthesized
- **Insert a slide** → existing slides hit the cache, only the new slide triggers TTS
- **Change voice preset** → affected slides rebuild (voice is part of the hash)

Use `--dry-run` (or `-n`) to see what a build would do without making any API calls:

```
$ slidesonnet build lecture.yaml --dry-run
8 narrated slides: 5 cached, 3 need TTS (~1,200 characters via elevenlabs)
```

This is especially useful before ElevenLabs builds to estimate API usage and cost.

Build artifacts live in `cache/` next to the playlist file. Add it to `.gitignore`.

## Subtitles

Every build automatically generates an SRT subtitle file alongside the video (`lecture.srt` next to `lecture.mp4`). The subtitles use the original narration text (before pronunciation substitutions) and are timed to match the audio.

Long narrations are split into subtitle-sized chunks at sentence boundaries, then clause boundaries, then word boundaries — each chunk timed proportionally by character count.

Use the SRT file as a starting point for translation or editing with any subtitle tool. To skip generation, pass `--no-srt`. To regenerate from cache without rebuilding:

```
slidesonnet subtitles lecture.yaml
```

## Project layout

```
my-course/
├── lecture.yaml              # playlist + config
├── pronunciation/
│   └── cs-terms.md
├── 01-intro/slides.md        # MARP module
├── 02-proofs/slides.tex      # Beamer module
├── animations/euler.mp4      # video module
├── .env                      # API keys (gitignored)
├── lecture.mp4               # final output video
├── lecture.srt               # auto-generated subtitles
├── cache/                    # build artifacts (gitignored)
│   ├── audio/                # TTS cache (content-addressed)
│   ├── 01-intro/
│   │   ├── slides/           # extracted PNGs + manifest
│   │   ├── utterances/       # text sent to TTS (for debugging)
│   │   └── segments/         # per-slide video segments
│   └── .doit.db
└── .gitignore
```

## Development

```bash
git clone https://github.com/avivz/slideSonnet.git
cd slideSonnet
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[piper,dev]"

make test-unit     # unit tests only (fast, no external tools)
make test          # all tests (requires ffmpeg, marp, pdflatex, piper)
make lint          # ruff check + format
make typecheck     # mypy --strict
```

## License

MIT
