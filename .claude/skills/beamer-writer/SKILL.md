---
name: beamer-writer
description: Write Beamer LaTeX presentations for slideSonnet narrated video lectures. Use when the user asks to "write a lecture", "create slides", "write a presentation", "make a beamer file", "add a beamer module", or wants help authoring .tex slide content for slideSonnet.
argument-hint: [topic or instructions]
---

# Beamer Presentation Writer for slideSonnet

Write Beamer LaTeX slides that slideSonnet compiles into narrated MP4 videos.

## Beamer Essentials

Beamer is LaTeX's presentation class. Key constructs:

```latex
\documentclass[aspectratio=169]{beamer}
\usetheme{default}          % or: Madrid, Berlin, CambridgeUniversity, etc.
\usepackage{...}

\title{...}
\author{...}
\date{...}

\begin{document}

\begin{frame}{Frame Title}
  Content here: itemize, enumerate, math, tikz, tables, images.
\end{frame}

\end{document}
```

- **`\begin{frame}{Title}...\end{frame}`** — each frame is one slide
- **`\pause`** — creates overlay sub-slides (progressive reveal)
- **`\begin{itemize}...\end{itemize}`** — bullet lists
- **`\[ ... \]`** or `\begin{equation}...\end{equation}` — display math
- **`\includegraphics[width=\textwidth]{img.png}`** — images (needs `\usepackage{graphicx}`)
- **`\begin{tikzpicture}...\end{tikzpicture}`** — diagrams (needs `\usepackage{tikz}`)
- **`\begin{columns}...\end{columns}`** with `\begin{column}{0.5\textwidth}...\end{column}` — side-by-side layout
- **`\frametitle{}`** — alternative to the `{Title}` argument on `\begin{frame}`
- Always use `aspectratio=169` for widescreen video output

## slideSonnet Narration Commands

Add `\usepackage{slidesonnet}` to define the narration commands as LaTeX no-ops (so `pdflatex` compiles normally). Place `slidesonnet.sty` in the same directory as the `.tex` file.

### `\say{text}` — narrate the slide

```latex
\begin{frame}{Topic}
  Slide content here.
  \say{Narration text spoken during this slide.}
\end{frame}
```

- Place `\say{}` anywhere inside a frame
- Multiple `\say{}` in the same frame concatenate: `\say{First.} \say{Second.}` → TTS receives "First. Second."
- Nested braces work: `\say{The set \{1,2,3\} has {three} elements.}`
- LaTeX markup (`\textbf`, `\textit`, `\emph`, `\underline`, `\text`) is stripped before TTS
- Tildes (`~`) become spaces, double backslashes (`\\`) become spaces

### `\say[params]{text}` — voice/pace override and sub-slide targeting

```latex
\say[voice=narrator]{Different voice for this slide.}
\say[voice=bob, pace=slow]{Bob speaks slowly.}
```

Voice names reference presets defined in the playlist YAML `voices:` section. On conflict, last `\say` wins.

### `\nonarration` / `\nonarration[duration]` — silent slide

Show the slide for `video.silence_duration` seconds (default 3s) with no narration. With an explicit duration (in seconds), the per-slide value overrides the global config. Use for title cards, visual pauses, or end slides.

### `\slidesonnetskip` — exclude from video

Omit the slide entirely.

### Overlay frames with `\pause`

Target sub-slides by number in brackets:

```latex
\begin{frame}{Step by Step}
  First point.
  \say{Explaining the first point.}
  \pause
  Second point.
  \say[2]{Now the second point.}
  \pause
  Third point.
  \say[slide=3, voice=expert]{Expert explains the third.}
\end{frame}
```

- N pauses → N+1 sub-slides
- `\say{text}` with no number targets sub-slide 1
- `\say[2]{text}` or `\say[slide=2]{text}` targets sub-slide 2
- Sub-slides with no `\say` become silent (warning emitted)
- `\slidesonnetskip` or `\nonarration` on an overlay frame applies to all sub-slides

## The Playlist File (Main Lecture File)

The playlist is a YAML file that defines the lecture structure. It is the entry point for `slidesonnet build`.

### Format

```yaml
title: Lecture Title
tts:
  backend: piper                     # or: elevenlabs
  piper:
    model: en_US-lessac-medium
voices:
  default:
    piper: en_US-lessac-medium
    elevenlabs: nPczCjzI2devNBz1zQrb
  narrator:
    piper: en_US-amy-medium
    elevenlabs: 21m00Tcm4TlvDq8ikWAM
pronunciation:
  shared:
    - pronunciation/general.md
  # piper:
  #   - pronunciation/piper-hacks.md
  # elevenlabs:
  #   - pronunciation/elevenlabs-hacks.md
video:
  resolution: 1920x1080
  fps: 24
  crf: 23
  pad_seconds: 1.5
  silence_duration: 3.0
  crossfade: 0.5
modules:
  - chapter1.tex
  - chapter2.tex
  - video/interlude.mp4
  - chapter3.tex
```

### Key rules

- **Modules** are listed under the `modules:` key as plain strings
- **File extension determines type**: `.tex` → Beamer, `.md` → MARP, `.mp4`/`.mkv`/`.webm`/`.mov` → video passthrough
- Paths are relative to the playlist file
- Lines starting with `//` are comments (filtered before YAML parsing)
- The `voices:` section maps voice names to per-backend voice IDs — these are the names used in `\say[voice=NAME]{}`
- The `pronunciation:` section points to markdown files with `**word**: replacement` entries for TTS substitution. Can be a flat list (treated as shared) or a dict with `shared`, `piper`, `elevenlabs` keys for per-backend dictionaries
- Build command: `slidesonnet build` (or `slidesonnet build --tts piper`)

## Writing Guidelines

When writing Beamer slides for slideSonnet:

1. **Every frame needs an annotation** — use `\say{}`, `\nonarration`, or `\slidesonnetskip`. Unannotated frames produce warnings.
2. **Write narration as natural speech** — avoid reading slide text verbatim. Explain, elaborate, connect ideas. The narration should complement the visual content, not duplicate it.
3. **Use `\nonarration` for title/end slides** — not every slide needs speech.
4. **Keep narration per slide to 2-4 sentences** — roughly 10-30 seconds of audio. Longer narrations work but consider splitting across slides.
5. **Use overlays (`\pause`) for progressive reveal** — narrate each step separately with `\say[N]{...}`.
6. **Put `slidesonnet.sty` in the same directory** — or ensure it's on the TeX path.
7. **Use `aspectratio=169`** — matches the default 1920x1080 video output.
8. **Test with `pdflatex`** — the document must compile independently before slideSonnet processes it.

## Typical File Structure

```
lecture/
├── slidesonnet.yaml        # Playlist (main file)
├── slidesonnet.sty         # LaTeX package (copy from repo root)
├── chapter1.tex            # Beamer module
├── chapter2.tex            # Beamer module
├── images/                 # Shared images
│   └── diagram.png
├── pronunciation/          # TTS pronunciation dictionaries
│   └── general.md
└── cache/                  # Build artifacts (gitignored)
    └── ...
```

## Example: Complete Beamer Module

```latex
\documentclass[aspectratio=169]{beamer}
\usetheme{default}
\usepackage{slidesonnet}

\title{Graph Theory Basics}
\begin{document}

\begin{frame}{Graph Theory Basics}
  \nonarration
\end{frame}

\begin{frame}{What is a Graph?}
  A graph $G = (V, E)$ consists of:
  \begin{itemize}
    \item A set of \textbf{vertices} $V$
    \item A set of \textbf{edges} $E \subseteq V \times V$
  \end{itemize}
  \say{A graph is a mathematical structure with two components: a set of vertices, which represent objects, and a set of edges, which represent connections between them.}
\end{frame}

\begin{frame}{Degree of a Vertex}
  The degree of vertex $v$ is the number of edges incident to $v$:
  \[ \deg(v) = |\{e \in E : v \in e\}| \]
  \pause
  \textbf{Handshaking Lemma:}
  \[ \sum_{v \in V} \deg(v) = 2|E| \]
  \say{The degree of a vertex counts how many edges touch it.}
  \say[2]{The handshaking lemma tells us that the sum of all vertex degrees equals twice the number of edges. This is because each edge contributes exactly one to the degree of each of its two endpoints.}
\end{frame}

\begin{frame}{Thank You}
  \nonarration
\end{frame}

\end{document}
```

$ARGUMENTS
