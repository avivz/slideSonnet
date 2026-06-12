# CI Workflow

After every commit and push, check that CI passes on GitHub:

```bash
gh run list --limit 1                  # Get the latest run ID
gh run watch <run-id>                  # Watch until completion
gh run view <run-id> --log-failed      # If failed, inspect logs
```

CI runs 4 jobs: lint, typecheck, test (3.13), build. All must pass. If any fail, fix the issue and push again before moving on.

**No heavy tests in CI.** This repo stays on the GitHub Actions free tier, so CI
runs only the fast unit tier: `pytest -m "not integration and not browser"`.
Heavy tests — `integration` (external tools: ffmpeg/pdftoppm/latexmk/kokoro) and
`browser` (real-browser Playwright GUI journeys) — are **local-only**. Never add a
CI job that runs them.
