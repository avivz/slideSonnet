# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

slideSonnet (v1.x) is a **PDF + narration-sidecar editor**. You bring a finished
PDF whose Beamer source stamped a stable `\ssid` slide-id onto every page; the
spoken narration lives in a human-readable, git-diffable `<deck>.narration`
sidecar keyed to those ids. The tool synthesizes speech (Kokoro local / Inworld
cloud, content-addressed cache), composites video with FFmpeg, writes SRT/VTT
subtitles, and ships a NiceGUI editor (`slidesonnet edit`) with a silence-aware
whole-deck preview. The CLI/`slidesonnet.api` make the whole pipeline scriptable.

> The pre-1.0 source→video pipeline (MARP/Beamer parsers, doit build graph,
> playlists, inline `\say`/`<!-- say -->`) was **removed** in the v1 rewrite.
> Don't reintroduce it.

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
make install                           # Editable install with Kokoro + dev tools
make test                              # All tests (needs ffmpeg, pdftoppm, kokoro)
make test-unit                         # Unit tests only (fast, no external deps)
make lint                              # Ruff check + format --check
make fmt                               # Ruff format
make typecheck                         # mypy --strict on src/
make basel                             # Compile + render basel-problem (Kokoro)
make showcase                          # Compile + render showcase (Kokoro)
make demos                             # Both demos
make check-basel / make check-showcase # Run id reconciliation on a demo
make clean-basel / make clean-showcase # slidesonnet clean (keeps API audio)
make purge-examples                    # clean --keep nothing on both demos
make clean                             # Remove build artifacts + __pycache__ + .slidesonnet/
slidesonnet clean <deck.pdf>                       # Default: --keep api
slidesonnet clean <deck.pdf> --keep nothing        # Nuke the deck's cache
.venv/bin/pytest tests/test_narration_format.py -v # Single test file
.venv/bin/pytest tests/test_cli.py::test_version   # Single test function
.venv/bin/pytest -m "not integration"              # Unit tier only
```

## Testing Rules

- **NEVER run tests or builds against Inworld** — it costs real money (API credits). Use `--engine kokoro` for integration testing, and mocked unit tests (a fake `TTSEngine`) for Inworld functionality. The test suite enforces this with an autouse conftest guard (sentinel API key + fail-fast fake client) — mock `slidesonnet.tts.inworld.InworldClient` when a test needs a client.
- **Prefer `make clean-*` over `make purge-*`** — clean keeps cached API audio (which costs money to regenerate), purge nukes everything. Only use purge when explicitly asked.
- **No heavy tests in CI** — GitHub Actions free tier has limited minutes, and we stay on it. CI runs lint, typecheck, the fast unit tier (`pytest -m "not integration and not browser"`), and the wheel build only. Heavy tests are local-only: `integration` (`make test`, external tools) and `browser` (real-browser Playwright GUI journeys).
- **Fast inner loop: `make test-fast`** (~16 s) for day-to-day iteration — it's the unit tier minus the `gui` marker. The `gui` marker is **auto-applied** (no need to tag tests by hand) to any test using NiceGUI's in-process `user` fixture; those ~75 server-lifecycle tests are ~90 % of the unit-tier wall time. Run the **full** tier — `make test-unit` (~100 s) — before you push, since CI runs it. **Don't reach for `pytest-xdist`**: the GUI tests serialize on the in-process server while each worker re-pays the heavy torch/nicegui import, so `-n auto` gives no speedup (measured flat ~105 s at every worker count). The serial full tier is the reality; the fast loop is how you avoid paying it constantly.
- **Tests must be order-independent.** Don't rely on collection order or on state another test left behind. Process-wide caches (e.g. `slidesonnet.tts.qwen3._MODEL_CACHE`) are reset between tests by an autouse `conftest` fixture; if you add another global/warm-model cache, reset it there too rather than writing an order-dependent assertion.

## Example Videos

Example videos are **not** stored in the repo. They are hosted as GitHub Release assets on the `v0.0.0` release. MP4 files live on disk in `examples/` but are gitignored.

```bash
# Upload or replace a video
gh release upload v0.0.0 examples/showcase/showcase.mp4 --clobber

# Upload all example videos
gh release upload v0.0.0 examples/showcase/showcase.mp4 examples/basel-problem/basel-problem.mp4 --clobber
```

## Releasing

```bash
git tag v1.0.0a0                       # Version tag triggers publish workflow
git push origin v1.0.0a0               # CI → TestPyPI → PyPI → GitHub Release
```

Version is set in `src/slidesonnet/__init__.py`. Update it before tagging.

## Code Conventions

- Python 3.13+, line length 100 (Ruff)
- `mypy --strict` must pass on all source files. Untyped external libraries (inworld_tts, dotenv, kokoro, fitz, nicegui) are ignored via `[[tool.mypy.overrides]]` in pyproject.toml. All new code must have full type annotations.
- Heavy tests are local-only (never in CI): `@pytest.mark.integration` (export/render and GUI-with-Kokoro) and `@pytest.mark.browser` (real-browser Playwright GUI journeys). GUI logic is also unit-tested via NiceGUI's in-process `user` simulation (selenium-free `nicegui.testing.user_plugin`, loaded in `tests/conftest.py`) — fast, but blind to focus/blur and value-sync timing, which is what the browser tier covers.
- External tool dependencies: ffmpeg, ffprobe, pdftoppm, kokoro (Python package); latexmk + pdflatex to compile your own deck (use `slidesonnet doctor` to check)
