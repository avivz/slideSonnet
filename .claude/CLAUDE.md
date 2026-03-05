# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

slideSonnet compiles text-based slide presentations (MARP Markdown or LaTeX Beamer) into narrated MP4 videos. It parses slide annotations (`<!-- say: ... -->` in MARP, `\say{}` in Beamer), synthesizes speech via TTS engines (Piper local or ElevenLabs cloud), and composites video segments using FFmpeg — all orchestrated by a doit-based incremental build system.

## Development Environment

All project packages are installed in `.venv/`. The Makefile uses `.venv/bin/` prefixes so `make` targets work without activating the venv. For direct commands, use `.venv/bin/python`, `.venv/bin/pytest`, etc.

The `.claude/` directory is committed (rules, skills, agents). Personal settings (`settings.local.json`) are gitignored. The `dev/` directory is excluded via `.git/info/exclude`.

## Planning Flow

Two planning docs, one tracked and one not:

- **`dev/INBOX.md`** (untracked) — Unsorted ideas, observations, and review findings. Dump anything here with no formatting pressure. Separated by `---` lines.
- **`ROADMAP.md`** (committed) — Curated, prioritized plan with Now/Next/Later tiers and a Done section.
- **`CHANGELOG.md`** (committed) — Keep a Changelog format. Updated when shipping features.

Items flow from inbox → roadmap during `/pm` triage. The `/pm` skill reads both files.

## Development Commands

```bash
make install                           # Install with local TTS + dev tools
make test                              # All tests (requires ffmpeg, marp, pdflatex, piper)
make test-unit                         # Unit tests only (fast, no external deps)
make lint                              # Ruff check + format
make typecheck                         # mypy --strict on src/
make showcase-piper                    # Build showcase example with local Piper TTS
make showcase                          # Build showcase example with configured TTS
make basel-piper                       # Build basel-problem example with Piper
make clean-showcase                    # Clean showcase (keeps API audio)
make clean-basel                       # Clean basel-problem (keeps API audio)
make clean-examples                    # Clean all examples (keeps API audio)
make purge-showcase                    # Nuke entire showcase cache
make purge-examples                    # Nuke all example caches
make clean                             # Remove project build artifacts + __pycache__
slidesonnet clean                                  # Default: --keep api
slidesonnet clean --keep nothing                   # Nuke entire cache
slidesonnet clean --keep current                   # Keep audio for current slide text (any engine)
.venv/bin/pytest tests/test_config.py -v         # Single test file
.venv/bin/pytest tests/test_cli.py::test_version # Single test function
```

## Testing Rules

- **NEVER run tests or builds against ElevenLabs** — it costs real money (API credits). Use `--tts piper` for integration testing, and mocked unit tests for ElevenLabs functionality.
- **Prefer `make clean-*` over `make purge-*`** — clean keeps cached API audio (which costs money to regenerate), purge nukes everything. Only use purge when explicitly asked.
- **No integration tests in CI** — GitHub Actions free tier has limited minutes. CI runs lint, typecheck, unit tests, and wheel build only. Integration tests (`make test`) are local-only.

## Releasing

```bash
git tag v0.1.0a1                       # Version tag triggers publish workflow
git push origin v0.1.0a1               # CI → TestPyPI → PyPI → GitHub Release
```

Version is set in `src/slidesonnet/__init__.py`. Update it before tagging.

## Code Conventions

- Python 3.12+, line length 100 (Ruff)
- `mypy --strict` must pass on all source files. Untyped external libraries (doit, elevenlabs, dotenv) are ignored via `[[tool.mypy.overrides]]` in pyproject.toml. All new code must have full type annotations.
- Integration tests marked with `@pytest.mark.integration` (in test_composer.py)
- External tool dependencies: ffmpeg, ffprobe, marp-cli, piper, pdflatex, pdftoppm (use `slidesonnet doctor` to check)
