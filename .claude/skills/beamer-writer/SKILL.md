---
name: beamer-writer
description: Write Beamer LaTeX decks + narration sidecars for slideSonnet. Use when the user asks to "write a lecture", "create slides", "write a presentation", "make a beamer deck", or wants help authoring .tex slides and their .narration file for slideSonnet.
argument-hint: [topic or instructions]
---

# Beamer Presentation Writer for slideSonnet

slideSonnet (v1) renders a finished **PDF** plus a plain-text **narration
sidecar**. Your job is to produce a compilable Beamer `.tex` whose pages carry
stable `\ssid` ids, and a `<deck>.narration` file keyed to those ids.

> There is **no** playlist YAML, no `\say{}`, no MARP. The narration text never
> lives in the `.tex` — only the slide-ids do.

## Beamer essentials

```latex
\documentclass[aspectratio=169]{beamer}
\usepackage{slidesonnet}        % defines \ssid (run `slidesonnet sty` to get the file)
\usetheme{Madrid}

\title{...}\author{...}\date{}
\begin{document}
\begin{frame}{Frame Title}
  Content: itemize, math, tikz, columns, images.
\end{frame}
\end{document}
```

- `\begin{frame}{Title}...\end{frame}` — one frame.
- `\onslide<N->{...}`, `\only<N>{...}`, `\item<N->`, `\pause` — overlay steps
  (each emits its own PDF page).
- `\[ ... \]` display math; `\includegraphics` (needs `graphicx`); `tikzpicture`
  (needs `tikz`). Always `aspectratio=169`.
- For frames containing verbatim/`listings`, add `[fragile]` — and never put a
  literal `\end{frame}` inside a listing.

## Marking slides — the `\ssid` macro

Add `\usepackage{slidesonnet}` and give **every emitted page** a stable id.

### `\ssid{id}` — a non-overlay frame's single page

```latex
\begin{frame}{Intro}
  \ssid{intro-title}
  ...
\end{frame}
```

### `\ssid<step>{id}` — name each overlay step

```latex
\begin{frame}{Euler's trick}
  \ssid<1>{euler-setup}
  \ssid<2>{euler-trick}
  \ssid<3>{euler-result}      % ranges work: \ssid<2-3>{...}
  \only<1->{Setup.}\par
  \onslide<2->{The trick.}\par
  \onslide<3->{The result.}
\end{frame}
```

Rules:
- **Exactly one id per emitted page.** Name every overlay step. A page you forget
  gets a positional `auto-p<page>-s<sub>` default and `slidesonnet check` warns.
- **Ids must be unique across the whole deck** (duplicates are a hard error).
- Ids are short, kebab-case, and meaningful (`euler-setup`, not `slide7`).
- The id is stamped invisibly (PDF text mode 3) — never visible, on any
  background.

## The narration sidecar (`<deck>.narration`)

An indented, line-oriented, git-diffable block format. Scaffold it from the
compiled PDF with `slidesonnet init deck.pdf`, then fill in each block:

```
# comments start with '#' (line-leading, or trailing ' #...')
@euler-setup
  utterance:
    voice: narrator              # optional per-utterance directives
    pace: slow                   # slow | normal | fast
    direct: deliberate, calm     # director's note (forward-compat; local engine ignores it)
    text: We want the sum of one over n squared.
  pause: 0.8                     # explicit silence, in seconds

@euler-trick
  utterance:
    text: Watch the denominators carefully.
  pause: 1
  utterance:
    voice: alex
    text: This is the whole trick.
  transition-out: crossfade 0.5  # optional; default is a cut

@intro-overview
  pause: 3                       # silent slide — held 3 seconds, no speech
```

- `@<slide-id>` starts a block (must match an id in the PDF). Its body is an
  ordered list of `utterance:` and `pause:` entries, optionally bracketed by
  `transition-in:` / `transition-out:` lines.
- Each `utterance:` carries its own `voice:`, `pace:`, `direct:`, and `text:`.
  **Voice is per-utterance** — one slide can mix voices (a dialogue works on a
  single page; each utterance is its own synthesis call). Named voices are
  defined in `slidesonnet.toml`; a raw engine voice id (e.g. `am_michael`)
  also works.
- `pause: N` is the timing primitive: between utterances, an end-of-slide
  hold, or — as a block's only content — a silent slide.
- Wrapped `text:` lines are fine: a line that isn't a known directive
  continues the text (don't start a wrapped line with a word + colon).
- Hand-edits survive GUI saves: only blocks whose content changes are
  rewritten; comments and wrapping are preserved.

## Optional config (`slidesonnet.toml`)

Only needed to override defaults or define named voices/pronunciation:

```toml
[tts]
backend = "kokoro"           # or "elevenlabs"

[tts.kokoro]
voice = "af_heart"

[video]
resolution = "1920x1080"
fps = 24

[voices.narrator]
kokoro = "af_bella"
elevenlabs = "21m00Tcm4TlvDq8ikWAM"

pronunciation = ["pronunciation/names.md"]   # **word**: replacement entries
```

## Workflow

1. **Understand the request** — topic, scope, audience, overlay usage, voices.
2. **Examine existing files** — if extending a deck, read its `.tex`,
   `.narration`, and `slidesonnet.toml` to match style and ids.
3. **Write the `.tex`** — `\usepackage{slidesonnet}`, `aspectratio=169`, a
   `\ssid` on every page (per step on overlay frames). Start with a title frame,
   end with a closing frame.
4. **Compile** — `slidesonnet sty` (drops `slidesonnet.sty`), then
   `latexmk -pdf deck.tex`. Fix any errors before finishing.
5. **Scaffold + write narration** — `slidesonnet init deck.pdf`, then fill in
   each `@id` block as natural speech.
6. **Reconcile** — `slidesonnet check deck.pdf` must report no errors (fix
   duplicate/auto/orphan ids).
7. **(Optional) render** — `slidesonnet export deck.pdf -o deck.mp4 --engine kokoro`.

## Content principles

- **Narration is speech, not slide text** — explain, give intuition, connect
  ideas. Never read the bullets aloud.
- **One idea per page**; use overlay steps to reveal progressively, narrating
  each step in its own `@id` block.
- **Math rigor, plain-language narration** — proper LaTeX on the slide, spoken
  explanation in the sidecar.
- **Pacing** — 2–4 sentences per block (~10–30s). Split dense material across
  steps rather than cramming.
- **Title/closing pages** can be silent: a block with just `pause: N`.

## Typical file structure

```
lecture/
├── deck.tex               # Beamer source with \ssid markers
├── deck.narration         # narration sidecar (keyed by \ssid)
├── deck.pdf               # compiled (the artifact slideSonnet reads)
├── slidesonnet.toml       # optional: engine, voices, pronunciation
├── slidesonnet.sty        # `slidesonnet sty` (gitignored; generated)
├── pronunciation/names.md # optional **word**: replacement dictionaries
└── .slidesonnet/          # audio + render cache (gitignored)
```

## Example: complete deck + sidecar

`graphs.tex`:

```latex
\documentclass[aspectratio=169]{beamer}
\usepackage{slidesonnet}
\usetheme{Madrid}
\title{Graph Theory Basics}\date{}
\begin{document}

\begin{frame}[plain]
  \ssid{title}
  \titlepage
\end{frame}

\begin{frame}{What is a graph?}
  \ssid<1>{graph-def}
  \ssid<2>{graph-degree}
  A graph $G=(V,E)$ has vertices $V$ and edges $E \subseteq V\times V$.
  \onslide<2->{\medskip The \emph{degree} of $v$ is the number of incident edges:
    \[ \deg(v) = |\{e\in E : v\in e\}| \]}
\end{frame}

\begin{frame}{Handshaking lemma}
  \ssid{handshake}
  \[ \sum_{v\in V}\deg(v) = 2|E| \]
\end{frame}

\begin{frame}[plain]
  \ssid{closing}
  \centering\Large Thanks for watching.
\end{frame}
\end{document}
```

`graphs.narration`:

```
@title
  utterance:
    text: Welcome. Today we'll cover the basics of graph theory.
  pause: 0.5

@graph-def
  utterance:
    text: A graph is a mathematical structure with two parts: a set of
      vertices, which represent objects, and a set of edges, which represent
      connections between them.

@graph-degree
  utterance:
    text: The degree of a vertex counts how many edges touch it.

@handshake
  utterance:
    text: The handshaking lemma says the sum of all vertex degrees equals
      twice the number of edges — because each edge adds one to the degree
      of each of its two endpoints.

@closing
  pause: 1.5
```

$ARGUMENTS
