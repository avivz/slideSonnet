# Changelog

All notable changes to slideSonnet will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **A deck's plain and final builds can live side by side.** Name the plain
  (working) build `deck.plain.pdf` and keep `deck.pdf` for the final one you hand
  out and export. Both are one deck — same `deck.narration`, `deck.review` and
  review base — and the editor, the library (which lists the deck once) and
  `slidesonnet review` work on the plain build when it's there, even when given
  `deck.pdf`. Each build keeps its own page renders. Export still refuses a plain
  build; the editor names its videos `deck.mp4`.
- **`slidesonnet check` warns about two pauses in a row** on a slide, naming the
  slide and the lines in the narration file: two silences back to back are just
  one longer silence, and usually a slip. The editor shows the warning on that
  slide too.

### Changed
- **Starting a review conversation no longer greys out the other slides.** You
  stay where you were; the new conversation is marked "new" in the Review tab's
  list, and clicking it opens it as before.
- **Going to a slide outside the conversation you're reading shows every slide
  again** — from the Script view (clicking anywhere in that slide, or into its
  words) and the Slide view's narration, not only from the slide strip.

### Fixed
- **One pause between two lines shows as one pause in the Script view.** Every
  line used to be followed by an extra `⏸ 0.0` of its own, so a single pause read
  as two, and a number typed into that extra box was quietly lost. To add a pause
  between two lines that have none, point at the first line: a `⏸ 0.0` appears
  after its last word; type the seconds there.
- **A line you empty in the Script view goes away once you click away from it**,
  as deleting it in the Slide view does. It used to linger as an empty box until
  the page was reloaded (most visibly during a review). The file was already
  right; a line you've just added still waits for your words.

## [1.0.0a3] — 2026-09-29

### Breaking
Read this first when upgrading from 1.0.0a2.

- **Plain builds are the default for `slidesonnet.sty`.** An ordinary compile now
  draws page numbers, the headline (navigation) and metropolis progress bars
  invisibly (the layout is unchanged), so slide-by-slide comparisons stay useful.
  A *final* build shows them: `latexmk -pdf -usepretex='\def\ssfinal{}' deck.tex`.
  **Re-run `slidesonnet sty` and compile your final video with `\ssfinal`**, or the
  page numbers disappear from it. Final builds carry an invisible `SSFINAL` marker
  (`slidesonnet.pdf.reader.is_final_build`).
- **`export` refuses a deck that isn't ready** — a plain build, open review
  conversations, errors from `check`, or no narration — listing each reason.
  `--draft` (or "Export draft" in the editor) renders anyway, to
  `<name>.draft.mp4`. PDFs from an older `slidesonnet.sty` carry no build marker and
  export as before. Only `.mp4` output is accepted; a PDF with no `\ssid` is an
  error in `init` and `check`; a missing `--narration` file is an error rather than
  an empty deck.
- **Paid work asks first on the command line.** `tts` and `export` ask before
  generating Inworld clips (including a forced regenerate of a fully cached deck);
  `--yes` skips the question, and without a terminal they refuse — add `--yes` to
  scripts. `clean` never deletes paid clips: after a prompt they move to
  `.slidesonnet/audio/trash/`.
- **Some existing clips regenerate once:**
  - The default Inworld model is now **`inworld-tts-2`** (was
    `inworld-tts-1.5-max`). The model is part of the cache key, so existing Inworld
    clips re-synthesize (paid) on the next generate; set `[tts.inworld] model` in
    `slidesonnet.toml` to keep the old one.
  - **Director's notes (`direct:`) now go to Inworld** (`inworld-tts-2` performs
    them; other models are never sent them). Lines with a note regenerate once;
    `[tts.inworld] send_direction = false` opts out.
  - **Pronunciation-dictionary IPA (`/…/`) now goes to Inworld only.** Kokoro and
    Qwen3 say the word ("Mengoli") instead of reading the IPA out; their lines with
    such a word regenerate once, for free.
  - **Qwen3** clips now depend on `[tts.qwen3] language` (English keeps existing
    clips), and a per-voice `.pt` prompt is keyed by its content, not its path;
    per-voice clips made before this regenerate once.
- **`#` in narration is text.** On `text:`, `voice:` and `direct:` lines only a
  line *starting* with `#` is a comment: `voice: x  # note` now keeps `# note` as
  part of the value. Put comments on their own line.
- **A silent export has no audio stream** (it was a silent AAC track).
- **`subs --timing tts` refuses to guess.** When audio is missing it names the
  lines and slides instead of silently falling back to a words-per-minute guess;
  pass `--allow-estimates` (or `--timing estimate`) to allow guesses. `subs` now
  takes its format from the output file's extension.
- **`slidesonnet.toml` is checked strictly**, each error naming its key: string
  booleans (`"false"`), nan/inf, odd or zero resolutions and `crf` outside 0–51 are
  refused, and an explicitly given config file that doesn't exist is an error
  instead of silently meaning defaults.
- **`edit --host 0.0.0.0` requires `--allow-host NAME`**, and any non-loopback bind
  warns.
- **The NiceGUI editor was replaced by a new Vue editor** served by FastAPI +
  Uvicorn; NiceGUI is no longer a dependency. When a deck's `slidesonnet.toml`
  names no engine, the editor now starts on **Inworld** (anything that spends
  credits still asks first); the command line keeps the free Kokoro default.
- **API: `ProgressFn` is now `(phase, done, total, label)`** (was `(slide_id, done,
  total)`, with `"assemble"` sometimes standing in for the slide id). Callers
  passing `progress=` to `synthesize_deck`, `export` or `build_preview` need the
  extra argument. New `api.export_phases()` lists the phases an export reports, for
  `slidesonnet.progress.RunProgress`.

### Added
- **A new deck editor.** `slidesonnet edit` opens a redesigned editor: the player
  sits under the slide, deck-wide tools (engine, voices, generate, export) top the
  console, the filmstrip labels each slide's state, and typing is saved as you go.
  There are no full-width bars — the deck name, errors (only when there are some)
  and shortcuts (?) sit atop the slides column, each side pane folds away, and a
  line's voice, pace and note fold behind ⋯. Generation is shared between tabs and
  keeps going if you reload; an export started in the editor keeps going if you
  close the tab. Every confirmation uses the editor's own dialog.
- **Script view** (the editor's default; **Slide** switches back): the whole deck's
  narration as one editable document, one paragraph per line, pauses at the end of
  the line before them. While playing, the spoken line is marked up to the current
  word. Under review, each changed slide shows its narration changes word by word.
- **A deck library and deck switching.** `slidesonnet edit` accepts a folder, a
  deck (`edit deck.pdf` opens it directly and lists its neighbours) or nothing (the
  current folder); `--root` scans a wider tree. The library finds every PDF with a
  `.narration` beside it, grouped by folder and sorted naturally (`week9` before
  `week10`); type to filter (**/** or **Ctrl+K**), ↑/↓ and **Enter** to open. PDFs
  without narration are listed last with the command that starts one. Inside a
  deck, **Ctrl+K** (or clicking its name) opens a switcher and **Alt+←/→** step
  through the library. Each deck has its own URL (`/d/<token>`), so back/forward,
  bookmarks and two decks in two tabs work. Leaving a deck by any route saves first
  (and stays put if the save fails), stops playback and cancels audio still
  generating for it (finished clips stay cached).
- **Review conversations** — a loop for reviewing an agent's changes slide by
  slide. The *base* (every slide's page image, text, narration and order) is taken
  the first time a deck is opened; `slidesonnet review status` lists slides that
  differ from it (new, edited, moved, deleted, matched by slide id; a hair's
  re-layout doesn't count). Conversations live in a human-readable, append-only
  `<deck>.review` beside the deck (created only once something is written):
  `list` (`--all`, `--mine`), `comment`, `reply` (`-m`, `--add-slides`, including a
  slide not compiled yet, `--title`), `title`, `accept`, `reopen`, `clear` (drops
  closed ones and moves the base forward), a permanent deck-wide `deck`
  conversation, and `send` / `wait --since N` so an agent can block until you hand
  over a batch (`wait --timeout` exits 3). `review` commands take `--narration`.
  The editor and an agent can write at the same time. Audio of the review base
  counts as in use until `review clear`, and no clean level deletes the base.
- **Review in the editor.** The console's **Review** tab lists conversations (the
  deck conversation pinned on top, ✓ accepts on a row) and counts what waits for
  you across the deck; a banner says where the agent is waiting. Choosing one greys
  out the other slides and shows its messages, reply box and Reopen. A new
  conversation is about the slide on screen or several (Ctrl-click in the
  filmstrip); rename one with ✎. A changed slide shows its base beside the current
  version (`D` toggles before-only) and a word diff; moved slides are marked ↕,
  removed ones appear as faded tiles, and `N` jumps to the next slide waiting for
  you. Changes with no conversation (a recompile, an outside edit) are filed into
  their own; your own edits carry no review markings. A note goes out with Enter
  (Shift+Enter for a new line) and wakes an agent in `review wait`. **Clear
  accepted** (asks first) makes accepted changes the new base; **Reset comparison**
  compares from the deck as it is now.
- **Quick export: `export --fast`** (and a *Quick export* box in the editor): 720p,
  plain cuts, the stills encoded in one pass; the same audio and subtitles. Writes
  `<name>.fast.mp4`, so a full-quality video is never replaced. On the basel demo:
  about 2 min for a full export, about 15 s for a first quick one, about 2 s for a
  repeat after a slide-only change.
- **Inworld delivery controls.**
  - **Fix how a word is said, not how it's captioned:** `[Mengoli](/menˈɡoːli/)`
    (IPA) or `[Dijkstra](DYKE-struh)` (a respelling). Subtitles and the editor show
    "Mengoli"; Inworld says the IPA; Kokoro and Qwen3 say a respelling, or the word
    as written (never IPA). `check` and the editor warn about a fix typed with a
    space, `[Dijkstra] (DYKE-struh)`, which is read as written.
  - `temperature`, `delivery_mode` (stable/balanced/creative), `language` and
    `text_normalization` under `[tts.inworld]`, sent only when set.
  - Square brackets are said, not swallowed: "[0, 1]" is sent as "(0, 1)"; sound
    tags like `[sigh]` still work.
  - Each setting, fix and note is part of the clip's cache key, so a change
    regenerates exactly the clips it affects. The editor's note field says only
    Inworld follows it.
- **A shared speech-clip pool** (`[cache] audio_dir`, `SLIDESONNET_AUDIO_DIR` in
  the shell or a deck's `.env`, or `--audio-dir`), so every deck of a course and
  every git worktree reuses the same clips instead of re-buying Inworld lines.
  `slidesonnet pool status` shows which pool a deck uses and why; clips in a deck's
  old local cache are copied in on first use; `pool migrate --root <course>
  --apply` moves a whole course. With a pool, `clean deck.pdf` touches only the
  deck's own scratch and logs, and the automatic sweep is off.
- **`slidesonnet pool prune`** keeps a clip if any deck using the pool still says
  it (`--root`, repeatable, plus explicit decks; dry run unless `--apply`). Paid or
  slow clips (Inworld, Qwen3) go to `<pool>/trash/` (`--empty-trash` to finish);
  the dry run says what each orphan said and which deck last used it. A deck that
  fails to load aborts the plan.
- **Deck checks** in the console list findings that belong to no slide (narration
  out of PDF order, narration whose slide is gone), instead of every slide saying
  "No issues on this slide".
- **`check`** flags voices the engine doesn't have, warns that a plain build
  exports only as a draft, and reports a duplicate `@id` once, with both line
  numbers (the editor agrees).
- **`clean --dry-run`, `--yes` and `--narration`**; its summary reports the paid
  clips kept, and `--keep` help explains each level.
- **Export progress covers the whole run**: every phase as one overall percentage
  that never goes backwards, with elapsed time, e.g. `[01:42 37%] 3/5 video 7/23 ·
  step2-zeros` on stderr, ending with a timing line. Wrappers can match
  `slidesonnet.progress.LINE_PATTERN` / `PHASE_PATTERN`; `--quiet` hides them.
- **`export --keep-scratch` / `[video] keep_scratch`** (see *Changed*).
- **`edit --allow-host NAME`** for network binds; `--host`/`--port` have help, and
  `--host ::1` opens a valid URL.
- **Playback speed (1× / 1.25× / 1.5× / 2×)** in the editor, applied live with
  pitch preserved; preview only — never the cache, `pace:`, or the video.
- **"Play transitions in single-slide preview"** (off by default): unchecked,
  playing one slide is a plain cut. **Watch as video** always draws transitions.
- **Resuming after an edit plays the new words**, from the start of the line it was
  paused in.
- Docs: pre-release install, a quick start that reaches a video, "Engines and
  keys", and a full `slidesonnet.toml` reference.

### Changed
- **Play all plays slide by slide and starts at once**, preparing the next slide
  while one plays, instead of building the whole deck first (13–29 s on a 55-slide
  deck). It plays the slides not greyed out, holds a silent slide for its pause,
  keeps each transition's time but cuts, and shows "slide 3 of 7". Missing clips
  are queued up front, asking once on a paid engine. The old whole-deck preview,
  transitions drawn, is now **Watch as video** (the film button). Playback starts
  with a moment of silence so Bluetooth speakers don't swallow the first word.
- **Decks open at once.** The current slide renders first and the rest fill in
  around it; a deck's page images are reused until the PDF changes; the Kokoro
  libraries load only on first synthesis. A cold open of a 22-slide deck went from
  ~11 s to ~1 s. Replaying a deck no longer re-measures every clip (lengths are
  saved in `durations.json` beside the clips), and versioned slide images are
  cached by the browser.
- **A successful `export` deletes its render scratch** (decoded PCM, `track.wav`,
  silences, per-slide segments — ~7 GB across a 33-deck course). Page images and
  clips stay; a failed export keeps everything; `--keep-scratch` or `[video]
  keep_scratch = true` keeps it always, as does an export launched from the editor.
  Silence files are shared per duration.
- **The automatic sweep waits until a Kokoro clip has been orphaned for 10
  minutes**, so trying a wording and reverting keeps the clip; it runs a moment
  after a save instead of during it. `clean` leaves files it doesn't recognise alone.
- **A narration edit marks its clip stale at once** ("Edited · click to
  regenerate"); undoing back to the original text restores it.
- `export` no longer rewrites a subtitle file whose bytes are unchanged.
- `tts` reports "N generated, M reused"; an unknown `--id` is an error with a
  suggestion; the file `init` writes shows a v1 example and the next step.
- **CLI errors are one line** saying what went wrong and how to fix it (`-v` shows
  the traceback), including LaTeX source passed instead of a PDF, unreadable PDFs
  and unwritable paths. `-q`/`-v` also work after the subcommand.
- Kokoro's `words count mismatch` warnings are hidden (`--verbose` shows them), and
  Kokoro loads its model and voices from the local cache without touching the
  network (no ~30 s stall offline); `SLIDESONNET_KOKORO_REFRESH=1` picks up a new
  upstream revision.
- `doctor` requires Python 3.13, as the package does, and checks the editor's
  server and that its browser interface is built.
- Sidecar lines split only on `\n`/`\r\n` (U+2028 and similar no longer break a
  line).

### Fixed
**Audio and paid safety**
- **`clean --keep current/exact` no longer deletes current paid audio whose voice
  is set in the narration file's `voices:`/`default-voice:`** (it mistook
  default- or preamble-voiced Inworld clips for orphans).
- **`clean` and the automatic sweep no longer delete other decks' clips** in a
  shared `.slidesonnet/audio/`: it is collected against every narrated deck in the
  folder. `--keep nothing` removes only this deck's renders.
- **The sweep honours `--narration`**; clips made for an override sidecar were
  deleted a second after being generated.
- **Paid work makes only what you approved.** An approved Inworld generate, preview
  or export that waited in line used to bill edits made meanwhile; it now stops
  with "The narration changed after you approved it; approve again to generate N
  new clips."
- `make clean` removes build artefacts only (it deleted every `.slidesonnet/`,
  including committed paid example audio).

**Narration file**
- A line break typed into an utterance can no longer add a pause, change the voice
  or start a new slide block; a line break in a voice or director's note is refused.
- `pause: -1`, `inf`, `nan` and `transition-in: fade nan` give a clear error with
  the line number (the editor refuses them too); durations are written exactly.
- The Voices dialog can't save a voice name the sidecar can't read back.
- Saves and `init` (fresh, `--force`, `--merge`) replace the narration file in one
  step, so a program watching it never reads a half-written file.

**Export and subtitles**
- **Slides stay in step with the narration.** A 30-slide video ran about a second
  behind its audio; each slide now starts within one frame of its narration, and a
  slide between two full transitions no longer gains an invented 0.1 s.
- **Subtitles no longer drift late on Inworld (MP3) renders** (≈1–2 s by the end of
  a long deck); already-cached clips are fixed too, with no re-synthesis.
- `subs` takes `--engine`, so a deck exported with Inworld no longer gets
  subtitles guessed from Kokoro-shaped cache keys (≈10 s of drift over 8 minutes).
  Note that `export` already writes matching subtitles; running `subs` after it
  overwrites them.
- Subtitle timestamps can no longer read `,1000` (invalid SRT/VTT).
- A failed or cancelled export keeps the previous video and subtitles.
- An empty utterance no longer fails the export; blank speech is skipped in
  synthesis, timing and subtitles.
- Export no longer overwrites and deletes a `concat_list.txt` of yours, and decks
  in folders named like `O'Brien` export again.
- Cancelling an export or preview and undoing an edit can no longer serve the
  edited (or half-written) audio from the render cache.
- A slide whose narration is one MP3 clip gets a real WAV page file.

**Editor**
- **Typing is no longer lost, and outside edits no longer overwritten, when the
  narration file changes on disk.** An edit to another slide leaves your typing in
  place; an edit to the slide you're on shows the file's version and offers yours
  back (**Copy my text**, **Keep my version**), one conflict at a time.
- **A recompiled PDF shows up**, also during playback: each slide keeps its old
  picture until the new one is rendered and swapped in whole (no half-sent
  images), and saving while the PDF is missing or half-written keeps the last good
  version.
- A preview always plays its own audio (a second preview could play the previous
  slide's).
- During playback the slide changes land exactly on the audio, even while you type
  on another slide; dragging the position slider and changing speed respond at once.
- Right-to-left narration (Hebrew, Arabic) lays out correctly.
- The unattached-narration actions (attach, append, delete) refuse a slide's own
  narration instead of moving or deleting it.

### Security
- **The editor checks the Host header on slide images and audio (`/ssmedia`)** as
  on its API, blocking DNS-rebinding reads.

### Removed
- **The NiceGUI editor** and the NiceGUI dependency (see *Breaking*).

## [1.0.0a2] — 2026-06-19

### Added
- **"Play all" shows a progress bar while assembling the audio track.** Building
  the whole-deck preview concatenates a per-page WAV for every slide and can take
  a while on a long deck — previously just a spinner with no sense of progress.
  The editor now shows an **"Assembling audio · X/N"** bar (reusing the generation
  progress bar) that advances per page and completes on the final concat, so you
  can see it's working and how far along it is. `api.build_preview` /
  `render.render_audio_track` gained a `progress` callback that drives it.
- **Unified, level-controlled logging across the CLI and editor.** Logging is now
  configured once at startup, so a `logger.info`/`logger.exception` from any module
  (including the background generation worker) reaches you instead of vanishing.
  `--verbose`/`-v` shows debug detail, `--quiet`/`-q` drops to warnings, and the
  `SLIDESONNET_LOG` env var sets the level when no flag is given (flag wins). Each
  deck command also writes a rotating run log to `<deck>/.slidesonnet/slidesonnet.log`
  capturing full DEBUG detail for post-mortem diagnosis — so a background-job
  failure now lands on disk with its traceback. Configure it with `--log-file PATH`,
  `--no-log-file`, or a `[logging]` section in `slidesonnet.toml` (`file`, `level`,
  `max_bytes`, `backup_count`; size-based rotation caps disk at
  `max_bytes * (backup_count + 1)`). The run log is a disposable artifact, removed
  by `slidesonnet clean`. The editor's ad-hoc `[gen] …` progress prints are now
  structured `logger` calls routed through the same configuration.
- **Inworld cloud TTS engine (`--engine inworld`).** A paid cloud backend that
  synthesizes one content-addressed clip per utterance (`[tts.inworld]` config +
  the `inworld` extra), with an `INWORLD_API_KEY` check in `slidesonnet doctor`.
  Ships with a built-in default voice (**Simon**), so an unvoiced utterance
  narrates out of the box (override per deck with `[tts.inworld] voice` or a
  named voice).
- **"Generate missing" asks before spending credits on a paid engine.** The
  whole-deck fill now shows the same confirmation popup the play path uses when
  the active engine is paid (Inworld), so a batch synthesis never
  bills unattended — declining queues nothing. Auto-generate stays fully disabled
  for paid engines, and a single per-utterance generate is still a one-click
  action.
- **Per-slide start/end silence, editable in the editor.** The hold at a slide's
  start and end (previously the invisible global `pre_silence`/`tail_seconds`) is
  now a per-slide value you can see and set: a slide with narration shows **Start
  silence** and **End silence** fields bracketing its lines, defaulting to the
  deck values, and `0` means no hold (a quick, hard change). A leading/trailing
  `pause:` in the `.narration` file *is* that silence — it replaces the default
  rather than adding to it — so the file stays the source of truth. Saving in the
  editor materializes the defaults into explicit `pause:` blocks.
- **Transitions play over the narration, centered on the slide boundary.** A
  transition is now a visual overlay centered on the cut between two slides — half
  over the end of the outgoing slide, half over the start of the incoming one —
  playing over whatever audio is there (silence *or* speech), so a wipe between
  overlay steps reads as a build animation without inserting a gap. The deck's
  total length and audio are unchanged (the morph never adds time). A transition
  longer than the shorter adjacent slide is clamped, and `slidesonnet check` now
  warns (`transition-too-long`) before you export.
- **The utterance voice picker shows each named voice's engine voice.** A named
  voice now reads as `lecturer (am_michael)` — the parenthetical is the voice it
  resolves to on the active engine, greyed in the dropdown — and updates when you
  switch engines. The picker also always offers an explicit **default** option
  (labelled with the deck default, e.g. `default (lecturer)`), selected when an
  utterance has no voice of its own.
- **Editing an utterance reclaims its old local audio automatically.** When you
  change a slide's text or pinned voice, the now-orphaned local clip (Kokoro —
  cheap to regenerate) is pruned the moment the edit saves, so the cache stays in
  step with the deck. Paid audio (Inworld) is never auto-pruned, and renders are
  untouched.
- **The Voices dialog picks each engine's voice from a list.** Mapping a named
  voice per engine is now a pick-or-type combobox for engines with a fixed voice
  set (Kokoro's voices, Qwen3's CustomVoice speakers) instead of free text, and a
  new voice's fields start at each engine's default. Inworld (account-specific
  ids) stays free text. Pick a voice from the list or type a custom one.
- **Play is cancellable while it waits on generation.** Pressing play on a slide
  whose audio isn't ready shows a spinner while the clips render; that wait is now
  cancellable — **Stop** aborts it immediately (instead of only taking effect once
  synthesis finished), pressing a different play button supersedes it, and
  navigating off a single-slide build cancels the wait. In every case the queued
  audio keeps generating in the background, so you can move to an already-generated
  slide and play it right away.
- **Cancel all generation from the progress bar.** A small ✕ beside the
  generation progress bar drops every queued clip and stops the running one at
  once (the running clip on an engine that can't abort mid-clip finishes its
  current file into the cache — harmless).
- **Generation progress is now visible.** While clips render in the background the
  editor shows a deck-wide count bar (e.g. "Generating 4/12"), a live elapsed/estimate
  line for the clip in flight ("intro · 12s of ~18s"), and a thin estimated
  within-clip bar; finished clips show their audio length and file size in the
  per-utterance tooltip. All driven by the generation queue, so it reflects the
  prioritized order.
- **Auto-generate while editing now works for Qwen3, with a smart queue.** The
  background generation queue picks the *best-next* clip — the slide you're on,
  then ahead by nearness, then behind — and re-prioritizes for free as you
  navigate (the pick is made when the worker frees up, against where you are
  then). Free-but-slow engines (Qwen3) are no longer locked out of
  "Auto-generate as I edit"; only *paid* engines stay gated (they'd bill on every
  save). Pressing **play** on a slide whose audio isn't ready preempts a heavy
  clip generating for another slide — it aborts mid-generation (cooperative
  cancel) and re-queues, so the worker makes what you need now; the engine warms
  on switch so the first clip doesn't stall.
- **Qwen3 ships with ready-to-use voices.** The Qwen3 engine now defaults to the
  **CustomVoice** model, which carries nine built-in speakers (Vivian, Serena,
  Uncle_Fu, Dylan, Eric, Ryan, Aiden, Ono_Anna, Sohee) — so Qwen3 narrates out of
  the box with no voice-clone prompt to prepare. The speakers appear in the
  editor's voice picker, and **Dylan** is the default. The own-voice clone path
  is still there: point `[tts.qwen3] model` at a `…-Base` repo and set a `.pt`
  `voice_prompt` (or map a `.pt` per voice) to clone instead.

- **Edit the voice map in the editor.** A new **Voices…** dialog in the editor
  console lets you create and edit the deck's named voices without hand-editing
  the narration file: each row is an internal name mapped to a concrete voice per
  engine (a Kokoro voice, an Inworld voice name, or a Qwen3 `.pt` path), with a
  **Default voice** picker. Saving writes a well-formed `voices:`/`default-voice:`
  preamble (a Qwen3 `.pt` is stored relative to the deck, as on load), and the
  voice pickers, the unset-voice placeholder, and the `voice-unmapped` warnings
  all relight against the new map — so mapping a name for the active engine clears
  its warning in place. A deck whose map you don't touch still round-trips
  byte-stable (only an actual edit regenerates the preamble).
- **Portable voice layer — internal voice names, cross-engine map in the
  narration file.** The sidecar gained an optional deck-level preamble: a
  `voices:` block mapping an internal name (`lecturer`, `guest`) to a concrete
  per-engine voice (`lecturer: {kokoro: am_michael, inworld: <id>, qwen3:
  voice/lecturer.pt}`), plus a top-level `default-voice:`. An utterance's
  `voice:` now names one of *your* internal names; with none it uses
  `default-voice`, with neither the engine default — so switching the active
  engine renarrates the same script with **zero** sidecar edits, and the
  `.narration` is self-contained (the voice definitions travel with it). The
  editor's voice picker shows internal names first (engine voices follow as an
  advanced affordance) and the unset-voice placeholder shows the deck default.
  A `slidesonnet.toml` `[voices.NAME]` library still works as a shared fallback,
  and a sidecar entry wins over a toml entry of the same name. Both `slidesonnet
  check` and the editor warn when a named voice has no mapping for the active
  engine (rather than silently using the engine default) — in the editor the
  warning lights the slide that uses the voice and follows the engine picker, so
  switching to an engine the voice doesn't cover flags it live. Files declaring
  the new preamble bump the `# slidesonnet-format:` header to 2; v1 files (no
  preamble) parse and round-trip byte-identically.
- **Pick the generation engine in the editor.** A new **Engine** dropdown in the
  editor console switches which TTS backend generates audio — Kokoro, Qwen3, or a
  cloud engine — for the current session, without touching `slidesonnet.toml` or
  the (engine-agnostic) `.narration` sidecar. The choice routes per-utterance
  generate, "Generate missing", preview, and export; the paid-confirm and
  auto-generate gates, the voice picker, and the per-slide audio badges all follow
  the picked engine. The dropdown offers only the engines whose package is
  installed (plus whatever's active). The pick is **session-only** — it's never
  written to disk, so the deck stays portable and relaunching returns to the
  default (Kokoro).
- **Qwen3-TTS local engine (own-voice narration).** A new `--engine qwen3`
  backend (the `[qwen3]` extra) narrates a deck in a cloned voice from a local
  `.pt` voice-clone prompt — the expressive / own-voice path Kokoro can't do.
  It's free local audio (`.wav`, content-addressed cache like Kokoro) that runs
  on CPU/CUDA/Intel XPU; configure it under `[tts.qwen3]` (`model`, `device`,
  `voice_prompt`, `language`). The model loads lazily and stays warm across
  clips, writes are atomic, and a missing package / missing prompt / no-audio
  result each surface a clean error. Because generation is well below real-time,
  the engine is marked non-realtime: the editor's **"Auto-generate as I edit"**
  is disabled for it (free, but too slow to fire on every edit — distinct from
  the paid-engine "would bill" reason), and `slidesonnet doctor` now reports
  Qwen3 alongside Kokoro and Inworld. Qwen3 reaches its `.pt` voice through
  the portable voice map — a `qwen3:` voice resolves to a clone-prompt path
  (relative to the deck dir), so the same script narrates under Kokoro or Qwen3
  by name alone — and the multi-GB model is cached process-wide so it loads once
  rather than per clip; the editor shows a distinct "Loading the voice model…"
  status before that first generation. (The DashScope cloud mode is tracked
  separately on the roadmap.)
- **Slide transition gallery.** `transition-out`/`transition-in` grew from
  `cut`/`crossfade` to FFmpeg's full `xfade` set, organized as a curated picker:
  pick a **Type** (Fade, Fade through black, Fade through white, Dissolve, Wipe,
  Slide, Cover, Reveal, Circle) and, where it applies, a **Direction**
  (Left/Right/Up/Down, or Open/Close). The editor renders an in-place **preview
  morph** that approximates the chosen effect in the browser and completes exactly
  at the slide boundary, so what you preview matches the export's timing — for the
  whole-deck preview *and* a single-slide play (which shows that slide's own in/out
  transitions, against a black frame at the deck's first/last slide). On export the
  morph is *absorbed into the outgoing slide's trailing hold* — the deck's total
  duration and audio are unchanged. (`cut` is an instant hard cut, no fade;
  `crossfade` still parses, as an alias for `fade`.)
- **Background audio generation.** Generating a clip no longer freezes the
  editor — synthesis runs on a background queue while you keep typing,
  navigating, and editing. Each utterance's generate button shows a spinner
  while its clip is queued or rendering, then settles green. Two requests for
  the same clip (a double-click, or pressing play right after regenerate) share
  one job instead of synthesizing twice, and **Play** waits for any in-flight
  job for the clips it needs rather than racing it.
- **Auto-generate as you edit** (opt-in, off by default). A console checkbox
  quietly generates a slide's audio in the background after you edit it: enabling
  it fills every uncached clip except the slide you're on, and thereafter each
  edited slide is generated once its text has been stable for a couple of
  seconds (the utterance you're actively typing in is skipped until you move on).
  Local-only — with a paid cloud engine the checkbox is disabled, since an
  unattended trigger must never bill per save.

### Changed
- **The per-utterance voice picker offers named voices only.** A slide's Voice
  dropdown now lists the deck's *named* voices (defined in the Voices dialog) and
  nothing else — raw engine ids (`am_echo`, `af_heart`, …) no longer appear there,
  so an utterance references a portable name and the engine voice is resolved
  through the map (an unset voice selects the explicit **default** option). A small
  voice-over button beside the picker opens the Voices dialog to define names, and
  an explicitly-pinned id already in a sidecar still shows so it isn't lost.
- **Auto-generate starts off each session.** Opening a deck no longer restores a
  previously-persisted "Auto-generate as I edit" — it always starts off, so
  background generation is opt-in each time. Switching the generation engine also
  resets it off (the new engine's audio is all uncached). This removes a surprise
  where changing a voice with auto-generate on quietly re-cached the slides.
- **Kokoro's default voice is now `am_echo`** (was `af_heart`). A deck that relied
  on the old default and wants to keep it can pin `[tts.kokoro] voice = "af_heart"`;
  otherwise unvoiced utterances regenerate under the new default.
- **`[tts.qwen3] model` now defaults to `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`**
  (was the `-Base` clone model), so Qwen3 works without a voice-clone prompt. A
  deck that relied on the Base own-voice path must set `model` back to a `…-Base`
  repo (and keep its `.pt` `voice_prompt`).

### Removed
- **The ElevenLabs TTS backend.** Inworld is the cloud engine now — it matches
  ElevenLabs on quality at roughly a tenth of the price — so the redundant engine
  is gone: the `elevenlabs` extra, the `[tts.elevenlabs]` config block and its
  `elevenlabs_*` keys, the `--engine elevenlabs` choice, and the
  `ELEVENLABS_API_KEY` check in `slidesonnet doctor`. A deck whose
  `slidesonnet.toml` still names `backend = "elevenlabs"` or maps an `elevenlabs`
  voice must switch to `inworld`.

### Fixed
- **Changing a pause or edge-silence now takes effect on the next Play, even
  without leaving the field.** The pause/Start/End-silence number fields commit
  when you leave them, and a Play-all press could land before that — so changing a
  silence and immediately pressing Play all replayed the *old* track (the loaded
  whole-deck preview was never revoked). A play press now flushes the focused
  field first and rebuilds the preview when it changed, so what you hear always
  reflects the latest silence. A press that changed nothing still resumes in place.
- **Renaming a voice now follows through to every utterance and the deck default.**
  Renaming a named voice in the **Voices…** dialog (e.g. `lecturer` → `host`) used
  to update only the `voices:` map key — utterances that used the voice still
  referenced the old name (now resolving as *unmapped*) and the old name lingered
  in the per-utterance picker. The dialog now tracks each row's old→new identity
  and rewrites every utterance `voice:` and the `default-voice` from the old name
  to the new one before saving, so no reference is left dangling and the picker
  stops offering the gone name. (Deleting a voice is unchanged — its references are
  left to surface as unmapped, not silently rewritten.)
- **Auto-prune no longer discards expensive Qwen3 audio on an unrelated edit.**
  The silent on-edit orphan sweep deleted any *non-paid* engine's orphaned clips,
  treating "free" as "cheap to regenerate" — but a Qwen3 clip is free yet slow
  (seconds per clip on a local GPU), so editing one slide could silently throw
  away minutes of just-generated own-voice audio elsewhere in the deck. Whether
  the sweep may delete a backend's orphans is now a per-engine policy
  (`BackendSpec.auto_prune_orphans`): only real-time local audio (Kokoro) is
  reclaimed eagerly; paid audio (Inworld — would re-bill) and expensive local
  audio (Qwen3) are kept. An explicit `slidesonnet clean --keep nothing` still
  removes everything.
- **Exported decks with transitions now play on Windows.** FFmpeg's `xfade`
  renegotiates the filter-graph pixel format and emitted `yuv444p` (High 4:4:4)
  for the transition clips while the plain slide segments stayed `yuv420p` — a
  stream-copy concat then produced a non-uniform H.264 stream. ffmpeg and VLC
  tolerate the mid-stream format switch, but Windows' 4:2:0-only H.264 decoder
  rejected it at the first transition ("unsupported codec settings"): the first
  slide played, then playback died. The transition clips are now pinned to
  `yuv420p` so every segment matches. Repro test
  `test_compose_transition_clip_is_yuv420p`.
- **The paid-synth confirmation popup now names the engine you actually picked.**
  The "spending API credits" dialog read the on-disk default (`config.tts.backend`,
  still `kokoro` for most decks) while the paid gate and the synthesis itself use
  the session-selected engine — so picking Inworld in the editor and pressing
  Generate warned about *kokoro*. It now reads `active_backend`, so the warning
  names the engine that will actually run.
- **Editing the narration file externally no longer leaves a stale preview.**
  With a whole-deck (or single-slide) preview loaded, hand-editing the
  `.narration` sidecar on disk — e.g. changing a slide transition — reloaded the
  editor's fields but kept the *old* preview track: pressing play again resumed
  the stale audio and transition morph instead of rebuilding. The editor now
  revokes a loaded preview whenever the deck changes on disk, so the next play
  rebuilds from the new file.
- **API keys in `.env` now reach generation, not just `doctor`.** Only
  `slidesonnet doctor` loaded `.env`; the engines read `os.environ` directly, so
  a key sitting in `.env` was invisible to actual synthesis — a paid render or
  preview failed with "`INWORLD_API_KEY` not set" even though the key was there.
  Every synthesis path now loads `.env` first, **anchored at the deck's
  directory** (then the cwd) — so the key is found no matter where the editor or
  CLI was launched from (e.g. from `$HOME` while editing a deck whose `.env` sits
  in a tree the cwd never reaches upward). The deck-dir `.env` wins over the
  cwd's, and an exported variable still wins over both.
- **Kokoro no longer floods the terminal on load.** The two torch warnings its
  model construction always emits (an LSTM `dropout` UserWarning and a `weight_norm`
  deprecation FutureWarning) are suppressed around the pipeline build, so the
  editor's own output isn't buried. Other warnings still surface.
- **The editor's background queue looks up the cache under the *picked* engine.**
  It was keyed to the on-disk config's engine, so after switching the session
  engine (e.g. to Qwen3) "Generate missing" could report "queued 0" while the
  filmstrip showed clips missing — it was finding another engine's cached audio.
  Queue, filmstrip, and synthesis now agree on the active engine.
- **Qwen3 CustomVoice no longer crashes on a foreign voice id.** A deck whose
  `default-voice` resolved to another engine's voice (e.g. Kokoro `af_heart`) made
  Qwen3 fail with "Unsupported speakers". Unknown speakers now fall back to the
  default (Vivian) with a warning, and known speakers match case-insensitively.
- **Background generation now reports its outcome.** "Generate missing" and per-clip
  generation print `[gen]` progress to the terminal (queued count, per-clip start /
  done-with-timing, failures, cancellations) instead of failing silently.
- **A slide's "Transition in" now matches the previous slide's "Transition out".**
  The two are the same boundary, but the editor stored and showed them as
  independent fields, so they could disagree (set an outgoing wipe on one slide
  and the next slide's incoming still read "cut"). The incoming control now
  reflects the boundary with the previous slide and edits it in place (stored
  canonically on the earlier slide's outgoing transition), so the two faces stay
  identical. The first slide keeps its own incoming transition (the deck open).
- **Auto-generate now covers external changes and structural edits.** Two gaps
  left slides ungenerated with "Auto-generate as I edit" on: (1) a recompile or a
  sidecar edit from another tool didn't trigger a fill, so newly-added/changed
  slides sat un-narrated — the editor now sweeps after any external reload; and
  (2) committing a structural change (add/delete/reorder a block) flushed the
  open utterance's text but never scheduled its generation, so typing a line then
  adding a block saved the text without generating it.
- **Kokoro now writes audio atomically** (temp file + rename), so two concurrent
  generations of the same clip — or a regenerate racing a queued job — can no
  longer corrupt the cache file or expose a half-written WAV to a reader.

## [1.0.0a1] — 2026-06-15

First public alpha. The repository went public for this release.

### Fixed (editor reliability pass, June 2026)
Bugs found running slideSonnet over a real course deck:
- **A PDF/config-only refresh no longer dumps unsaved narration edits.** Typing
  in a narration field while an external recompile lands used to rebuild the
  block editor from disk and revert in-progress text; a refresh now repaints
  only the slide/diagnostics (`render_side()`) unless the sidecar itself changed
  or the current slide moved.
- **PDF updates that share a timestamp now trigger a refresh.** Change detection
  keyed on mtime alone missed same-second rebuilds (WSL/Windows-mount second
  granularity); sources are now stamped on `(mtime, size)`.
- **Editing narration mid-playback no longer replays stale audio.** Changing an
  utterance's text or director's note immediately revokes the loaded track (it
  used the non-invalidating save path before), so the next play synthesizes and
  plays the new words. A no-op blur no longer falsely stops playback.
- **Ctrl-S saves the focused field in place** without a focus loss or a browser
  Save dialog (saves via the silent path, never rebuilding the textarea).
- **"Play all" starts at the current slide,** not slide 1 — the whole-deck
  preview seeks to the current slide's cue (`#t=` fragment + audio seek) and
  reflects it in the position slider and clock.
- **"Generate missing" no longer stops unaffected playback.** It stops the
  player only when the currently-loaded track actually has clips to generate.
- **Stale slide image after a recompile is gone.** The stage image and filmstrip
  thumbnails carry a `(mtime, size)` cache-busting query, so a re-rendered (or
  renumbered, after a dropped slide) `page-N.png` is refetched instead of served
  from the browser cache.

### Fixed (June 2026 full-codebase review)
- **`slidesonnet clean --keep current`/`api` no longer deletes the cached
  audio of paced utterances.** Clean compared cache filenames computed at the
  base speed, while synthesis embeds the pace-multiplied speed — so every
  `pace: slow`/`fast` clip looked stale and was removed (re-billable on paid
  engines). Clean now derives filenames the same pace-aware way synthesis does.
- **Two decks in one directory no longer interleave render artifacts.** Render
  output moved to a per-deck `.slidesonnet/render/<deck-stem>/`; previously the
  shared `render/` mixed both decks' positionally-named files (page-0001.wav,
  seg-0001.mp4, …), corrupting previews and exports.
- **Editor actions follow a live-edited config's engine.** Generate / preview /
  export re-read the on-disk `slidesonnet.toml` backend instead of pinning the
  one loaded when the editor started.
- **Broken external edits are reported, not silently ignored.** Saving a
  `slidesonnet.toml` or sidecar with a syntax error while the editor is open
  now flashes the parse error in the footer (the last good deck stays on
  screen); before, the editor silently kept retrying and edits seemed to do
  nothing.
- ffprobe/ffmpeg failures now raise slideSonnet's `FFmpegError` (clean CLI
  message) instead of a bare `RuntimeError` traceback.

### Changed (June 2026 full-codebase review)
- **External tools run with a timeout** (10 min per invocation): a wedged
  ffmpeg/ffprobe/pdftoppm can no longer hang an export or the editor forever.
- **Sidecar format version header.** `slidesonnet init` now stamps
  `# slidesonnet-format: 1` at the top of new sidecars (a comment — older
  parsers skip it); reading a file with a *greater* version logs an upgrade
  warning instead of failing cryptically.
- **Editor performance:** page-ids are cached on the PDF's mtime (committing
  an edit no longer re-parses the whole PDF), the deck-wide audio-cache scan
  is computed once per render tick instead of three times, redundant ffprobe
  spawns per exported slide were cut, and Kokoro WAV writes use a vectorized
  numpy path (~50× faster than the old per-sample loop on long utterances).
- Internal: the TTS backend registry is now the single source for CLI
  choices, config validation, cache extensions, and clean's paid-engine set;
  the editor view was decomposed into components (`PaneLayout`,
  `PreviewPlayer`, `BlockEditor`, `OrphanTray`); editor CSS/fonts/JS moved to
  package static files; the test suite hard-fails any accidental real
  ElevenLabs API call.

### Removed (June 2026 full-codebase review)
- The unused `pad_seconds` video-config knob (parsed but never affected
  output).
- The `rich` dependency (never imported).
- The `examples/basel-problem-he` Hebrew demo (pre-1.0 format, unbuildable
  since the rewrite; Hebrew support is paused).

### Added
- **Per-utterance generation.** Each utterance card has its own generate
  button that doubles as the audio indicator: amber wave = no audio yet,
  green refresh = generated (click again for a fresh take). It synthesizes
  just that line and stays in sync as you edit. The per-slide generate
  button in the transport is gone; the console button is now **"Generate
  missing (N)"** — it shows exactly how many clips a click will make,
  disables as "All audio generated" when there's nothing to do, and never
  re-makes (or re-bills) existing audio. Filmstrip thumbs wear a small
  amber audio badge while a slide still has ungenerated speech (the
  colored dot remains the diagnostics light).
- **Stage divider.** A draggable splitter between the slide image and the
  narration cards apportions the stage vertically (20–85%).
- **Ctrl+S saves in place** from any narration field (utterance text,
  director's note, pause/crossfade seconds) without leaving the field.
- **Footer status flash replaces popup pills.** All editor messages
  ("Preview ready", "Synthesized…", errors) now glide through a
  color-coded footer area that fades after a few seconds (warnings and
  errors linger longer) — nothing pops over the transport or steals
  clicks anymore.
- The voice box shows the deck default (e.g. "af_heart (default)") as a
  placeholder when an utterance has no explicit voice, with a stacked
  label so the field name doesn't overlay it.

### Fixed
- **Misplaced keys in `slidesonnet.toml` no longer vanish silently.** A
  top-level key written below a `[table]` header (TOML scopes it to that
  table) now logs a warning naming the key and the fix. Both bundled demos
  had `pronunciation = [...]` below a `[voices.*]` header — their
  pronunciation dictionaries (Euler, slideSonnet, id, …) had never actually
  loaded; a test now guards the example configs.
- **Saving no longer destroys hand-edited sidecar formatting.** The parser
  now remembers each block's raw text, and a save rewrites only blocks whose
  content actually changed — `#` comments, blank lines, and hand-wrapped
  narration survive untouched. Comments above an edited block (and trailing
  end-of-file comments) are kept even when that block is rewritten. Wrapped
  `text:` lines now parse: after a `text:` line, any line that isn't a known
  directive continues the text.
- **Audio-changing actions reset the preview player.** Re-generating,
  adding/deleting/reordering cards, and editing pause length, voice, pace,
  or transitions now stop and rewind a rolling preview — previously the
  stale track kept playing and replay *resumed* it, so e.g. a longer pause
  was never heard no matter how often you replayed.
- The autosave "saved" flash no longer logs an error when the save was
  triggered from a card that got rebuilt before the flash faded.
- **Structured narration: attributed utterances, pauses, and transitions.**
  A slide's narration is now an ordered list of *utterance* and *pause*
  blocks. Each utterance carries its own `voice`, `pace`, and free-text
  `direct` (director's note); a slide can mix voices — each utterance is its
  own synthesis call (so Kokoro renders a two-voice exchange on one slide).
  `direct` is stored and serialized for forward compatibility (the local
  engine ignores it). Each slide also has `transition-in`/`transition-out`
  (default `cut`, or a timed `crossfade`).
- **Block editor.** The single narration textarea is replaced by a card list:
  "Line" and "Pause" buttons add blocks; each utterance card has a growing
  text area with a one-line, labelled voice / pace / director's-note strip
  (bordered fields). **Voice** is a dropdown of the engine's actual voices
  (Kokoro's English set, plus any named presets from `slidesonnet.toml`);
  clear it for the deck default. A per-utterance voice that isn't a named
  preset is now passed straight to the backend as a raw voice id, so the
  picker's choices take effect. Pace is a compact select; cards reorder and
  delete; pause cards edit their duration; transition rows bracket the slide.
- **Unattached-narration tray.** When a recompile (or a duplicate `@id`) drops
  a narration block, it lands in a distinct, highlighted tray instead of
  vanishing: the full text is shown and selectable, with one-click **copy**,
  **Append here** (fold it onto the open slide), **Attach to…** (move it onto
  an empty slide), and **Delete**.
- Editor usability: single-slide preview button (was deck-only), ←/→
  keyboard navigation, autosave "saved" flash, and an engine/sidecar
  status footer.
- **Live reload of deck sources.** The editor watches the PDF, the
  `.narration` sidecar, and `slidesonnet.toml` (1s mtime poll — reliable on
  WSL mounts) and reloads automatically: recompile your deck or edit the
  sidecar in another editor and the filmstrip, thumbnails, diagnostics, and
  config refresh in place. The editor's own saves don't trigger it.
- Resizable, collapsible side panels: drag the dividers (grip handles) to
  resize the filmstrip and console, collapse them via in-panel chevrons or
  the persistent header toggles (which remember the dragged width). On
  narrow windows both panels auto-collapse, and reopening one floats it
  over the stage instead of squeezing it.
- The narration pane now matches the slide's aspect ratio (read from the
  PDF), keeping comfortable line lengths instead of spanning the window.
- `slidesonnet edit --dev`: auto-restart the editor when slideSonnet's own
  source changes (for hacking on slideSonnet itself).
- Per-deck `.latexmkrc` in the example decks routes LaTeX intermediates to
  a `.build/` subfolder, keeping deck directories clean.
- ↑/↓ now navigate slides too, matching the vertical filmstrip (←/→ still
  work).

- `examples/error-showcase`: a deliberately broken deck with every
  reconciliation problem on its own slide (auto id, un-narrated, duplicate
  ids, duplicate sidecar blocks, orphan narration) — open it in the editor
  to see how each one surfaces. Guarded by tests so it stays broken in
  exactly the advertised ways.

### Changed (narration file format)
- **The `.narration` sidecar grammar is now an indented block format** (a
  breaking change). Each slide is `@id` followed by `utterance:` blocks (with
  `voice:`/`pace:`/`direct:`/`text:` lines), `pause: N` lines, and optional
  `transition-in:`/`transition-out:` lines. The old flat `:voice`/`:pace` +
  inline-`[pause]` body grammar is gone; the bundled example decks are
  migrated. A new `transition-conflict` check (warning) fires when a slide's
  `transition-out` disagrees with the next slide's `transition-in`; the
  earlier slide's transition wins, and the editor clears the next slide's
  `transition-in` when you set an outgoing one, so a boundary is only ever
  written on one side.

### Changed (reconciliation)
- Duplicate slide-ids are no longer a hard error: when the same `\ssid`
  appears on several pages, later occurrences are auto-renamed (`twin`,
  `twin-2`, …) with a warning, so every page stays addressable and
  narratable. The suffix always skips ids that genuinely exist (a real
  `twin-2` elsewhere makes the duplicate become `twin-3`), so renames can
  never collide. Note the renamed binding follows occurrence order — it
  shifts if the duplicate pages reorder, which is why the warning still
  tells you to give each page its own `\ssid`. Duplicate *narration blocks*
  are handled the same way: a repeated `@id` in the sidecar is auto-renamed
  on load (`double-block` → `double-block-2`) so neither block's text is
  lost, with a warning, and the renamed block surfaces in the
  unattached-narration tray — no more frozen saving.

### Fixed
- Typing narration on a page with no slide-id no longer corrupts the
  sidecar (it wrote an unparseable "@" block). The editor disables the
  narration pane on unmarked pages and shows the missing-\ssid warning on
  the page itself.
- Browsing a deck whose sidecar has duplicate blocks no longer silently
  collapses them (navigation auto-saves were dropping all but the last
  duplicate's text). The later block is auto-renamed on load so its text is
  kept, and editing the rest of the deck is never frozen by a duplicate
  elsewhere in the file.
- Saving no longer scaffolds bare `@id` headers for un-narrated pages. An
  empty placeholder block used to read back as a (narrated-but-empty) block
  and silence the page's `missing-narration` warning; un-narrated pages now
  stay out of the sidecar until they get real content.
- Pressing play on a slide with no narration now says so instead of
  rendering and playing a silent track.
- Recompiling a deck no longer risks killing the editor's live-reload: a
  poll tick that catches the PDF (or `slidesonnet.toml`) missing or
  half-written keeps showing the last good deck and retries next tick.
- Preview playback got defined behaviors: Stop now cancels a preview even
  while its track is still being built (it used to start playing anyway),
  starting a new preview immediately silences the rolling one, switching
  slides during a single-slide preview stops its audio (it used to keep
  talking over the new slide), and the deck preview's automatic page flips
  no longer discard narration you typed during playback.
- Replaying a preview after navigating now plays the new slide's audio:
  previews render to one track file, and the browser kept replaying the
  old audio because the URL never changed (now cache-busted per request).

### Changed (editor transport)
- "Generate" moved into the transport bar next to play (icon button); play
  and generate now gray out when pointless — play when the slide has no
  speech, generate when every segment is already cached. "Generate all"
  stays in the console for whole-deck synthesis.
- One transport, no duplicate players: the native browser audio widget is
  gone (it offered a second, stale play button). The play-slide /
  play-deck buttons now toggle play/pause for their own track (icon
  flips), Stop resets the player, and switching slides clears a
  single-slide preview (even one still building) while deck previews
  seek to the new slide — playing or paused. A seek bar + elapsed/total
  clock in the transport replaces the widget's scrubber (drag to jump
  anywhere in the track).

### Changed
- **Python 3.13+ is now required** (was 3.12+). CI only ever tested 3.13;
  the package metadata now says what's actually verified.
- **Kokoro replaces Piper as the local TTS engine.** The default backend is
  now [Kokoro 82M](https://github.com/hexgrad/kokoro) (Apache-2.0): clearly
  more natural speech than Piper while still ~2x real-time on CPU. Configure
  with `[tts.kokoro]` (`voice`, `speed`); voices are named like `af_heart` /
  `am_michael` / `bm_george`. Install via the `[kokoro]` extra; the model
  (~330 MB) auto-downloads from the Hugging Face hub on first use.
- **Editor redesign** (`slidesonnet edit`): dark "recording studio" theme
  (warm charcoal + amber, IBM Plex Mono / Bricolage Grotesque) and a
  three-pane layout — clickable filmstrip with per-slide status dots
  (error / warning / narrated / empty), a letterboxed slide stage with a
  transport bar, and a narration console with sectioned controls.
- Editor actions (generate / preview / export) now run off the event loop
  with button spinners instead of freezing the UI, and won't double-run
  while one is in flight.

### Removed
- **Piper TTS backend.** `--engine piper`, the `[piper]` extra, `[tts.piper]`
  config, and `piper_model`/`piper_speed` are gone. Cached Piper audio is no
  longer referenced (clean it with `slidesonnet clean`).

## [1.0.0a0] — 2026-06-09

A ground-up rewrite. slideSonnet is now a **PDF + narration sidecar editor**
rather than a source→video compile pipeline.

### Added
- **PDF-first workflow.** Work from a finished PDF; narration lives in a
  human-readable, git-diffable `<deck>.narration` sidecar keyed to slides by
  stable ids.
- **`\ssid` LaTeX macro** (`slidesonnet.sty`, written by `slidesonnet sty`) that
  stamps an invisible, per-page slide-id (overlay-step aware: `\ssid<2>{...}`)
  into the PDF text layer; unnamed pages get an `auto-…` default + warning.
- **Sidecar grammar:** `@slide-id` blocks, `:voice`/`:pace` directives, and
  `[pause N]` as the single timing primitive (mid-pause / end-hold / silent
  slide). Round-trip stable.
- **NiceGUI editor** (`slidesonnet edit`): page nav, narration editing,
  per-slide TTS, diagnostics panel, and a whole-deck preview that bakes in
  silences and flips the slide on cue — sample-accurate to the export.
- **id-only reconciliation** (`slidesonnet check`): duplicate / auto / missing /
  orphan / order diagnostics; exits non-zero on errors.
- **CLI:** `sty`, `init` (`--merge`/`--force`), `check`, `tts`, `export`
  (`--silent`, `--timing tts|estimate|fixed:N`, `--subtitles`,
  `--sub-granularity`), `subs`, `edit`, `clean`, `doctor`.
- **Timing model:** real-audio / WPM-estimate / fixed-seconds; silent renders.
- **Subtitles:** SRT **and** WebVTT, per-segment or per-slide granularity.
- **Typed Python API** (`slidesonnet.api`) mirroring every CLI operation.
- **TOML config** (`slidesonnet.toml`, optional) for engine, voices, video, and
  pronunciation.
- Demos rebuilt in the new format: `basel-problem` and a self-narrated
  `showcase` (both Beamer + sidecar, rendered with Piper).

### Changed
- Audio cache moved to `<deck-dir>/.slidesonnet/`; still content-addressed, so
  editing one block re-synthesizes only that block.
- `doctor` checks the new toolchain (PyMuPDF, NiceGUI, pdftoppm); dependencies
  add **PyMuPDF** + **NiceGUI**, drop **doit**, **playwright**, **PyYAML**.

### Removed
- **Breaking:** the MARP/Beamer source parsers, the doit build graph, playlists,
  inline `<!-- say: -->` / `\say{}` narration, and the multi-module concat
  pipeline. The tool no longer compiles slides — you bring the PDF.

## [0.2.0] — 2026-06-09

### Added
- Beamer `\say<N>{}` overlay-step syntax mirroring beamer's own overlay specs (`\onslide<N>`, `\item<N->`); options go in `\say<N>[voice=…, pace=…]{}`

### Changed
- Beamer decks now compile with `latexmk` (runs the engine to convergence) instead of a fixed two-pass `pdflatex`; honors a deck's `.latexmkrc` while forcing output into the cache. `slidesonnet doctor` now checks for `latexmk`.
- Beamer overlay-step counts are read from beamer's compiled `.nav` (`\beamer@framepages`), so **every** overlay mechanism — `\onslide<>`, `\item<>`, `+`/`.`, not just `\pause` — produces correctly aligned video segments

### Removed
- **Breaking:** Beamer `\say` now *requires* an overlay step. A bare `\say{}` is rejected, and the legacy `\say[N]` / `\say[slide=N]` bracket-number forms are no longer supported — use `\say<N>{}` (brackets are for `voice`/`pace` only)

## [0.1.0a1] — 2026-04-21

### Added
- Showcase example rewritten from scratch — covers subtitles, dry-run, preview, utterances, auto-discovery, pronunciation, voice presets, fragment animation, and more
- Default config renamed to `slidesonnet.yaml` (auto-discovered in cwd; `lecture.yaml` fallback)
- `output:` config field and `--output` / `-o` CLI flag for custom video naming
- Output video defaults to directory name (e.g., `my-lecture/` produces `my-lecture.mp4`)
- `slidesonnet pdf` now produces a single concatenated PDF via `pdfunite`
- PLAYLIST argument is now optional on all commands (auto-discovers config in cwd)
- `slidesonnet doctor` checks for `pdfunite`
- SRT subtitle generation — every build produces a `.srt` file alongside the video
- `slidesonnet subtitles` command to regenerate SRT from cached audio
- `slidesonnet doctor` command to check external dependencies
- `slidesonnet list` command with per-slide cache status
- `slidesonnet utterances` command to export narration text for proofreading
- `slidesonnet preview` for fast low-res builds (skips crossfade, Piper TTS)
- `slidesonnet preview-slide` for single-slide audio preview
- `--dry-run` flag with API cost estimation
- `--no-srt` flag to skip subtitle generation
- Per-backend pronunciation dictionaries (shared + piper/elevenlabs overrides)
- Voice presets with per-backend voice ID mapping
- Optional duration parameter for `\nonarration` / `<!-- nonarration(5) -->`
- Video passthrough modules (.mp4, .mkv, .webm, .mov)
- Crossfade transitions between slides
- Annotation-aware image caching for faster preview builds
- Rich progress bars with cached/built counts
- Graduated `slidesonnet clean --keep` levels (api, current, nothing)
- Hebrew pronunciation tests documenting niqqud word-boundary behavior
- Adversarial edge-case tests for MARP and Beamer parsers (24 tests covering nested delimiters, escaped characters, malformed annotations, empty slides)

### Changed
- Example videos moved from Git LFS to GitHub Releases (`v0.0.0`); MP4 files no longer tracked in repo
- Default config file renamed from `lecture.yaml` to `slidesonnet.yaml` (`slidesonnet init` creates the new name; `lecture.yaml` auto-discovered as fallback)
- `slidesonnet pdf` now produces a single concatenated PDF instead of per-module PDFs
- Per-module PDFs generated into cache directory (fixes collision bug with same-named modules)
- Playlist format migrated from Markdown with YAML front matter to pure `.yaml`
- `init` command simplified: positional format argument, dropped `--from`
- `utterances` command renamed to `list`
- `--keep utterances` renamed to `--keep current`
- `--rebuild` flag removed
- `\silent` / `<!-- silent -->` renamed to `\nonarration` / `<!-- nonarration -->`

### Fixed
- `--quiet` / `-q` flag now suppresses output from `init` and `clean` commands (previously only `build` and `preview` respected it)
- Quadratic regex backtracking in MARP `_SAY_RE` pattern
- Fence detection tracks fence type and length per CommonMark spec
- LaTeX `%` line comments correctly skipped in brace extraction
- Piper `speaker=0` falsy check
- Playwright browser leak on error paths
- pdflatex runs twice to resolve cross-references
- `.env` loaded before TTS engine creation in `clean --keep`
- Duplicate log handlers on repeated CLI invocations
- Video config changes tracked in compose and assemble tasks
- 21 CLI UX issues (error messages, help text, output formatting, consistency)

