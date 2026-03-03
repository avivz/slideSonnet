# Beamer LaTeX Slides

slideSonnet parses Beamer LaTeX frames and generates narrated video from them. This document covers the Beamer-specific syntax and features.

## Setup

Your Beamer document should include the `slidesonnet` package, which defines `\say`, `\nonarration`, and `\slidesonnetskip` as no-ops so LaTeX compiles normally:

```latex
\documentclass{beamer}
\usepackage{slidesonnet}

\begin{document}
% ... frames ...
\end{document}
```

The `slidesonnet.sty` file is included in the repository root. Place it where pdflatex can find it — either in the same directory as your `.tex` file or in your local `texmf` tree.

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

An empty `\say{}` triggers a warning ("did you mean `\nonarration`?") and is treated as silent.

### `\say[params]{text}`

Optional bracket parameters control voice and pace:

```latex
\say[voice=alice]{Alice narrates this slide.}
\say[voice=bob, pace=slow]{Bob speaks slowly here.}
```

Voice names reference presets defined in the playlist YAML `voices:` section. When multiple `\say` commands in the same frame (or sub-slide) specify conflicting voice or pace, the last one wins.

### `\nonarration` / `\nonarration[duration]`

Show the slide with silence (no narration). Without a duration argument, the slide appears for the configured `video.silence_duration` (default: 3 seconds). With an explicit duration (in seconds), the per-slide value overrides the global config:

```latex
\begin{frame}
  \frametitle{Title Card}
  \nonarration           % uses global silence_duration
\end{frame}

\begin{frame}
  \frametitle{Complex Diagram}
  \nonarration[10]       % hold for 10 seconds
\end{frame}

\begin{frame}
  \frametitle{Quick Transition}
  \nonarration[1.5]      % hold for 1.5 seconds
\end{frame}
```

> **Tip:** Always specify an explicit duration — e.g. `\nonarration[5]` — rather than relying on the global `silence_duration` default. Explicit durations make the pacing of your presentation self-documenting and independent of project-level configuration changes.

### `\slidesonnetskip`

Omit the slide from the video entirely:

```latex
\begin{frame}
  \frametitle{Notes}
  \slidesonnetskip
\end{frame}
```

Note: `\skip` is a TeX primitive (a length register) and is **not** used by slideSonnet. Always use `\slidesonnetskip` to skip frames.

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
- **Target beyond pause count** — if `\say[5]{text}` appears in a frame with only 2 pauses, the sub-slide count is extended to 5 (with a warning); the image index clamps to the last available PDF page
- **`\slidesonnetskip` / `\nonarration` on overlay frames** — applies to all sub-slides in the frame (duration override, if given, applies to every sub-slide)
- **Unannotated frames** — frames with no `\say`, `\nonarration`, or `\slidesonnetskip` produce a warning and are treated as having no annotation

### Backward compatibility

Frames without `\pause` behave exactly as before: multiple `\say` commands concatenate onto a single slide. Frames with `\pause` but only unnumbered `\say` commands put all narration on sub-slide 1; remaining sub-slides are silent.

## Braces and special characters

### Nested braces

slideSonnet uses brace-counting (not a flat regex) to extract `\say` body text, so nested braces work correctly:

```latex
\say{This has {nested braces} in the text.}
% TTS receives: "This has {nested braces} in the text."
```

### Escaped braces

Escaped braces (`\{` and `\}`) are treated as literal characters and do not affect brace matching:

```latex
\say{The set \{1, 2, 3\} is finite.}
```

### Special characters

- **Tildes** (`~`) are converted to spaces (LaTeX uses `~` as a non-breaking space)
- **Double backslashes** (`\\`) are converted to spaces (LaTeX line breaks)

## LaTeX markup in narration

Common LaTeX formatting commands are stripped from narration text before TTS:

```latex
\say{This is \textbf{important} and \emph{emphasized}.}
% TTS receives: "This is important and emphasized."
```

Supported: `\textbf`, `\textit`, `\emph`, `\underline`, `\text`. Nested markup is handled correctly via brace-counting:

```latex
\say{A \textbf{bold \emph{and italic}} phrase.}
% TTS receives: "A bold and italic phrase."
```

Other LaTeX commands (e.g., `\item`, `\newline`) are removed as well. Whitespace is normalized to single spaces.

## Image extraction

slideSonnet compiles Beamer documents with `pdflatex` and extracts slide images with `pdftoppm`. Requirements:

- **pdflatex** — from TeX Live (`sudo apt install texlive-latex-base`)
- **pdftoppm** — from poppler-utils (`sudo apt install poppler-utils`)

Images are extracted at 300 DPI as PNG files.

pdflatex runs in the source file's parent directory, so relative paths in `\input`, `\includegraphics`, and `TEXINPUTS` resolve naturally. If pdflatex exits with errors but still produces a PDF, slideSonnet logs a warning and continues.
