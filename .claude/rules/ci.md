# CI Workflow

After every commit and push, check that CI passes on GitHub:

```bash
gh run list --limit 1                  # Get the latest run ID
gh run watch <run-id>                  # Watch until completion
gh run view <run-id> --log-failed      # If failed, inspect logs
```

CI runs 5 jobs: lint, typecheck, test (3.12), test (3.13), build. All must pass. If any fail, fix the issue and push again before moving on.
