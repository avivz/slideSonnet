# Roadmap

Current version: 0.1.0 (alpha)

## Now — ship first release

1. **Finalize and record Basel problem example** — Polish the existing Basel problem lesson into a publishable state. Must build from `examples/` with `--tts piper`. Human approves the final video. Upload to YouTube. **Blocks v0.1.0a1.**

2. **Tag and publish v0.1.0a1** — Blocked by Basel video. CI publish workflow is ready (`publish.yml`). Remaining steps: set version to `0.1.0a1` in `__init__.py`, cut CHANGELOG, configure `TEST_PYPI_API_TOKEN` and `PYPI_API_TOKEN` secrets in GitHub, then `git tag v0.1.0a1 && git push origin v0.1.0a1`. Verify install from PyPI afterward.

## Next — before beta

1. **Default `init` format to `md`** — `slidesonnet init` with no FMT argument should default to `md` and print a message mentioning `slidesonnet init tex` for Beamer. Reduces first-contact friction.

2. **Partial-build CLI options** — Let users run just parts of the pipeline (just TTS, just images). The `--until` flag exists but may not cover all use cases.

3. **ElevenLabs expressiveness** — Extra emotion and expressiveness parameters for ElevenLabs audio generation.

4. **Test coverage audit** — Identify missing and redundant tests. Ensure all CLI commands have test coverage.

5. **Code review** — Audit for dead code, duplicated logic, fragile patterns. The parsing regex and annotation stripping logic appear in multiple places.

6. **Documentation review** — Ensure README, `docs/marp.md`, `docs/beamer.md`, and `--help` text are all consistent and complete.

7. **Design a logo** — Needed for GitHub repo, PyPI page, project website, and YouTube branding. Do before public launch.

## Later — backlog

1. **Hebrew TTS** — Research is done (see `dev/hebrew-tts-research.md`). LightBlue Piper+Phonikud is the most promising local path. Cartesia Sonic-3 for cloud. Requires a new backend module.

2. **Watch mode** — `slidesonnet watch slides.md 3 -p slidesonnet.yaml` to auto-rebuild on file save. Adds watchdog dependency.

3. **Pronunciation correction workflow** — Interactive tooling for iterating on pronunciation dictionaries.

4. **Basel problem example — Hebrew subtitles** — Add Hebrew subtitle translation as a demo of multilingual workflows.

5. **`--json` output** — Machine-readable output for CI/automation.

6. **Additional TTS backends** — Cartesia, Google Cloud TTS, Azure Speech. Each follows the existing backend pattern.

8. **Code tutorial presentation mode** — A slide format for teaching programming: syntax-highlighted code that evolves across slides (lines added, removed, modified), shell commands being typed, program output, and GUI screenshots. Narrated programming tutorials from text source files — no screen recording needed. Needs design: source format, diff specification, shell session description.

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
- [x] `--output` flag and `slidesonnet.yaml` config rename with auto-discovery
- [x] `--quiet` mode covers all CLI commands (init, clean now respect `-q`)
- [x] Showcase example rewritten from scratch (covers all current features, builds with `--tts piper`)
