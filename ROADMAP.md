# Roadmap

Current version: 0.1.0 (alpha)

## Now — ship alpha

### Pre-alpha consistency checklist

Version & metadata:
- [ ] `__version__` in `src/slidesonnet/__init__.py` set to `"0.1.0a1"`
- [ ] `CHANGELOG.md`: move `[Unreleased]` content into `[0.1.0a1] — <date>`, leave `[Unreleased]` empty
- [ ] `CHANGELOG.md`: remove or merge the stub `[0.1.0] — Unreleased` entry at the bottom
- [ ] `ROADMAP.md` header matches version (`0.1.0a1`)
- [ ] `pyproject.toml` classifier is `Development Status :: 3 - Alpha`

README & docs:
- [ ] `README.md` installation section says `pip install slidesonnet` (matches PyPI name)
- [ ] `README.md` feature list matches Done items in ROADMAP and CHANGELOG Added section
- [ ] `README.md` CLI command table matches actual `slidesonnet --help` output
- [ ] `README.md` YouTube video links are live and correct
- [ ] `docs/marp.md` annotation syntax matches what the parser actually accepts
- [ ] `docs/beamer.md` annotation syntax matches what the parser actually accepts
- [ ] CLI `--help` text for every command is accurate (run `slidesonnet <cmd> --help` for each)

Build & packaging:
- [ ] `pyproject.toml` entry point `slidesonnet = "slidesonnet.cli:main"` works after `pip install .`
- [ ] `pyproject.toml` project URLs point to correct GitHub repo
- [ ] `pyproject.toml` dependencies are complete (no missing runtime deps)
- [ ] `pyproject.toml` optional extras (`piper`, `elevenlabs`, `dev`) install cleanly
- [ ] `LICENSE` file present and referenced in `pyproject.toml`

CI & release pipeline:
- [ ] CI passes: `make lint`, `make typecheck`, `make test-unit` all green
- [ ] `publish.yml` workflow: `TEST_PYPI_API_TOKEN` secret configured in GitHub
- [ ] `publish.yml` workflow: `PYPI_API_TOKEN` secret configured in GitHub
- [ ] Integration tests pass locally: `make test` (requires ffmpeg, marp, pdflatex, piper)

Examples:
- [ ] `examples/showcase/` builds with `make showcase-piper`
- [ ] `examples/basel-problem/` builds with `make basel-piper`
- [ ] Example videos on GitHub Releases (`v0.0.0`) match current builds
- [ ] Example config files use `slidesonnet.yaml` (not old `lecture.yaml` name)

Post-tag verification:
- [ ] `git tag v0.1.0a1 && git push origin v0.1.0a1` triggers publish workflow
- [ ] Package appears on TestPyPI, then PyPI
- [ ] `pip install slidesonnet` in a fresh venv works
- [ ] `slidesonnet --version` prints `0.1.0a1`
- [ ] `slidesonnet doctor` runs in a fresh install
- [ ] GitHub Release created with correct tag and notes

## Next — before beta

### UX polish
1. **Default `init` format to `md`** — `slidesonnet init` with no FMT argument should default to `md` and print a message mentioning `slidesonnet init tex` for Beamer. Reduces first-contact friction.
2. **`preview-slide` auto-discover playlist** — Only CLI command requiring explicit `-p playlist.yaml`. Should auto-discover like every other command.
3. **`doctor` suggest next step** — After all checks pass, print "Run `slidesonnet init md` to get started." One-liner.
4. **`clean --dry-run`** — Preview what would be removed without deleting. Useful for checking stale cache.
5. **`clean` confirmation preview** — `--keep nothing` should show file counts and size before confirming (e.g., "Will remove 14 audio files, 30 images, 6 segments (23.1 MB). Continue?").
6. **`preview-slide` improvements** — (1) Support `--tts elevenlabs` to spot-check one slide with production voice. (2) Improve discoverability / usage help.

### Features
7. **Partial-build CLI options** — Let users run just parts of the pipeline (just TTS, just images). The `--until` flag exists but may not cover all use cases.
8. **ElevenLabs expressiveness** — Extra emotion and expressiveness parameters for ElevenLabs audio generation.

### Quality
9. **Test coverage audit** — Identify missing and redundant tests. Ensure all CLI commands have test coverage.
10. **Code review** — Audit for dead code, duplicated logic, fragile patterns. The parsing regex and annotation stripping logic appear in multiple places.
11. **Documentation review** — Ensure README, `docs/marp.md`, `docs/beamer.md`, and `--help` text are all consistent and complete.
12. **Design a logo** — Needed for GitHub repo, PyPI page, project website, and YouTube branding. Do before public launch.

## Later — backlog

1. **Rename `utterances` command to `narration`** — "Utterances" is TTS jargon; "narration" echoes the annotation terms users know. Breaking change — do in a minor version bump.
2. **`pdf` progress indication** — Can be slow with many Beamer modules, no feedback currently.
3. **Reorder build pipeline: TTS before compose** — Run all TTS first, then compose video. Subtitles could be generated as soon as audio is done, before video rendering finishes. Architecture change.
4. **Rethink `clean` keep levels** — Current levels nuke images/segments even when only audio changed. Consider separate clean targets or orphan-only mode.
5. **`--json` output / scriptable build path** — Machine-readable output for CI/automation. Also solves `build` not printing output path in a scriptable way.
6. **Hebrew TTS** — Research is done (see `dev/hebrew-tts-research.md`). LightBlue Piper+Phonikud is the most promising local path. Cartesia Sonic-3 for cloud. Requires a new backend module.
7. **Watch mode** — `slidesonnet watch` to auto-rebuild on file save. Adds watchdog dependency.
8. **Pronunciation correction workflow** — Interactive tooling for iterating on pronunciation dictionaries.
9. **Additional TTS backends** — Cartesia, Google Cloud TTS, Azure Speech. Each follows the existing backend pattern.
11. **Code tutorial presentation mode** — A slide format for teaching programming: syntax-highlighted code that evolves across slides (lines added, removed, modified), shell commands being typed, program output, and GUI screenshots. Narrated programming tutorials from text source files — no screen recording needed. Needs design: source format, diff specification, shell session description.

## Done

- [x] Core pipeline: parse -> TTS -> compose -> assemble (MARP + Beamer)
- [x] Incremental builds via doit with content-hash caching
- [x] Piper (local) and ElevenLabs (cloud) TTS backends
- [x] Pronunciation dictionaries (shared + per-backend)
- [x] Voice presets per TTS backend
- [x] SRT subtitle generation
- [x] `slidesonnet doctor` dependency checker
- [x] `slidesonnet init` project scaffolding (MARP + Beamer)
- [x] `slidesonnet preview` fast low-res builds
- [x] `slidesonnet preview-slide` single-slide audio preview
- [x] `slidesonnet list` with per-slide cache status
- [x] `slidesonnet clean` with graduated `--keep` levels
- [x] `--dry-run` mode with API cost estimation
- [x] Video passthrough modules (.mp4/.mkv/.webm/.mov)
- [x] Crossfade transitions between slides
- [x] CI: lint, typecheck, unit tests, wheel build + smoke test
- [x] CI publish workflow (TestPyPI → PyPI → GitHub Release)
- [x] CLI UX polish (two passes)
- [x] Adversarial parser edge-case tests
- [x] Cache-only default mode with `--allow-api` preflight check
- [x] Lower `requires-python` to `>=3.12` (no 3.13-only features used)
- [x] `slidesonnet utterances` narration text export for proofreading
- [x] Purge large files from git history; binary assets moved to Git LFS
- [x] Example videos human-approved and uploaded to GitHub Releases (v0.0.0): showcase, Basel problem (EN), Basel problem (HE)
- [x] MP4 videos removed from Git LFS; hosted on GitHub Releases instead
- [x] Basel problem example — Hebrew subtitle translation
- [x] `--output` flag and `slidesonnet.yaml` config rename with auto-discovery
- [x] `--quiet` mode covers all CLI commands (init, clean now respect `-q`)
- [x] Showcase example rewritten from scratch (covers all current features, builds with `--tts piper`)
- [x] Fix `voices.default` fallback: inherit `voices.default` piper/elevenlabs mappings into TTS engine defaults when not explicitly set in YAML
- [x] Fix ElevenLabs missing API key: early validation in `_prepare()` with actionable error message
