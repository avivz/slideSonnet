---
paths:
  - "tests/**/*.py"
---

# Testing Rules

- **NEVER run tests or builds against Inworld** — it costs real money (API credits). Use `--engine kokoro` for integration testing, and mocked unit tests (a fake `TTSEngine`) for Inworld functionality.
- The suite enforces this: an autouse conftest fixture pins `INWORLD_API_KEY` to a sentinel in the process environment (`env.getenv` checks the process environment before any `.env`, so a real key in a `.env` is never read) and replaces the client class with one that raises on construction. Tests needing a client mock `@patch("slidesonnet.tts.inworld.InworldClient")` over it.
- Unit tests don't rasterize: an autouse fixture stubs pdftoppm with tiny PNGs (real pdftoppm coverage stays in the integration tier). Deck-prep boilerplate lives in `tests/conftest.py::prep_marked_deck`.
- **Prefer `make clean-examples` (or `clean-basel`/`clean-showcase`) over `make purge-examples`** — clean keeps cached API audio (which costs money to regenerate), purge nukes everything. Only use purge when explicitly asked.
- **Heavy tests are local-only, never in CI** (free-tier minutes). Two heavy markers:
  - `@pytest.mark.integration` — needs external tools (export/render in `test_export_integration.py`, rasterize in `test_pdf_reader.py`, previews with real Kokoro in `test_error_showcase.py`).
  - `@pytest.mark.browser` — real-browser Playwright journeys (`tests/test_browser_journeys.py`: focus, typing without blur, real audio, navigation) against the production frontend and server.
  The CI unit tier is `pytest -m "not integration and not browser"`.
- Editor coverage, lowest level first: Python API/service tests (`tests/test_server_*.py`, FastAPI test client), Vitest store/component tests (`frontend/tests`, jsdom — in CI), and the local browser tier only for what needs a real browser. A new test must earn its place: check a lower-level test doesn't already cover it, and prefer one parametrized table over many one-assertion tests.
- External tool dependencies: ffmpeg, ffprobe, pdftoppm, kokoro (latexmk/pdflatex only to compile demo decks).
