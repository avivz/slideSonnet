# Changelog

All notable changes to slideSonnet will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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

## [0.1.0] — Unreleased

Initial alpha. Core pipeline working for MARP Markdown and LaTeX Beamer inputs with Piper (local) and ElevenLabs (cloud) TTS backends.
