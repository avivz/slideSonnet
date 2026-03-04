# Roadmap

Current version: 0.1.0 (alpha)

## Now — ship first release

1. **Tag and publish v0.1.0a1** — CI publish workflow is ready (`publish.yml`). Remaining steps: set version to `0.1.0a1` in `__init__.py`, cut CHANGELOG, configure `TEST_PYPI_API_TOKEN` and `PYPI_API_TOKEN` secrets in GitHub, then `git tag v0.1.0a1 && git push origin v0.1.0a1`. Verify install from PyPI afterward.

3. **Remove large files from git history** — ~54 MB tracked media inflating `.git/` to 123 MB. Use `git filter-repo` or BFG to purge before promoting the repo publicly. MP4s should be gitignored; ElevenLabs caches need alternate storage (LFS or external).

4. **Partial-build CLI options** — Let users run just parts of the pipeline (just TTS, just images, just utterance text export). The `--until` flag exists but may not cover all use cases.

## Next — before beta

1. **`--output` flag** — Build to a custom filename/path (cache stays near sources). Document in README.

2. **Integration tests in CI** — Install ffmpeg + Piper in CI and run at least one end-to-end build. Currently only unit tests run in CI.

3. **Overhaul showcase example** — The showcase is outdated. Update to demonstrate all current features (subtitles, pronunciation, voice presets, skip, nonarration durations).

4. **ElevenLabs expressiveness** — Extra emotion and expressiveness parameters for ElevenLabs audio generation.

5. **Test coverage audit** — Identify missing and redundant tests. Ensure all CLI commands have test coverage.

6. **Code review** — Audit for dead code, duplicated logic, fragile patterns. The parsing regex and annotation stripping logic appear in multiple places.

7. **Documentation review** — Ensure README, `docs/marp.md`, `docs/beamer.md`, and `--help` text are all consistent and complete.

8. **Design a logo** — Needed for GitHub repo, PyPI page, project website, and YouTube branding. Do before public launch.

## Later — backlog

1. **Hebrew TTS** — Research is done (see `dev/hebrew-tts-research.md`). LightBlue Piper+Phonikud is the most promising local path. Cartesia Sonic-3 for cloud. Requires a new backend module.

2. **Watch mode** — `slidesonnet watch slides.md 3 -p lecture.yaml` to auto-rebuild on file save. Adds watchdog dependency.

3. **Pronunciation correction workflow** — Interactive tooling for iterating on pronunciation dictionaries.

4. **Basel problem example finalization** — Finalize the sample lesson. Add Hebrew subtitle translation as a demo.

5. **`--json` output** — Machine-readable output for CI/automation.

6. **`--quiet` mode** — Suppress non-error output for scripting.

7. **Additional TTS backends** — Cartesia, Google Cloud TTS, Azure Speech. Each follows the existing backend pattern.

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
