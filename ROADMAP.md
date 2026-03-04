# Roadmap

Current version: 0.1.0 (alpha, unreleased)

## Now — blocking release

1. **First PyPI release** — Tag v0.1.0a1 and publish to TestPyPI, then PyPI. The README advertises `uv tool install slidesonnet[piper]` but the package doesn't exist yet. Validates the entire install story.

2. **Partial-build CLI options** — Let users run just parts of the pipeline (just TTS, just images, just utterance text export). Review CLI surface to avoid overcomplicating things. The `--until` flag exists but may not cover all use cases.

## Next — before beta

5. **`--output` flag** — Build to a custom filename/path (cache stays near sources). Document in README.

6. **ElevenLabs expressiveness** — Extra emotion and expressiveness parameters for ElevenLabs audio generation.

7. **Overhaul showcase example** — The showcase is outdated. Update to demonstrate all current features (subtitles, pronunciation, voice presets, skip, nonarration durations).

8. **Integration tests in CI** — Install ffmpeg + Piper in CI and run at least one end-to-end build. Currently only unit tests run in CI.

9. **Test coverage audit** — Identify missing and redundant tests. Ensure all CLI commands have test coverage.

10. **Code review** — Audit for dead code, duplicated logic, fragile patterns. The parsing regex and annotation stripping logic appear in multiple places.

11. **Documentation review** — Ensure README, `docs/marp.md`, `docs/beamer.md`, and `--help` text are all consistent and complete.

12. **Design a logo** — Needed for GitHub repo, PyPI page, project website, and YouTube branding. Do before public launch.

13. **Remove large files from git history** — The repo has ~54 MB of tracked media (3 lecture MP4s, ~48 ElevenLabs audio cache files) plus historical copies inflating `.git/` to 123 MB. MP4s are build artifacts and should be gitignored. ElevenLabs audio caches cost real money to regenerate — move them to a separate storage mechanism (Git LFS, a release artifact, or a shared cache outside the repo). Use `git filter-repo` or BFG to purge historical blobs. Do before first public release / PyPI publish.

## Later — backlog

13. **Hebrew TTS** — Research is done (see `dev/hebrew-tts-research.md`). LightBlue Piper+Phonikud is the most promising local path. Cartesia Sonic-3 for cloud. Requires a new backend module.

14. **Watch mode** — `slidesonnet watch slides.md 3 -p lecture.yaml` to auto-rebuild on file save. Adds watchdog dependency.

15. **Pronunciation correction workflow** — Interactive tooling for iterating on pronunciation dictionaries.

16. **Basel problem example finalization** — Finalize the sample lesson. Add Hebrew subtitle translation as a demo.

17. **`--json` output** — Machine-readable output for CI/automation.

18. **`--quiet` mode** — Suppress non-error output for scripting.

19. **Additional TTS backends** — Cartesia, Google Cloud TTS, Azure Speech. Each follows the existing backend pattern.

20. **Code tutorial presentation mode** — A slide format for teaching programming: syntax-highlighted code that evolves across slides (lines added, removed, modified), shell commands being typed, program output, and GUI screenshots. Narrated programming tutorials from text source files — no screen recording needed. Needs design: source format, diff specification, shell session description.

## Done (pre-release)

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
- [x] CLI UX polish (two passes)
- [x] Adversarial parser edge-case tests (nested braces, escaped delimiters, malformed annotations, empty slides)
- [x] Cache-only default mode with `--allow-api` preflight check
