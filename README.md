<p align="center">
  <img src="assets/logo/slidesonnet-logo.png" alt="slideSonnet" width="500">
</p>

Write, preview, and render narration for a finished slide **PDF** — keeping the
spoken words in a plain-text **sidecar** file next to the deck.

slideSonnet inverts the usual flow. Your PDF is the frozen artifact; the
narration lives in a human-readable, git-diffable file keyed to slides by stable
ids. Edit a line, hit re-render, and only that line is re-synthesized — no
recompiling slides, no re-recording a microphone. A local GUI gives you
subtitle-style editing synced to each slide; an LLM can write the first draft;
the CLI scripts the whole pipeline.

> **v1 is a rewrite.** Earlier 0.x releases compiled MARP/Beamer *source* into
> video with narration embedded inline (`<!-- say: -->`, `\say{}`). v1 works
> from a **PDF + narration sidecar** instead. See `CHANGELOG.md`.

## How it works

```
deck.pdf  ──(invisible \ssid markers)──┐
                                        ├──►  slidesonnet  ──►  deck.mp4 + deck.srt
deck.narration  ──(@slide-id blocks)────┘                       (preview in the GUI)
```

1. **Mark** every slide in your Beamer source with a stable id (`\ssid{...}`),
   compile to PDF.
2. **Scaffold** a sidecar from the PDF's ids (`slidesonnet init`).
3. **Write** narration — by hand, by an LLM, or in the GUI (`slidesonnet edit`).
4. **Render** a narrated (or silent) MP4 with subtitles (`slidesonnet export`).

## Installation

### External dependencies

| Tool | Required? | What it does | Install |
|---|---|---|---|
| **ffmpeg / ffprobe** | Yes | Audio + video composition | `sudo apt install ffmpeg` |
| **pdftoppm** | Yes | Rasterize PDF pages to images | `sudo apt install poppler-utils` |
| **latexmk + pdflatex** | To compile your deck | Build the Beamer PDF (your job, not the tool's) | `sudo apt install latexmk texlive-latex-base` |

PyMuPDF (PDF id extraction) and NiceGUI (the editor) install as Python
dependencies. After installing, run `slidesonnet doctor`.

### Install for use

Install slideSonnet as an isolated, global CLI — its own virtualenv, separate
from your system Python and any source checkout:

```bash
uv tool install "slidesonnet[kokoro]"    # or: pipx install "slidesonnet[kokoro]"
```

The `[kokoro]` extra adds [Kokoro](https://github.com/hexgrad/kokoro) (82M,
Apache-2.0) for free, natural-sounding local speech (~2x real-time on CPU;
the model downloads on first use). Then run `slidesonnet doctor` to confirm the
external tools above are visible.

Upgrade with `uv tool upgrade slidesonnet`; remove with `uv tool uninstall
slidesonnet`. To hack on slideSonnet itself instead, see
[Development](#development) for the editable install.

## Quick start

```bash
# 1. Drop the LaTeX macro next to your Beamer source and \usepackage it
slidesonnet sty                      # writes slidesonnet.sty

# 2. In your .tex: \usepackage{slidesonnet} and \ssid{...} on every frame,
#    then compile however you like:
latexmk -pdf deck.tex

# 3. Scaffold the narration sidecar from the PDF's slide-ids
slidesonnet init deck.pdf            # writes deck.narration

# 4. Write narration (edit deck.narration, or open the editor)
slidesonnet edit deck.pdf

# 5. Render — narrated MP4 + subtitles
slidesonnet export deck.pdf -o deck.mp4 --engine kokoro
```

## Marking slides — the `\ssid` macro

`slidesonnet sty` writes `slidesonnet.sty`. In your Beamer preamble add
`\usepackage{slidesonnet}`, then give each emitted page an id:

```latex
\begin{frame}
  \ssid<1>{euler-setup}     % id for overlay step 1
  \ssid<2>{euler-trick}     % id for overlay step 2  (ranges work: \ssid<2-3>{...})
  \only<1->{...}\onslide<2->{...}
\end{frame}

\begin{frame}
  \ssid{intro-title}        % non-overlay frame: one id for its single page
  ...
\end{frame}
```

The id is stamped as **invisible** text (PDF rendering mode 3 — like an OCR
layer): never shown, on any background, but reliably recovered from the text
layer. Any page you forget to name gets a positional `auto-…` default and a
warning, so it gets a real name.

## The narration sidecar

An indented, line-oriented, git-diffable file (`deck.narration`). Each slide is
an `@id` block of one or more `utterance:` blocks and `pause:` lines:

```
# a comment
@intro-title
  utterance:
    text: Welcome to the course on the Basel problem.
  pause: 1.5
  utterance:
    text: Today we'll see how Euler summed the reciprocals of the squares.

@intro-overview
  pause: 3                  # silent slide — held 3s while they read

@euler-trick
  utterance:
    voice: bernoulli        # optional per-utterance voice
    pace: slow              # slow | normal | fast
    text: Watch the denominators carefully. This is the trick.
```

- `@<slide-id>` starts a block; each `utterance:` carries the spoken `text:`
  plus optional `voice:` / `pace:` / `direct:` (a director's note engines
  ignore). A slide can mix voices — each utterance is its own synthesis call.
- `pause: N` is an explicit silence in seconds: between utterances, as an
  end-of-slide hold, or alone as a silent slide.
- A slide can bracket itself with `transition-in:` / `transition-out:` lines
  (`cut`, the default, or `crossfade N`).

The full authoring guide — marking overlay steps, the complete sidecar
grammar, and the optional `slidesonnet.toml` config — is in
[`docs/authoring.md`](docs/authoring.md).

## The editor

`slidesonnet edit deck.pdf` opens a local [NiceGUI](https://nicegui.io/) app:
page through the deck, edit narration beside each slide, set voice/pace, generate
per-slide TTS, and **preview the whole deck**. The preview plays one pre-rendered
track with the pauses baked in and flips the slide image on cue — so the preview
is sample-accurate to the exported video. A diagnostics panel flags duplicate,
missing, orphan, or `auto-…` ids.

### Many decks in one session

The editor opens on a **library** of the decks it finds, so a course of decks
doesn't mean relaunching per deck:

```bash
slidesonnet edit                      # decks under the current folder
slidesonnet edit ~/courses/aicode     # decks under a course folder
slidesonnet edit deck.pdf             # that deck, plus its neighbours
slidesonnet edit deck.pdf --root ~/courses   # ...while browsing a wider tree
```

A deck is any PDF with a matching `.narration` beside it; subfolders are searched
(`week01/intro/intro.pdf` and friends), and dot-folders, `node_modules`, and deck
caches are skipped. Once you're in a deck, **Ctrl+K** opens a type-to-filter deck
switcher and **Alt+←/→** step to the previous/next deck. Switching saves the slide
you were editing first, and asks before stopping any audio still generating.

**WSL note:** to open the editor in your *Windows* browser instead of a Linux
one:
- `slidesonnet edit deck.pdf --app` — a chromeless app window via Edge/Chrome
  (auto-detected on the Windows side; Firefox has no app-window mode).
- install `wslview` (`sudo apt install wslu`) — used automatically — for a normal
  tab in your default browser.
- `--browser CMD` for full control (e.g. `"cmd.exe /c start"`, or a browser path;
  a `{url}` token is substituted). Also settable via `SLIDESONNET_BROWSER`.

## CLI

```
slidesonnet sty    [-o PATH]                       write the LaTeX macro
slidesonnet init   deck.pdf [--merge|--force]      scaffold a blank sidecar
slidesonnet check  deck.pdf                         reconcile ids (exit≠0 on errors)
slidesonnet tts    deck.pdf [--engine ...] [--id ID ...]   synthesize into the cache
slidesonnet export deck.pdf -o OUT.mp4
        [--engine kokoro]              [--silent]
        [--timing tts|estimate|fixed:N] [--wpm N]
        [--subtitles srt|vtt|both|none] [--sub-granularity segment|slide]
slidesonnet subs   deck.pdf -o OUT.srt [--format srt|vtt] [--timing ...]
slidesonnet edit   [deck.pdf|FOLDER] [--root DIR]   launch the editor
slidesonnet clean  deck.pdf [--keep nothing|api|current|exact]
slidesonnet doctor
```

Every operation is also a typed Python function in `slidesonnet.api`
(`init_sidecar`, `synthesize_deck`, `export`, `write_subs`, …) so an LLM/CI loop
can drive the pipeline without the GUI.

### Timing & silent renders

`--timing tts` (default) uses real synthesized audio. `--timing estimate`
approximates from word count at `--wpm` for a fast rough cut with no TTS;
`--timing fixed:N` holds every page N seconds. `--silent` renders with no
narration (timing falls back to `estimate`) — pair it with subtitles for a
captioned silent cut.

## Examples

- [`examples/basel-problem/`](examples/basel-problem/) — a 22-page Euler proof
  with overlay steps and a second voice for the Bernoulli quote.
  **[▶ Watch on YouTube](https://youtu.be/pjjHS9vhjpk)** (Inworld narration).
- [`examples/showcase/`](examples/showcase/) — a self-narrated tour that teaches
  the workflow as a two-voice dialog (written in this very format).

Build them from source with `make basel` / `make showcase` (Kokoro). Videos are
hosted as GitHub Release assets, not committed.

## Development

```bash
make install      # editable install with Kokoro + dev tools
make test-unit    # fast unit tests (no external tools)
make test         # full suite (needs ffmpeg, pdftoppm, kokoro)
make lint         # ruff
make typecheck    # mypy --strict
```

All source is fully typed (`mypy --strict`); paid cloud TTS is never exercised
in tests (it costs money) — Kokoro and mocks only.

## License

slideSonnet's own code is **MIT** (see [`LICENSE`](LICENSE)).

It depends on [PyMuPDF](https://pymupdf.readthedocs.io/) (for reading slide-ids),
which is **AGPL-3.0** (or a commercial license from Artifex). AGPL is copyleft:
if you redistribute slideSonnet or run it as a network service, the AGPL terms
apply to the combined work. For local use or a normal open-source install this
is a non-issue — it only matters if you want to build a *closed-source* product
on top of it.
