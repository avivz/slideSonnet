# Beamer LaTeX Slides

slideSonnet parses Beamer LaTeX frames and generates narrated video from them. This document covers the Beamer-specific syntax and features.

## Setup

Your Beamer document should include the `slidesonnet` package, which defines `\say`, `\silent`, and `\skip` as no-ops so LaTeX compiles normally:

```latex
\documentclass{beamer}
\usepackage{slidesonnet}

\begin{document}
% ... frames ...
\end{document}
```

The `slidesonnet.sty` file is included in the repository root.

## Narration commands

### `\say{text}`

Narrate the slide with the given text:

```latex
\begin{frame}
  \frametitle{Introduction}
  \say{Welcome to this lecture on graph theory.}
\end{frame}
```

Multiple `\say` commands in the same frame are concatenated:

```latex
\begin{frame}
  \say{First sentence.}
  \say{Second sentence.}
  % TTS receives: "First sentence. Second sentence."
\end{frame}
```

### `\say[params]{text}`

Optional bracket parameters control voice and pace:

```latex
\say[voice=alice]{Alice narrates this slide.}
\say[voice=bob, pace=slow]{Bob speaks slowly here.}
```

Voice names reference presets defined in the playlist YAML front matter.

### `\silent`

Show the slide with silence (no narration):

```latex
\begin{frame}
  \frametitle{Title Card}
  \silent
\end{frame}
```

### `\skip`

Omit the slide from the video entirely:

```latex
\begin{frame}
  \frametitle{Notes}
  \skip
\end{frame}
```

`\slidesonnetskip` is an alias for `\skip` in case `\skip` conflicts with other packages.

## Overlay frames (`\pause`)

Beamer frames with `\pause` produce multiple PDF pages (sub-slides). slideSonnet lets you narrate each sub-slide independently using a sub-slide number in the `\say` bracket params.

### Syntax

```latex
\say{text}                        % sub-slide 1 (default)
\say[2]{text}                     % sub-slide 2 (bare number)
\say[slide=2]{text}               % sub-slide 2 (explicit key)
\say[2, voice=alice]{text}        % sub-slide 2 + voice
\say[slide=3, pace=slow]{text}    % sub-slide 3 + pace
```

### Example

```latex
\begin{frame}
  \frametitle{Step by Step}
  First point.
  \say{Let's start with the first point.}
  \pause
  Second point.
  \say[2]{Now here's the second point.}
  \pause
  Third point.
  \say[slide=3, voice=alice]{And Alice explains the third.}
\end{frame}
```

This frame produces 3 PDF pages and 3 video segments, each with its own narration.

### Rules

- **Sub-slide count** is determined by `\pause` commands: `N pauses → N+1 sub-slides`
- **Default target** is sub-slide 1 — `\say{text}` without a number always targets the first sub-slide
- **Multiple `\say` for the same sub-slide** are concatenated in file order
- **Missing narration** — sub-slides with no `\say` targeting them become silent (with a warning)
- **Target beyond pause count** — if `\say[5]{text}` appears in a frame with only 2 pauses, the sub-slide count is extended to 5 (with a warning)
- **`\skip` / `\silent` on overlay frames** — applies to all sub-slides in the frame

### Backward compatibility

Frames without `\pause` behave exactly as before: multiple `\say` commands concatenate onto a single slide. Frames with `\pause` but only unnumbered `\say` commands put all narration on sub-slide 1; remaining sub-slides are silent.

## LaTeX markup in narration

Common LaTeX formatting commands are stripped from narration text before TTS:

```latex
\say{This is \textbf{important} and \emph{emphasized}.}
% TTS receives: "This is important and emphasized."
```

Supported: `\textbf`, `\textit`, `\emph`, `\underline`, `\text`. Nested markup is handled correctly. Other commands (e.g., `\item`, `\newline`) are removed as well.

## Image extraction

slideSonnet compiles Beamer documents with `pdflatex` and extracts slide images with `pdftoppm`. Requirements:

- **pdflatex** — from TeX Live (`sudo apt install texlive-latex-base`)
- **pdftoppm** — from poppler-utils (`sudo apt install poppler-utils`)

Images are extracted at 300 DPI as PNG files.
