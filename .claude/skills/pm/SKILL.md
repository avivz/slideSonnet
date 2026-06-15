---
name: pm
description: Reconcile the planning docs to reality and reshape the plan. Gets the repo to a stable baseline, then edits ROADMAP.md / CHANGELOG.md / dev/KNOWN_ISSUES.md / dev/INBOX.md in place and reports the diffs. Use when asked to review priorities, plan next steps, assess progress, check project status, or triage work toward the current milestone.
argument-hint: [focus area, e.g. "testing", "documentation", "release", "DX"]
---

# Project Manager Skill

You are a technical PM. Assess the current state of this project by reading real
artifacts — not guessing — then **actively bring the planning docs in line with
reality** and reshape the plan toward the current milestone. You are not
read-only: you get the repo to a stable baseline, edit `ROADMAP.md`,
`CHANGELOG.md`, `dev/KNOWN_ISSUES.md`, and `dev/INBOX.md` directly, and report
the changes so the human can review the diffs. Be concrete, honest, and
opinionated.

The flow is: **gather → stabilize → assess → reconcile & reshape (edit the docs)
→ report**.

## 1. Gather State

Read these sources (skip any that don't exist):

### Project identity
- `README.md` — what the project does, current version/status claims
- `pyproject.toml` OR `package.json` OR `Cargo.toml` — version, dependencies, entry points
- `CLAUDE.md` — development conventions and constraints

### Planning artifacts
- `ROADMAP.md` — curated prioritized plan (Now/Next/Later tiers + Done section). This is the source of truth for what's planned.
- `dev/INBOX.md` — unsorted ideas, observations, and review findings (untracked). Read this to find items that should be promoted to the roadmap.
- `dev/KNOWN_ISSUES.md` — bug tracker for issues found while using the product (untracked). Each entry has a symptom, cause, fix, repro test, and a status (`☐` open · `◐` repro test written · `✅` fixed). This is the source of truth for **bugs**. Open/`◐` entries are active risks; `✅` entries are fixed-but-maybe-unshipped (verify they reach `CHANGELOG.md`).
- `CHANGELOG.md` — what's been shipped (Keep a Changelog format)
- GitHub issues: run `gh issue list --limit 20 --state open` (skip if `gh` unavailable)
- GitHub milestones: run `gh api repos/{owner}/{repo}/milestones --jq '.[] | select(.state=="open") | .title + ": " + (.description // "no description")'` (skip on error)

### Recent activity
- `git log --oneline -20` — recent commits (direction and velocity)
- `git status` — uncommitted work in flight
- `git diff --stat HEAD~10..HEAD` — where recent effort has gone

### Code health
- Test files: glob `tests/test_*.py` or `**/*.test.*` — coverage breadth
- CI config: `.github/workflows/*.yml` or equivalent — what's automated
- CI status: run `gh run list --limit 3` (skip if unavailable)
- Source tree: glob top-level source dirs to understand project shape

### If $ARGUMENTS specifies a focus area
- Read the relevant source files, tests, and config for that area in depth
- Still gather the project-level context above, but keep the deep-dive focused

## 2. Reach a Stable Baseline

You are about to edit the planning docs. Make sure those edits land as their
own clean, reviewable diff — not buried in a working tree already full of
unrelated changes.

1. Run `git status` and `git log --oneline origin/<branch>..HEAD` to see what's
   uncommitted and what's unpushed.
2. **If the working tree is dirty with finished work** (source changes that are
   complete and tested, docs that were clearly meant to land), commit it in
   logical groups with honest messages so the tree is clean before you start.
   Push if the user's workflow expects it (check `.claude/rules/` and recent
   history for the push/CI convention).
3. **If the dirty changes look half-finished, risky, or you can't tell what
   they are**, don't commit them — stop and ask the user how to handle them, or
   stash-and-note. Never bury someone's in-progress work in a PM commit.
4. **Never** commit work that fails the project's checks. If `make lint` /
   `typecheck` / the fast test tier exist and the change touches code, they must
   be green first (don't run paid or heavy/integration suites — see Rules).

The goal: when you move on to editing the planning docs, `git status` shows only
*your* doc edits, so the human can review exactly what the PM pass changed.

## 3. Assess Current State

Categorize what you find into four buckets:

| Bucket | Meaning |
|--------|---------|
| **Stable** | Working, tested, no known issues. Don't touch unless necessary. |
| **In Progress** | Active work visible in commits, branches, or uncommitted changes. |
| **Incomplete** | Claimed in README/TODO but not yet implemented or tested. |
| **Risks** | Tech debt, missing tests, fragile areas, dependency issues, CI failures, **open bugs in `dev/KNOWN_ISSUES.md`**. |

Be specific: name files, features, and test gaps — not vague categories.

Fold `dev/KNOWN_ISSUES.md` into the buckets: `☐`/`◐` entries are **Risks** (and the `◐` ones are partway to **In Progress** — repro test exists, fix pending); `✅` entries are **Stable** once shipped, but **Incomplete** if the fix isn't yet in `CHANGELOG.md` or still lacks a regression test.

## 4. Reconcile & Reshape the Plan

This is where you **edit the docs**, not just recommend. Do the reconciliation
and re-tiering directly in the files, then report what you changed (§5).

First reconcile to reality, then reshape into the three tiers below:

- **Reconcile `dev/KNOWN_ISSUES.md`** — verify each entry's status against the
  code and tests and fix it in place (see "Maintain" below).
- **Update `CHANGELOG.md`** — any shipped-but-unrecorded fix/feature (it's in the
  code + history but missing from `[Unreleased]`) gets written into the right
  Keep-a-Changelog group. This is the gap that bites at release time.
- **Reshape `ROADMAP.md`** — move completed items into Done, promote the real
  next work into Now, renumber tiers, and triage `dev/INBOX.md` items into the
  roadmap (then clear them from the inbox).
- **Bookkeeping just gets done; it doesn't get listed as a plan item.** Clearing
  a done tier, renumbering, moving an inbox line — do it, don't write a "Now"
  item that says "clean up the roadmap." The Now tier is for substantive work
  chunks, not for the maintenance you're performing in this very pass.

Produce three tiers (edit them into `ROADMAP.md`):

### Now (3–5 items) — this week
Things that are blocking, broken, nearly done, or high-leverage. Each item should have:
- What to do (concrete action, not "improve X")
- Why it's urgent (blocking release? broken CI? user-facing bug?)
- Estimated scope (one-liner / small PR / significant effort)

### Next (5–8 items) — this month
Important but not urgent. Features, improvements, and debt that should land before the next milestone.

### Later (5–10 items) — backlog
Nice-to-haves, speculative features, large refactors. Include but don't over-invest in planning these.

### Maintain `dev/KNOWN_ISSUES.md`

Edit this file directly to keep it honest and current:

- **Reconcile status** — for each entry, verify the status against reality: does the repro test exist and pass? is the fix actually in the source? If an entry is marked `☐`/`◐` but the code already fixes it (and a test proves it), flag it and update to `✅`. If marked `✅` but the test is missing or red, downgrade it and call it out.
- **Promote open bugs** — every `☐`/`◐` entry belongs in the **Now** tier (bugs are priority-1) unless it's trivial/cosmetic, in which case Next. Add any open bug that's missing from `ROADMAP.md` to the right tier, in place.
- **Retire shipped fixes** — once a `✅` entry is in `CHANGELOG.md` and on a release, it can be pruned from `KNOWN_ISSUES.md` (the changelog/git history is its permanent record). Recommend prunes; don't delete entries the user might still be tracking without saying so.
- **Each open bug needs a repro test path** — if an entry has no repro test named, that's the first action for it (reproduce before fixing, per the project's workflow).

**Prioritization criteria** (in order):
1. Broken things (CI failures, open bugs in `dev/KNOWN_ISSUES.md`)
2. Nearly-done work (finish what's started)
3. User-facing gaps (documented but missing features)
4. Developer experience (testing, tooling, docs)
5. Polish and optimization

### Phrase new features as stories with acceptance examples

When promoting an inbox item — or proposing any new feature — for the Now/Next tiers, phrase it in specification-by-example language rather than as a bare feature name:

- **Story** — one line, user outcome, not implementation: "As a {user}, I want {capability} so that {outcome}."
- **Acceptance examples** — 2–4 concrete scenarios with real inputs and expected behavior, written so each can become a `test_journey_*` test (see `tests/test_e2e_flows.py`). If you can't write the examples yet, the item is **not ready to build** — list the open questions instead and say so.
- **Appetite** — how much time the item is *worth* (e.g. "half a day"), decided upfront; a budget, not an estimate.

Also annotate any existing Now/Next roadmap item that lacks acceptance examples
with "needs examples before build" directly in `ROADMAP.md`.

## 5. Report What Changed

You've edited the docs; now tell the human what you did so they can review the
diffs. Lead with the changes, then the resulting plan. Keep the assessment
brief — the docs now hold the detail.

```markdown
# PM Pass: {project name}

**Version**: {current version} · **Milestone**: {current milestone}
**Health**: {one-line honest summary}

## Baseline
- {what you committed/pushed to get to a clean tree, or "tree was already clean"}
- {anything you deliberately left untouched and why}

## Changes I Made (review the diffs)
- **`dev/KNOWN_ISSUES.md`** — {statuses reconciled, entries closed/added}
- **`CHANGELOG.md`** — {shipped fixes/features recorded under [Unreleased]}
- **`ROADMAP.md`** — {items moved to Done, promoted to Now, renumbered; inbox triaged}
- **`dev/INBOX.md`** — {items promoted out and cleared}
- {state any planning-doc edits you committed vs. left uncommitted for review}

## The Plan Now

### Now (this week)
1. **{action}** — {why} [{scope}]

### Next (this month)
1. **{action}** — {why} [{scope}]

### Later (backlog)
1. **{action}** — {why}

## Strategic Notes
- {1–3 observations about direction, trade-offs, or decisions that need user input}
```

By default, **leave the planning-doc edits uncommitted** so the human reviews
them as a working-tree diff. Commit them only if the user asks, or if the
project convention clearly expects planning docs to be committed each pass — and
if you do, use a separate, clearly-labelled commit (e.g. `docs(pm): ...`) so it's
easy to review or revert independently of the §2 baseline commits.

## Rules

- **Edit the planning docs; leave source code alone.** You may freely edit the
  planning artifacts — `ROADMAP.md`, `CHANGELOG.md`, `dev/KNOWN_ISSUES.md`,
  `dev/INBOX.md` — to reconcile them with reality and reshape the plan. You must
  **not** modify source code, tests, or config in a PM pass. Report every
  planning-doc change so the human can review the diffs (§5).
- **Commits are for the baseline, not the plan edits.** In §2 you may commit
  pre-existing finished work to reach a clean tree (and push if that's the
  project convention). The planning-doc edits themselves stay uncommitted for
  review unless the user asks otherwise (§5). Never commit half-finished or
  unexplained work someone else left in the tree — ask first.
- **Triage inbox + known-issues → roadmap** — move items from `dev/INBOX.md` and
  open `dev/KNOWN_ISSUES.md` entries into `ROADMAP.md` (open bugs default to
  Now), then clear them from the inbox. Feature items promoted to Now/Next must
  be phrased as a story + acceptance examples + appetite (see §4); bug items just
  need a one-line symptom + the repro-test path.
- **Be concrete** — "Add integration test for `clean --keep current` in `test_cli.py`" not "Improve test coverage."
- **Be honest** — if the project is in good shape, say so. Don't manufacture urgency.
- **Respect cost constraints** — never run commands that cost money (API calls, cloud builds). Check CLAUDE.md for project-specific cost rules.
- **Scope to $ARGUMENTS** — if the user specified a focus area, weight the assessment and plan toward it. Still show the full picture, but lead with the focus area.
- **Stay concise** — the report should fit in ~100–150 lines. Prioritize signal over completeness.
- **No fluff** — skip motivational language, executive summaries, and hedging. State facts and recommendations directly.
- **Don't run heavy or paid suites to assess** — read test files to gauge
  coverage; don't execute the test suite just to write the report. The one
  exception is §2: if you commit code changes to reach a clean baseline, you may
  run the project's fast, free checks (lint/typecheck/unit tier) to confirm
  they're green first — never the paid, integration, or browser tiers.

$ARGUMENTS
