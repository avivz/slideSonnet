---
paths:
  - "tests/**/*.py"
---

# Testing Rules

- **NEVER run tests or builds against ElevenLabs** — it costs real money (API credits). Use `--engine kokoro` for integration testing, and mocked unit tests (a fake `TTSEngine`) for ElevenLabs functionality.
- **Prefer `make clean-*` over `make purge-*`** — clean keeps cached API audio (which costs money to regenerate), purge nukes everything. Only use purge when explicitly asked.
- Integration tests marked with `@pytest.mark.integration` (export/render in `test_export_integration.py`, rasterize in `test_pdf_reader.py`, GUI-with-Kokoro in `test_gui.py`). Run the unit tier with `-m "not integration"`.
- GUI logic is tested via NiceGUI's in-process `user` simulation (`tests/conftest.py` loads `nicegui.testing.user_plugin`; the page is registered in `tests/gui_main.py`).
- External tool dependencies: ffmpeg, ffprobe, pdftoppm, kokoro (latexmk/pdflatex only to compile demo decks).
