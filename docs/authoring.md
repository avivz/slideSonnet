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

`deck.narration` is an indented, line-oriented, git-diffable file. Each slide is
an `@id` block of `utterance:` blocks and `pause:` lines, optionally bracketed by
transitions:

```
# a comment (line-leading '#', or a trailing ' #...' on a content line)
@euler-setup
  utterance:
    voice: narrator        # optional per-utterance directives
    pace: slow             # slow | normal | fast
    direct: warm, unhurried  # optional director's note; engines ignore it
    text: We want the sum of one over n squared.
  pause: 0.8

@euler-trick
  transition-in: crossfade 0.5   # optional; default is a cut
  utterance:
    text: Watch the denominators.
  pause: 1
  utterance:
    text: This is the trick.

@intro-overview
  pause: 3                 # silent slide — held 3 seconds
```

- `@<slide-id>` starts a block.
- `utterance:` introduces one spoken line. Its `text:` holds the words; `voice:`,
  `pace:` (`slow|normal|fast`), and `direct:` (a director's note the local engine
  ignores) are optional. Voices are defined in `slidesonnet.toml`. A slide can
  hold several utterances and mix voices — each is its own synthesis call.
- `pause: N` is an explicit silence in seconds: between utterances, as an
  end-of-slide hold, or alone as a silent slide.
- `transition-in:` / `transition-out:` (`cut`, the default, or `crossfade N`)
  bracket the slide. A boundary is written on only one side — setting an
  outgoing transition clears the next slide's incoming one.
- Indentation is cosmetic (lines are classified by their leading `key:` token).
  After a `text:` line, any line that isn't a known directive continues the
  text, so hand-wrapped narration parses; the file round-trips byte-for-byte
  except for blocks you actually change.

## 4. Render

```bash
slidesonnet export deck.pdf -o deck.mp4 --engine kokoro     # narrated + subtitles
slidesonnet export deck.pdf -o deck.mp4 --silent            # fast silent cut
slidesonnet edit  deck.pdf                                  # GUI editor + preview
```

## Config (`slidesonnet.toml`, optional)

```toml
[tts]
backend = "kokoro"

[tts.kokoro]
voice = "af_heart"

[video]
resolution = "1920x1080"
fps = 24

[voices.narrator]            # named voice → per-backend voice id
kokoro = "af_heart"

pronunciation = ["pronunciation/names.md"]   # **word**: replacement entries
```

Place it next to the deck; it's auto-discovered. With no config, sensible defaults
(Kokoro, 1080p) apply.
