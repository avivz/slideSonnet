---
paths:
  - "tests/**/*.py"
---

# Testing Rules

- **NEVER run tests or builds against ElevenLabs** — it costs real money (API credits). Use `--tts piper` for integration testing, and mocked unit tests for ElevenLabs functionality.
- **Prefer `make clean-*` over `make purge-*`** — clean keeps cached API audio (which costs money to regenerate), purge nukes everything. Only use purge when explicitly asked.
- Integration tests marked with `@pytest.mark.integration` (in test_composer.py)
- External tool dependencies: ffmpeg, ffprobe, marp-cli, piper, pdflatex, pdftoppm
