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

**Plain and final builds.** An ordinary compile is a *plain* build: page
numbers, navigation, and (metropolis) progress bars are drawn invisibly — they
keep their space, so the layout never moves, but they don't change when a slide
is inserted or removed. That keeps slide-by-slide comparisons exact while you
iterate. When you're done — for distributing the slides or rendering the final
video — make a *final* build, which shows them:

```bash
latexmk -pdf -usepretex='\def\ssfinal{}' deck.tex
# or: pdflatex "\def\ssfinal{}\input{deck}"
```

**Rules**

- Every emitted page should have exactly one `\ssid`. A page you forget gets a
  positional `auto-p<page>-s<sub>` default — `slidesonnet check` warns so you give
  it a real name.
- Ids must be unique across the deck. A repeated id is renamed on the later page
  (`twin` → `twin-2`) with a warning; give each page its own `\ssid`.
- A PDF with no `\ssid` on any page is an error in `init` and `check`: run
  `slidesonnet sty`, add `\usepackage{slidesonnet}`, and recompile.
- Ids are the *only* coupling to your source — the narration text never lives in
  the `.tex`.

## 2. Scaffold the sidecar

```bash
slidesonnet init deck.pdf        # writes deck.narration, one @block per slide
slidesonnet check deck.pdf       # reconcile ids; exits non-zero on errors
```

`init --merge` tops up an existing sidecar with blocks for new ids (leaving your
text untouched); `init --force` overwrites. The new file starts with a commented
example of the grammar below.

`check` reports, besides id problems: a voice the engine doesn't have (for
engines that publish a voice list, like Kokoro — all its languages), a slide-id
with two `@` blocks (with both line numbers), and, as warnings, a plain build
(which `export` only turns into a draft) and a Kokoro Japanese (`j*`) or Mandarin
(`z*`) voice whose extra package isn't installed (`pip install 'misaki[ja]'` /
`'misaki[zh]'`; `doctor` lists both).

## 3. Write narration

`deck.narration` is an indented, line-oriented, git-diffable file. Each slide is
an `@id` block of `utterance:` blocks and `pause:` lines, optionally bracketed by
transitions:

```
# a comment (line-leading '#', or a trailing ' #...' on a structural line)
@euler-setup
  utterance:               # voice/pace/direct are optional
    voice: narrator
    pace: slow             # slow | normal | fast
    # direct: a director's note (Inworld's inworld-tts-2 follows it)
    direct: warm, unhurried
    text: We want the sum of one over n squared, as [Mengoli](/menˈɡoːli/) asked.
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
  `pace:` (`slow|normal|fast`), and `direct:` (a director's note; see
  [Delivery on Inworld](#delivery-on-inworld)) are optional. Voices are defined in `slidesonnet.toml`. A slide can
  hold several utterances and mix voices — each is its own synthesis call.
- `pause: N` is an explicit silence in seconds: between utterances, as an
  end-of-slide hold, or alone as a silent slide.
- `transition-in:` / `transition-out:` bracket the slide with a transition
  name and a duration in seconds, e.g. `fade 0.5`. Names: `cut` (the default),
  `fade`, `fadeblack`, `fadewhite`, `dissolve`, `crossfade`, `wipe…`, `slide…`,
  `cover…` and `reveal…` with a direction (`left`, `right`, `up`, `down`, e.g.
  `wipeleft`), and `circleopen` / `circleclose`. A boundary is written on only one side — setting an
  outgoing transition clears the next slide's incoming one.
- `[word](spoken form)` inside `text:` fixes how a word is said without
  touching the captions: `[Mengoli](/menˈɡoːli/)` (IPA between slashes, one
  pair per word: `[Leonhard Euler](/ˈleɪɒnhɑːrt/ /ˈɔɪlər/)`) or a respelling,
  `[Dijkstra](DYKE-struh)`. Subtitles and the editor show `Mengoli`; Inworld
  says the IPA or respelling; Kokoro and Qwen3 say a respelling but never IPA
  (they say the word as written instead). The `(` must follow the `]` directly.
- A `#` on a `text:` line (or its wrapped continuation), a `voice:` line or a
  `direct:` line is spoken or kept as written ("Use issue #123"); only a line
  that starts with `#` is a comment there.
- Indentation is cosmetic (lines are classified by their leading `key:` token).
  After a `text:` line, any line that isn't a known directive continues the
  text, so hand-wrapped narration parses; the file round-trips byte-for-byte
  except for blocks you actually change.

## 4. Render

```bash
slidesonnet export deck.pdf -o deck.mp4 --draft             # writes deck.draft.mp4
slidesonnet export deck.pdf -o deck.mp4 --silent --draft    # fast silent cut
slidesonnet edit  deck.pdf                                  # GUI editor + preview
slidesonnet edit  ~/courses/aicode                          # ...on a whole folder of decks
```

A final export (no `--draft`) is refused until the deck is ready: a final
build (`latexmk -pdf -usepretex='\def\ssfinal{}' deck.tex`), no errors from
`check`, some narration, and no open review conversations. `--draft` skips
those checks and names the file `<name>.draft.mp4`, so a draft never overwrites
the real video. Only `.mp4` output is supported.

With a paid engine (`--engine inworld`), `tts` and `export` say how many new
clips they would generate and ask first; `--yes` answers for you, and without a
terminal (a script, CI) they refuse unless `--yes` is given. Clips already in
the cache are reused for free.

## Config (`slidesonnet.toml`, optional)

Place it next to the deck; it's auto-discovered. With no config, sensible
defaults (Kokoro, 1080p) apply. Every key is optional; the values shown are the
defaults unless marked as an example. Paths are relative to the toml.

```toml
# Top-level keys go above the first [table]: TOML files everything after a
# header under that table, so a key written below [voices.narrator] is ignored.
pronunciation = ["pronunciation/names.md"]   # example; **word**: replacement entries

[tts]
backend = "kokoro"           # kokoro | inworld (paid) | qwen3

[tts.kokoro]
voice = "am_echo"            # any Kokoro voice, e.g. af_heart
speed = 1.0

[tts.inworld]
voice = "Simon"
model = "inworld-tts-2"
speed = 1.0
api_key_env = "INWORLD_API_KEY"   # the environment variable holding the key
# Delivery settings: unset means Inworld's own default, and nothing is sent.
# temperature = 0.8          # example: expressiveness, above 0 up to 2 (Inworld: 1)
# delivery_mode = "stable"   # example: stable | balanced | creative (inworld-tts-2)
# language = "en-US"         # example: skip Inworld's language detection
# text_normalization = false # example: say "Dr." / "1999" exactly as written
send_direction = true        # false: don't send lines' direct: notes to Inworld

[tts.qwen3]
model = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
device = "xpu"               # cpu | cuda | xpu
voice_prompt = ""            # a .pt voice-clone prompt (with a ...-Base model)
language = "English"

[video]
resolution = "1920x1080"
fps = 24
crf = 23                     # x264 quality: lower is better and bigger
preset = "medium"            # x264 speed preset (ultrafast … veryslow)
pre_silence = 0.3            # seconds before a slide's first word
tail_seconds = 0.5           # seconds held after its last word
keep_scratch = false         # true: keep render intermediates after export (debugging);
                             # same as `export --keep-scratch` for one run

[logging]
file = ".slidesonnet/slidesonnet.log"   # or false for no run log
level = "DEBUG"              # what the file records; the console follows -v / -q
max_bytes = 2_000_000        # rotate past ~2 MB
backup_count = 3             # keep slidesonnet.log.1 … .3

[cache]
audio_dir = "~/.cache/slidesonnet/aicode"   # example: a shared speech-clip pool (see below)

[voices.narrator]            # example: a named voice → per-engine voice id
kokoro = "af_heart"
inworld = "Ashley"
```

Named voices can also live in the sidecar itself (a `voices:` block and
`default-voice:` above the first `@` block, as in the examples); the sidecar's
entries win over the toml's.

### Engines and keys

- **Kokoro** (`pip install "slidesonnet[kokoro]"`) runs locally and is free.
- **Inworld** (`pip install "slidesonnet[inworld]"`) is a paid cloud engine: the
  narration text is sent to Inworld's servers, and each new clip spends API
  credits. Put the key in a `.env` file beside the deck (or in any folder above
  it, or the one you run from): `INWORLD_API_KEY=...`. A shell export wins over
  `.env`, and `[tts.inworld] api_key_env` names a different variable. Never
  commit `.env`.
- **Qwen3** (`pip install "slidesonnet[qwen3]"`) runs locally on a GPU, is slow,
  and can clone your own voice.

Choose one per run with `--engine`, or per deck with `[tts] backend`.

### Delivery on Inworld

- **Pronunciation.** Fix a word inline with `[word](/IPA/)` (see the narration
  format above), or deck-wide with a `pronunciation` file of `**word**: form`
  lines. Both work the same way: a respelling (`DYKE-struh`) is said by every
  engine, while IPA (`/menˈɡoːli/`) goes to Inworld only — Kokoro and Qwen3 say
  the word as written instead. Captions always show the word as written.
- **Director's notes.** A line's `direct:` note (e.g. `warm, unhurried`) is sent
  ahead of it as an Inworld stage direction. Only `inworld-tts-2` follows notes,
  so only it is sent them; other Inworld models, Kokoro and Qwen3 ignore them.
  `send_direction = false` under `[tts.inworld]` stops sending them. Lines
  without a note sound (and are cached) exactly as before.
- **Square brackets.** `inworld-tts-2` reads any `[...]` as a direction and
  drops it, so slideSonnet sends brackets in the narration as round ones
  (`[0, 1]` is said as "(0, 1)"); sound tags such as `[sigh]` and `[laugh]`
  stay tags. `check` notes each slide that has them.
- **Settings.** `temperature`, `delivery_mode`, `language` and
  `text_normalization` are sent only when set. Every setting, fix and note is
  part of a clip's cache key, so changing one re-generates exactly the clips it
  affects; leaving a setting unset (or blank) keeps the clips you already have.

### Sharing speech clips across checkouts (`[cache] audio_dir`)

Synthesized clips are content-addressed (text + voice + engine settings), so one
directory can safely serve every deck of a course — and every git worktree of
it. By default clips live in `<deck dir>/.slidesonnet/audio/`, which a fresh
worktree starts without, so it would re-synthesize (and, on Inworld, re-buy)
lines the main checkout already has. Point every checkout at one **pool**
instead. Where a deck's pool is comes from, first match wins:

1. `slidesonnet --audio-dir DIR <command>` — for one run;
2. `SLIDESONNET_AUDIO_DIR` — a shell export, or a `.env` beside the deck;
3. `[cache] audio_dir` in `slidesonnet.toml` — `~` expands, a relative path is
   relative to the toml;
4. the default `<deck dir>/.slidesonnet/audio/`.

Only the clips move; render scratch stays per deck. `slidesonnet pool status
deck.pdf` shows which pool a deck resolves to and why. Switching loses nothing:
the first time a deck is used with a pool, clips still in its old local cache
are copied in, and `slidesonnet pool migrate --root <course> --apply` does the
whole course in one go (copy into the pool, then remove the local folders; a dry
run without `--apply`).

Two things change once clips are shared:

- **`slidesonnet clean deck.pdf` never touches the pool.** A clip this deck no
  longer says may be one another deck still needs, so per-deck clean only
  removes the deck's own render scratch, logs, and (after copying them into the
  pool) any leftover local clips.
- **`slidesonnet pool prune --root <course>` prunes the pool** with every deck
  under the root in view: a clip is kept if *any* deck still uses it. It is a
  dry run until you add `--apply`. Orphans from paid or slow engines (Inworld,
  Qwen3) are moved to `<pool>/trash/`, not deleted — move one back to restore
  it, or `--empty-trash` to let them go. Cheap Kokoro orphans are deleted.
