# Changelog

All notable changes to slideSonnet will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed
- **Kokoro replaces Piper as the local TTS engine.** The default backend is
  now [Kokoro 82M](https://github.com/hexgrad/kokoro) (Apache-2.0): clearly
  more natural speech than Piper while still ~2x real-time on CPU. Configure
  with `[tts.kokoro]` (`voice`, `speed`); voices are named like `af_heart` /
  `am_michael` / `bm_george`. Install via the `[kokoro]` extra; the model
  (~330 MB) auto-downloads from the Hugging Face hub on first use.

### Removed
- **Piper TTS backend.** `--engine piper`, the `[piper]` extra, `[tts.piper]`
  config, and `piper_model`/`piper_speed` are gone. Cached Piper audio is no
  longer referenced (clean it with `slidesonnet clean`).
- **Editor redesign** (`slidesonnet edit`): dark "recording studio" theme
  (warm charcoal + amber, IBM Plex Mono / Bricolage Grotesque) and a
  three-pane layout — clickable filmstrip with per-slide status dots
  (error / warning / narrated / empty), a letterboxed slide stage with a
  transport bar, and a narration console with sectioned controls.
- Editor usability: single-slide preview button (was deck-only), ←/→
  keyboard navigation, autosave "saved" flash, engine/sidecar status footer,
  and pace as a one-click toggle instead of a dropdown.
- Editor actions (generate / preview / export) now run off the event loop
  with button spinners instead of freezing the UI, and won't double-run
  while one is in flight.

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

