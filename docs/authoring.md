# Authoring guide: marking slides + writing narration

slideSonnet works from a finished **PDF** plus a **narration sidecar**. This guide
covers how to mark a Beamer deck with slide-ids and how to write the sidecar.

## 1. Mark your Beamer source

Drop the macro next to your `.tex` and load it:

```bash
slidesonnet sty          # writes slidesonnet.sty
```

```latex
\usepackage{slidesonnet}
```

Give every emitted page a stable id. On an **overlay** frame, name each step; on a
plain frame, one bare id covers its single page:

```latex
\begin{frame}
  \ssid<1>{euler-setup}      % overlay step 1
  \ssid<2>{euler-trick}      % overlay step 2  (ranges: \ssid<2-3>{...})
  \only<1->{...}\onslide<2->{...}
\end{frame}

\begin{frame}
  \ssid{intro-title}         % non-overlay frame
  ...
\end{frame}
```

The id is stamped as **invisible** text (PDF rendering mode 3 — like an OCR layer):
never visible, on any background, but reliably recovered from the text layer.
Compile however you like (`latexmk -pdf deck.tex`).

**Rules**

- Every emitted page should have exactly one `\ssid`. A page you forget gets a
  positional `auto-p<page>-s<sub>` default — `slidesonnet check` warns so you give
  it a real name.
- Ids must be unique across the deck (duplicate ids are a hard error).
- Ids are the *only* coupling to your source — the narration text never lives in
  the `.tex`.

## 2. Scaffold the sidecar

```bash
slidesonnet init deck.pdf        # writes deck.narration, one @block per slide
slidesonnet check deck.pdf       # reconcile ids; exits non-zero on errors
```

`init --merge` tops up an existing sidecar with blocks for new ids (leaving your
text untouched); `init --force` overwrites.

## 3. Write narration

`deck.narration` is a flat, line-oriented file:

```
# a comment (line-leading '#', or a trailing ' #...')
@euler-setup
:voice narrator
We want the sum of one over n squared. [pause 0.8]

@euler-trick
:pace slow
Watch the denominators. [pause 1] This is the trick.

@intro-overview
[pause 3]            # silent slide — held 3 seconds
```

- `@<slide-id>` starts a block.
- `:voice <name>` / `:pace slow|normal|fast` are optional per-block directives.
  Voices are defined in `slidesonnet.toml`.
- `[pause N]` is the single timing primitive: a mid-sentence pause, an
  end-of-slide hold, or — as the only content — a silent slide.
- Body lines within a block join with spaces.

## 4. Render

```bash
slidesonnet export deck.pdf -o deck.mp4 --engine piper      # narrated + subtitles
slidesonnet export deck.pdf -o deck.mp4 --silent            # fast silent cut
slidesonnet edit  deck.pdf                                  # GUI editor + preview
```

## Config (`slidesonnet.toml`, optional)

```toml
[tts]
backend = "piper"          # or "elevenlabs"

[tts.piper]
model = "en_US-lessac-medium"

[video]
resolution = "1920x1080"
fps = 24

[voices.narrator]
piper = "en_US-lessac-medium"
elevenlabs = "EXAVITQu4vr4xnSDxMaL"

pronunciation = ["pronunciation/names.md"]   # **word**: replacement entries
```

Place it next to the deck; it's auto-discovered. With no config, sensible defaults
(Piper, 1080p) apply.
