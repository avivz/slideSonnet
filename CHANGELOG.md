# Changelog

All notable changes to slideSonnet will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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

