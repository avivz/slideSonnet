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

The `slidesonnet.sty` file is included in the repository root. Place it where LaTeX can find it — either in the same directory as your `.tex` file or in your local `texmf` tree.

## Narration commands

### `\say<N>{text}`

Narrate a frame's overlay **step** `N` with the given text. The `<N>` is the same overlay number you already use for beamer's `\onslide<N>`, `\item<N->`, etc. — it selects which built-up page of the frame the narration plays on:

```latex
\begin{frame}
  \frametitle{Introduction}
  \say<1>{Welcome to this lecture on graph theory.}
\end{frame}
```

**Every `\say` must carry a step number.** A bare `\say{...}` (no `<N>` and no bracket number) is an error — slideSonnet rejects it so the target step is never ambiguous. Use `\say<1>{...}` for a single-step frame.

Multiple `\say` commands targeting the **same** step are concatenated:

```latex
\begin{frame}
  \say<1>{First sentence.}
  \say<1>{Second sentence.}
  % TTS receives: "First sentence. Second sentence."
\end{frame}
```

An empty `\say<1>{}` triggers a warning ("did you mean `\nonarration`?") and is treated as silent.

### Voice and pace: `\say<N>[params]{text}`

Optional bracket parameters control voice and pace. They follow the overlay step, mirroring beamer's `\cmd<overlay>[options]{arg}` ordering:

```latex
\say<1>[voice=alice]{Alice narrates step 1.}
\say<2>[voice=bob, pace=slow]{Bob speaks slowly on step 2.}
```

Voice names reference presets defined in the playlist YAML `voices:` section. When multiple `\say` commands on the same step specify conflicting voice or pace, the last one wins.

### Legacy bracket-number form

Before angle-bracket overlays, the step was written as a bare number (or `slide=N`) inside the brackets. These still work and are exact synonyms for `<N>`:

```latex
\say[2]{text}                 % same as \say<2>{text}
\say[slide=2]{text}           % same as \say<2>{text}
\say[2, voice=alice]{text}    % step 2 + voice
```

If both forms are given and disagree (e.g. `\say<2>[3]{}`), the `<N>` overlay wins and a warning is logged. New decks should prefer `\say<N>{}` — it reads parallel to the beamer overlay specs around it.

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

## Overlay frames

Beamer frames that build up over multiple overlay steps produce multiple PDF pages. This happens with `\pause`, with overlay specs like `\onslide<2->`, `\item<2->`, `\node<2->`, with `+`/`.` increments — any beamer overlay mechanism. slideSonnet creates **one video segment per overlay step** and lets you narrate each step independently with `\say<N>{}`.

slideSonnet learns how many steps each frame has by compiling the deck and reading beamer's own `.nav` file (the `\beamer@framepages` records). Because beamer computes that itself, **every** overlay mechanism is counted correctly — not just `\pause`.

### Example

```latex
\begin{frame}
  \frametitle{Step by Step}
  \onslide<1->{First point.}
  \say<1>{Let's start with the first point.}
  \onslide<2->{Second point.}
  \say<2>{Now here's the second point.}
  \onslide<3->{Third point.}
  \say<3>[voice=alice]{And Alice explains the third.}
\end{frame}
```

This frame builds over 3 overlay steps → 3 video segments, each with its own narration. (`\pause` between the points instead of `\onslide` would produce the same three steps.)

### Rules

- **Step count** comes from beamer's `.nav` — every `\pause`, `\onslide<>`, `\item<>`, etc. is accounted for. (If the deck hasn't been compiled, slideSonnet falls back to counting `\pause`.)
- **Every `\say` is numbered** — `\say<N>{}` (or the legacy `[N]` / `[slide=N]`). A bare `\say{}` is rejected.
- **Multiple `\say` for the same step** are concatenated in file order.
- **Unnarrated steps** — steps with no `\say` are held silently for the configured `silence_duration` (or `\nonarration[secs]`). The whole build-up still appears in the video.
- **Target beyond the step count** — if `\say<5>{text}` appears in a frame with only 2 steps, the step count is extended to 5 (with a warning); the image index clamps to the last available PDF page.
- **`\slidesonnetskip` / `\nonarration` on overlay frames** — applies to all steps in the frame (a duration override, if given, applies to every step).
- **Unannotated frames** — frames with no `\say`, `\nonarration`, or `\slidesonnetskip` produce a warning and are treated as having no annotation.

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

## Compilation and image extraction

slideSonnet compiles Beamer documents with `latexmk` and extracts slide images with `pdftoppm`. Requirements:

- **latexmk** — from TeX Live (`sudo apt install latexmk`)
- **pdflatex** — from TeX Live (`sudo apt install texlive-latex-base`); invoked by latexmk
- **pdftoppm** — from poppler-utils (`sudo apt install poppler-utils`)

Images are extracted at 300 DPI as PNG files.

latexmk runs the LaTeX engine **as many times as needed** for cross-references, the table of contents, and the `.nav` file to converge — so the per-frame page counts slideSonnet reads from `.nav` always match the final PDF. It runs in the source file's parent directory, so relative paths in `\input`, `\includegraphics`, and `TEXINPUTS` resolve naturally.

A deck's own `.latexmkrc` is still read (so author build settings like `-shell-escape` or biber keep working), but slideSonnet forces the PDF and all aux files into its cache directory via `-outdir`/`-auxdir`, so a deck that routes output elsewhere won't hide the `.nav` from slideSonnet. If latexmk exits with errors but still produces a PDF, slideSonnet logs a warning and continues.
