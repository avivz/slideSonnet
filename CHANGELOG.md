# Changelog

All notable changes to slideSonnet will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Accelerated narration playback (1× / 1.25× / 1.5× / 2×).** A speed control in
  the editor transport cycles the preview's playback rate live — pressing it
  mid-play speeds up immediately with **no re-synthesis** and no cache write. The
  chosen speed sticks across slide changes and across both *play-slide* and
  *play-all* (re-applied on every track load), the cue-driven slide flips and the
  transition morph stay locked to the faster audio clock, and pitch is preserved
  (2× stays natural, not chipmunked). Preview-only: it never touches the
  synthesized cache, the per-utterance `pace:` directive, or the exported video.
  This is HTML5 `audio.playbackRate` on the transport player, distinct from
  `pace:` (which re-synthesizes).
- **Toggle for transitions in single-slide preview.** A new editor checkbox,
  **"Play transitions in single-slide preview"** (off by default), gates the
  single-slide morph: unchecked, playing one slide is a plain cut so you just hear
  its narration; checked, it animates that slide's own in/out transitions as
  before. The whole-deck preview always plays transitions, unaffected. The setting
  is local editor state (off each session), never written to the deck.

### Changed
- **Default Inworld model is now `inworld-tts-2`** (was `inworld-tts-1.5-max`).
  Override per deck with `[tts.inworld] model` in `slidesonnet.toml`. Note: the
  model is part of the audio cache key, so existing Inworld clips re-synthesize on
  next generate under the new default.
- **A narration edit marks its clip stale immediately.** Typing in an utterance
  now flips that clip's generate badge to "not generated yet" (amber) within a
  keystroke — before you blur or save — so you can see at a glance that the cached
  audio no longer matches the text; undoing back to the original text restores the
  green "up to date" badge without a save.

### Fixed
- **Subtitles no longer drift late on Inworld (MP3) renders.** An MP3 carries
  encoder delay + end padding, so its container `format.duration` over-reports the
  true decoded length by ~tens of ms per clip — and the subtitle timeline, built
  from those per-clip durations, slid progressively later (≈1–2 s behind by the end
  of a long deck) while the assembled audio track (which decodes the clips) did not.
  `get_duration` now measures the *decoded* length for compressed audio-only clips
  (MP3/AAC/…) by decoding to PCM, exactly as `concatenate_audio` does, so per-clip
  durations sum to the assembled track and the cues stay locked to the speech.
  WAV (Kokoro/Qwen3) was always sample-exact and is unaffected (it keeps the cheap
  header read), as is the muxed video. The fix applies to already-cached `.mp3`
  audio too — no re-synthesis or re-billing. Repro test
  `tests/test_subtitle_drift.py` (free — libmp3lame tones, no Inworld call).

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

