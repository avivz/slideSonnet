---
paths:
  - "tests/**/*.py"
---

# Testing Rules

- **NEVER run tests or builds against ElevenLabs** — it costs real money (API credits). Use `--engine kokoro` for integration testing, and mocked unit tests (a fake `TTSEngine`) for ElevenLabs functionality.
- The suite enforces this: an autouse conftest fixture pins `ELEVENLABS_API_KEY` to a sentinel (so doctor's `load_dotenv()` can't leak the real key from `.env`) and replaces the client class with one that raises on construction. Tests needing a client mock `@patch("slidesonnet.tts.elevenlabs.ElevenLabs")` over it.
- GUI unit tests don't rasterize: an autouse fixture stubs `EditorState.ensure_images` with tiny PNGs (real pdftoppm coverage stays in the integration tier). Deck-prep boilerplate lives in `tests/conftest.py::prep_marked_deck`.
- **Prefer `make clean-*` over `make purge-*`** — clean keeps cached API audio (which costs money to regenerate), purge nukes everything. Only use purge when explicitly asked.
- **Heavy tests are local-only, never in CI** (free-tier minutes). Two heavy markers:
  - `@pytest.mark.integration` — needs external tools (export/render in `test_export_integration.py`, rasterize in `test_pdf_reader.py`, GUI-with-Kokoro in `test_gui.py`).
  - `@pytest.mark.browser` — real-browser Playwright GUI journeys (focus/blur, value-sync timing, playback re-render) that the in-process sim structurally cannot catch.
  The CI unit tier is `pytest -m "not integration and not browser"`.
- GUI coverage has two tiers: fast **in-process** `user` simulation (`tests/conftest.py` loads `nicegui.testing.user_plugin`; page registered in `tests/gui_main.py`) for wiring/logic — but it writes widget `.value` synchronously, so it CANNOT see focus/blur or websocket-timing bugs; and the **browser** tier for those. Put timing-sensitive journeys in the browser tier.
- External tool dependencies: ffmpeg, ffprobe, pdftoppm, kokoro (latexmk/pdflatex only to compile demo decks).
