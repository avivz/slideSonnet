---
name: build
description: Run the slideSonnet CLI — scaffold, check, synthesize, export, and preview narrated videos from a PDF + narration sidecar. Use when the user asks to "render", "export", "build", "check", "synthesize", "preview", "clean", "pool", "review", or "doctor" a slideSonnet deck.
argument-hint: [deck.pdf or command]
---

# slideSonnet CLI Skill

slideSonnet renders a finished **PDF** (with invisible `\ssid` slide-ids) plus a
plain-text **`<deck>.narration`** sidecar into a narrated MP4 with subtitles.
There is no playlist, no `build` command, no MARP — you bring the PDF.

Engines: `kokoro` (local, free, the default), `inworld` (cloud, **paid per
clip**), `qwen3` (local GPU, slow). Errors print one line; add `-v` (before or
after the command: `slidesonnet export … -v`) to see the traceback.

## Command reference

### `slidesonnet sty` — write the LaTeX macro

```bash
slidesonnet sty [-o PATH]      # default: ./slidesonnet.sty
```

Drops `slidesonnet.sty` next to your Beamer source. `\usepackage{slidesonnet}`
and mark pages with `\ssid<step>{id}` / `\ssid{id}`, then compile (`latexmk -pdf`).
An ordinary compile is a *plain* build (page numbers hidden); the final video
needs a *final* build: `latexmk -pdf -usepretex='\def\ssfinal{}' deck.tex`.

### `slidesonnet init` — scaffold the narration sidecar

```bash
slidesonnet init deck.pdf [--narration PATH] [--merge] [--force]
```

Reads the slide-ids from the PDF and writes a blank `deck.narration` (one `@id`
block per page, with a commented example of the grammar). `--merge` appends
blocks for ids missing from an existing sidecar (safe to re-run after the deck
drifts); `--force` overwrites. A PDF with no `\ssid` at all is an error.

### `slidesonnet check` — reconcile ids

```bash
slidesonnet check deck.pdf [--narration PATH]
```

Reports duplicate / `auto-…` / missing / orphan / order issues, duplicate `@`
blocks (with line numbers), unknown engine voices, and warns when the PDF is a
plain build. **Exits non-zero on errors** — use it in an LLM/CI loop after
editing slides or narration.

### `slidesonnet tts` — synthesize into the cache

```bash
slidesonnet tts deck.pdf [--engine kokoro|inworld|qwen3] [--id ID ...] [--yes]
```

Synthesizes narration into the content-addressed cache (only missing/changed
clips) and reports "N generated, M reused". `--id` restricts to specific slides
(an unknown id is an error with a suggestion). With a paid engine it asks before
generating new clips; `--yes` skips the question, and without a terminal it
refuses unless `--yes` is given.

### `slidesonnet export` — render the video

```bash
slidesonnet export deck.pdf -o OUT.mp4 [OPTIONS]
```

| Flag | Effect |
|------|--------|
| `--draft` | Export a deck that isn't final (plain build, `check` errors, no narration, open review); writes `OUT.draft.mp4` |
| `--engine kokoro` | Local Kokoro TTS (free) |
| `--engine inworld` | Inworld cloud TTS (**costs money!**) |
| `--yes` | Generate paid clips without asking |
| `--silent` | No TTS: silent video; timing from the model below |
| `--timing tts` | Real synthesized audio (default) |
| `--timing estimate [--wpm N]` | Approximate from word count — fast rough cut, no TTS |
| `--timing fixed:N` | Hold every page N seconds |
| `--subtitles srt\|vtt\|both\|none` | Subtitle files beside the video (default srt) |
| `--sub-granularity segment\|slide` | One cue per speech segment (default) or per slide |
| `--keep-scratch` | Keep the render intermediates in `.slidesonnet/render/` (debugging) |

Without `--draft`, export refuses a plain build, a deck with `check` errors, a
deck with no narration, and open review conversations. Only `.mp4` output.

### `slidesonnet subs` — subtitles without rendering video

```bash
slidesonnet subs deck.pdf -o OUT.srt|OUT.vtt [--format srt|vtt] [--engine ...] [--timing ...] [--allow-estimates]
```

The format follows the output's extension. Pass the engine the video was made
with; under `--timing tts` it refuses lines with no generated audio unless
`--allow-estimates`. Never triggers TTS.

### `slidesonnet edit` — launch the editor

```bash
slidesonnet edit [deck.pdf|FOLDER] [--root DIR] [--narration PATH] [--host H] [--port P] [--no-browser] [--app]
```

Local browser editor: a library of decks, page nav, narration editing (saved as
you type), per-slide TTS, whole-deck preview, diagnostics, and the Review tab.

### `slidesonnet review` — conversations about an agent's changes

```bash
slidesonnet review status  deck.pdf                   # changed slides, unfiled changes
slidesonnet review comment deck.pdf @x @y -m "…" [--title "…"]  # no slides: the whole deck
slidesonnet review reply   deck.pdf c3 -m "…" [--add-slides @z] [--remove-slides @w]
slidesonnet review list    deck.pdf --mine --json     # what awaits the agent
slidesonnet review wait    --since CURSOR --json      # block until Send in any deck here (--root DIR)
slidesonnet review wait    deck.pdf --since N --json  # one deck only (its cursor is a number)
```

Also `title`, `accept`, `reopen`, `send`, `clear`, `show`, `snapshot`. `status`,
`list`, `snapshot` and `clear` take `--narration PATH` for a deck edited with
`edit --narration`. Never edit `<deck>.review` by hand.

### `slidesonnet clean` — prune the deck's cache

```bash
slidesonnet clean deck.pdf [--keep nothing|api|current|exact] [--dry-run] [-y] [--narration PATH]
```

| Level | Keeps | Removes |
|-------|-------|---------|
| `api` (default) | All paid (Inworld) clips | Local clips + renders |
| `current` | Clips for text the deck still says (any engine) | Orphans + renders |
| `exact` | Clips the deck would use with its current engine settings | Everything else |
| `nothing` | Nothing | The deck's whole cache |

At every level, clips another deck in the same folder still says are kept, and
paid clips go to `.slidesonnet/audio/trash/` rather than being deleted (it asks
first unless `-y`). `--dry-run` shows what would go and changes nothing; run it
before any level other than `api`. A shared pool is never touched by `clean`.

### `slidesonnet pool` — a shared speech-clip pool

```bash
slidesonnet pool status  [deck.pdf]                   # which pool a deck uses, and why
slidesonnet pool migrate --root DIR [--apply]         # copy old local caches into the pool
slidesonnet pool prune   --root DIR [--apply] [--keep current|exact|api] [--empty-trash]
```

`--audio-dir DIR` before any command (or `SLIDESONNET_AUDIO_DIR`, or `[cache]
audio_dir`) points a run at a pool. `migrate` and `prune` are dry runs until
`--apply`; prune parks paid/slow orphans in `<pool>/trash/`.

### `slidesonnet doctor` — check dependencies

```bash
slidesonnet doctor
```

Checks Python, ffmpeg/ffprobe/pdftoppm/PyMuPDF (core), the editor, latexmk/pdflatex
(to compile your deck), the kokoro/inworld/qwen3 engines, and `INWORLD_API_KEY`.
Exit 1 if a core dependency is missing.

## Common workflows

**From a marked Beamer source to a video:**
```bash
slidesonnet sty                               # drop the macro
latexmk -pdf deck.tex                         # compile (your job) — plain build
slidesonnet init  deck.pdf                    # scaffold narration
# ...write deck.narration...
slidesonnet check deck.pdf                    # reconcile ids and voices
slidesonnet export deck.pdf -o deck.mp4 --engine kokoro --draft   # deck.draft.mp4
latexmk -pdf -usepretex='\def\ssfinal{}' deck.tex   # final build (page numbers)
slidesonnet export deck.pdf -o deck.mp4 --engine kokoro           # deck.mp4
```

**Fast visual rough cut (no TTS):**
```bash
slidesonnet export deck.pdf -o deck.mp4 --silent --draft
```

**Iterate on one slide's narration:**
```bash
slidesonnet tts deck.pdf --id euler-setup --engine kokoro
slidesonnet edit deck.pdf            # or preview the whole deck in the editor
```

**Rebuild local audio from scratch (keeps paid clips):**
```bash
slidesonnet clean deck.pdf --keep api && slidesonnet export deck.pdf -o deck.mp4 --engine kokoro
```

Every command is also a typed function in `slidesonnet.api` (`init_sidecar`,
`check_deck`, `synthesize_deck`, `export`, `write_subs`, `build_preview`).

## Critical rules

- **NEVER use `--engine inworld` (or `--yes` with it) for testing** — it costs
  real money. Use `--engine kokoro` unless the user explicitly asks for Inworld,
  and let the user answer the paid-clip question themselves.
- **Prefer `slidesonnet clean --keep api`** (default) over `--keep nothing` to
  preserve paid cloud audio; run `--dry-run` first for any other level.
- **`slidesonnet check` before rendering** — it catches duplicate/orphan ids and
  unknown voices that would otherwise misbind or fail the narration.
- **Example videos are hosted on GitHub Releases** (`v0.0.0`), not in the repo.
  After rebuilding, upload with `gh release upload v0.0.0 path/to/video.mp4 --clobber`.

$ARGUMENTS
