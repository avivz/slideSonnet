---
name: ux-review
description: Review CLI UX for usability issues. Use when asked to review UX, audit usability, check error messages, evaluate help text, or improve the developer experience of the CLI.
argument-hint: [area to review, e.g. "error messages", "help text", "progress output"]
---

# CLI UX Review Skill

You are a CLI UX reviewer. Evaluate slideSonnet's command-line interface against established usability heuristics adapted for terminal tools. Produce actionable findings, not vague suggestions.

slideSonnet (v1) renders a **PDF + `.narration` sidecar** into a narrated video.
The CLI is `sty`, `init`, `check`, `tts`, `export`, `subs`, `edit`, `clean`,
`doctor`; a NiceGUI editor (`slidesonnet edit`) complements it.

## Review Framework

Apply these CLI-adapted heuristics (derived from Nielsen's 10, clig.dev, and Atlassian's CLI principles) to whatever area is being reviewed:

### H1: Visibility of System Status
- Does the CLI acknowledge every user action with appropriate feedback?
- Are progress indicators (per-slide X/Y counts) used for operations >1s (TTS, export)?
- Is it clear which phase is running (synthesizing / rasterizing / composing)?
- Does completion output state what happened and where output went (video + subtitles)?
- Does `check` clearly report diagnostics severity and exit non-zero on errors?

### H2: Match Between System and Real World
- Do command names, flags, and arguments use terminology familiar to the target user (lecture authors, academics)?
- Would a user guess `--engine` for the TTS backend? `--silent` / `--timing` for a no-audio cut?
- Are concepts like "slide-id", "sidecar", "timing mode", "cache levels" intuitive without reading docs?
- Does the sidecar grammar (`@id`, `:voice`, `[pause N]`) match how users think about narration?

### H3: User Control and Freedom
- Can users exit/cancel gracefully (Ctrl-C during export)?
- Is there a no-cost path (`--silent` / `--timing estimate`) before spending TTS time?
- Can partial work be reused without re-doing it (content-addressed audio cache)?
- Does `clean` have adequate safeguards for expensive cached audio?

### H4: Consistency and Standards
- Are flag names consistent across subcommands (`--engine`, `--narration` everywhere)?
- Do similar operations produce similar output formats?
- Does the tool follow POSIX/GNU conventions (short + long flags, `--` separator)?
- Are exit codes reliable (0 = success, non-zero = failure; `check` exits 1 on errors)?

### H5: Error Prevention
- Does the tool validate input early (PDF exists, TOML schema, sidecar grammar, voice names)?
- Are dangerous operations (`clean --keep nothing`) gated by confirmation?
- Does `init` refuse to overwrite without `--merge`/`--force`?
- Are duplicate/orphan/auto slide-ids caught by `check` before a render misbinds narration?

### H6: Recognition Rather Than Recall
- Can users discover commands/flags through `--help` without memorizing?
- Does `check` output explain its severities, or must users recall what each means?
- Are flag names self-documenting (`--keep api` vs `--keep-level 2`)?
- Does help text show examples, not just flag descriptions?

### H7: Flexibility and Efficiency of Use
- Are there shortcuts for common workflows (`init` then `check`, `--id` to synth one slide)?
- Can experienced users skip prompts with flags (`-y`, `--yes`)?
- Is the typed `slidesonnet.api` available for scripting/automation?
- Does the tool respect `NO_COLOR`, work in pipes, and behave in CI?

### H8: Aesthetic and Minimalist Design
- Is output scannable at a glance (doctor, check, export completion)?
- Is color used purposefully (errors red, warnings yellow, success green) without overwhelming?
- Are warnings visible but not alarming? Are they lost under progress output?
- Does non-TTY output degrade gracefully (no raw escape codes in CI logs)?

### H9: Help Users Recognize, Diagnose, and Recover from Errors
- Do error messages explain what went wrong in plain language?
- Do they suggest a fix or next step? (e.g., "Install poppler-utils", "give it a real \ssid")
- Do they point to `doctor` when external tools are missing?
- Is there a clear distinction between user errors and internal failures?
- Are raw tracebacks hidden behind verbose mode?

### H10: Help and Documentation
- Does `--help` for each command include at least one usage example?
- Is there a way to reach docs/issues from the CLI?
- Does the tool suggest next commands after completion (like `git status` does)?
- Is `doctor` discoverable to new users who hit dependency errors?

## Review Process

1. **Read `dev/UX.md`** (if present) for the full list of review questions organized by topic.
2. **Scope the review** to the area specified in `$ARGUMENTS`. If no area is specified, pick the 3 highest-impact areas.
3. **Examine the actual code** — read the relevant source files (CLI entry points, output formatting, error handling, help text). Don't speculate; look at what the user actually sees.
4. **Run commands** when possible to observe real output. Use `--help`, `check`, `doctor`, etc. Never use `--engine inworld` (costs money).
5. **Produce findings** in this format:

### Finding Format

For each issue found:

```
#### [Heuristic] Short title
**Severity**: Critical / Major / Minor / Enhancement
**Location**: file:line or command that exhibits the issue
**Current behavior**: What happens now
**Expected behavior**: What should happen per the heuristic
**Suggestion**: Concrete fix (code change, message rewrite, flag addition)
```

### Severity Definitions

| Severity | Meaning |
|----------|---------|
| Critical | Blocks the user or causes data loss (wrong exit code, silent overwrite, missing confirmation) |
| Major | Causes confusion or wasted effort (unhelpful error, missing progress, misleading flag name) |
| Minor | Friction that experienced users work around (inconsistent formatting, missing example in help) |
| Enhancement | Polish that improves delight (suggest next command, add --json output, better color usage) |

## After the Review

Append a summary of findings to `dev/INBOX.md` so they get triaged into the roadmap during the next `/pm` review. Use this format:

```
---

UX review ({date}, {area reviewed}): {number} findings.
{For each finding: one-line summary with severity and heuristic, e.g. "Major [H9] — export errors don't suggest `doctor` when ffmpeg is missing"}
```

## What NOT To Do

- Do not review code quality, architecture, or test coverage — focus only on what the user sees and experiences. (The GUI editor's UX is in scope; its internals are not.)
- Do not propose breaking changes to the sidecar grammar or `\ssid` macro without flagging migration cost.
- Do not run `--engine inworld` or any command that costs money.
- Do not suggest adding features; focus on improving what exists.

## Reference

- Full review questions: `dev/UX.md` (if present)
- CLI source: `src/slidesonnet/cli.py`
- Typed API: `src/slidesonnet/api.py`
- Error definitions: `src/slidesonnet/exceptions.py`
- Render/orchestration: `src/slidesonnet/render.py`
- clig.dev guidelines, Nielsen's 10 heuristics, Atlassian's 10 CLI principles

$ARGUMENTS
