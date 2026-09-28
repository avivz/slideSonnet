# Frontend migration: phased plan

- Date: 2026-09-28
- Baseline: `0a4e920` on `main` (the agent review loop is merged)
- Document branch: `docs/frontend-migration`

## Objective

Replace the NiceGUI frontend with a Vue 3 application backed by the existing
Python domain code — **incrementally**. Each phase below is its own branch,
lands on `main` with CI green, and leaves `slidesonnet edit` fully working.
NiceGUI and Vue coexist while the port is in flight: routes move from one to
the other a screen at a time, and NiceGUI is removed only in the last phase.

Each phase ends at a **checkpoint**: the maintainer opens a real deck in the
real editor, confirms the phase's acceptance list, and approves the merge.
The implementing agent does not start the next phase without that approval.
Phases may be split further; they may not be merged into one big-bang branch.

The finished product still launches with `slidesonnet edit`, works locally,
and supports the library, narration editor, review workflow, preview,
generation, and export. The port fixes known interaction bugs (below) and
**revisits the layout**: each Vue screen is built to an approved redesign
rather than copied pixel for pixel (see *Layout redesign*). Parity means
*behavior* parity; the look and arrangement may change. Genuinely new
features (waveform timing, drag-reorder, etc.) come after, on the new stack.

Retain the Python CLI, PDF processing, sidecar format, review records, TTS
engines, audio cache, shared pool, subtitle timing, and FFmpeg export pipeline.
Do not add accounts, cloud hosting, collaboration infrastructure, a database,
SSR, or a desktop shell. The current browser/app-window launch support remains.

## Why migrate

The Python core already has useful separation (`api.py`, narration models,
rendering, review operations); preserve it. The frontend is the problem:
~3,000 lines in `gui/app.py` plus state, review UI, and JS helpers, where
browser interaction and server operations share mutable state. Every keystroke,
focus change, and playback tick is a server round trip, so the code carries a
growing set of blur/`editing_active`/deferred-save guards to keep server-driven
re-renders from clobbering the browser. That model caps what the GUI can do:
native undo, smooth scrubbing, drag-reorder, a timing/waveform editor, and
rich review diffs are all expensive or impossible. A browser-owned UI removes
the whole bug class and raises that ceiling.

Secondary benefit: the in-process NiceGUI `user` tests are ~90 % of the unit
tier's wall time and are blind to focus/blur. Vitest component tests are fast
and test exactly those behaviors.

### Known bugs — each is fixed in a named phase

| # | Bug | Evidence | Fixed in |
|---|---|---|---|
| B1 | **Draft loss on external sidecar edit.** A changed sidecar triggers `render()`, rebuilding the editor and discarding unsaved typing. | `EditorView._poll_sources` (`gui/app.py`, the `"sidecar" in changes` branch) | Phase 0 (NiceGUI stopgap), properly in Phase 4 |
| B2 | **Split playback timing.** Python handles `timeupdate` and flips the slide; `static/morph.html` drives transitions on the browser clock. Slide changes depend on a round trip. | `Player.on_timeupdate` | Phase 3 |
| B3 | **Blocking work on the UI event path.** Save runs serialization, reload, review bookkeeping, cache pruning inline. | `blocks.save_current` call chain | Phase 1 (service layer offloads it) |
| B4 | **Shared mutable preview track.** `track.wav` is rewritten in place at a fixed path and busted with a `?t=` token; overlapping previews can play the wrong audio. | media route comment in `gui/app.py` | Phase 1 (immutable artifacts) |
| B5 | **Non-recursive packaging glob.** `"slidesonnet.gui" = ["static/*"]` would drop nested bundle assets. | `pyproject.toml` | Phase 2 |

Each fix lands with a regression test in the phase that fixes it.

## Decisions

| Concern | Choice |
|---|---|
| Frontend | Vue 3 single-file components, Composition API, strict TypeScript |
| Build | Vite; npm with a committed lockfile and a documented supported Node version |
| Navigation | Vue Router; retain `/` and `/d/{token}` URLs |
| Shared UI state | Pinia; separate server snapshots, local drafts, jobs, and playback |
| Presentation | Redesigned layout on a small token set (color, type, spacing) derived from today's theme; semantic HTML and accessible controls |
| Backend | FastAPI routes + explicit Pydantic request/response models |
| Commands | HTTP JSON API under `/api/v1`; TypeScript DTOs generated from OpenAPI |
| Updates | Server-Sent Events (SSE) for source changes and job progress |
| Media | Same-origin HTTP with byte-range support and versioned artifact URLs |
| Testing | Python + API tests and Vitest in CI; Playwright journeys local-only |
| Installation | Compiled frontend bundled in the Python distribution; no Node at runtime |

**Coexistence mechanism.** NiceGUI's `app` *is* a FastAPI instance, and
`gui/app.py` already registers plain `@app.get` media routes on it. During the
migration, the `/api/v1` routers, the SSE endpoint, and the built Vue assets
mount on that same app — one process, one origin, one port. A route belongs to
exactly one frontend at a time; switching between a Vue page and a NiceGUI page
is an ordinary page navigation (deck switching already is one). After Phase 6,
the same routers mount on a plain FastAPI app factory and NiceGUI goes away.

Use a small dependency set. Do not reproduce Quasar's component system just to
keep its look. Do not add a second state/query framework alongside Pinia
unless a concrete need justifies it.

## Testing policy (CI stays on the free tier)

| Tier | Where | Contents |
|---|---|---|
| Python unit + API | CI | Existing unit tier plus API tests via FastAPI's test client |
| Frontend | CI | ESLint, `vue-tsc`, Vitest (component + store tests), production build, DTO drift check |
| Browser (Playwright) | **Local only** (`make test-browser`) | Production frontend against the real Python API, synthesis stubbed at the `TTSEngine` boundary |
| Integration | **Local only** (`make test`) | Real ffmpeg/pdftoppm/Kokoro |

Browser tests stay out of CI. Revisit only if a browser smoke run becomes
*much* faster than today's tier (order of tens of seconds total) — and then as
a proposal to the maintainer, not as part of a phase. Vitest carries the
focus/blur, draft, and playback-controller logic that NiceGUI's in-process
tests could not see, so most coverage that needs to be in CI can be there
without a browser.

No paid API calls anywhere; keep the existing conftest guards against real
Inworld calls. No model downloads or real TTS in browser tests.

### Test hygiene: shrink, don't transplant

The suite is already large (~1,090 tests; the unit tier alone takes ~2.5 min).
The migration is a chance to make it smaller and sharper, not to port it 1:1.

- **Every ported test earns its place.** Before porting a GUI test, name the
  behavior it protects and check whether a domain, service, or API test
  already covers it. If one does, drop the GUI test and move any unique
  assertion down to that lower level.
- **Test at the lowest level that can see the bug.** Logic goes into Python
  unit/API tests or Vitest store tests. Component tests cover wiring. Browser
  journeys are only for what needs a real browser (focus, timing, media).
- **Consolidate.** Merge near-duplicate tests (same setup, one assertion
  each) into one test or a parametrized table. Delete tests that only pin
  implementation details (widget class names, internal call order) that the
  port makes irrelevant anyway.
- **Pruning is not deleting coverage to get green.** A removed test is either
  redundant (point to what covers it) or pins behavior that no longer exists
  (say which). The parity inventory records this mapping.
- **Report the numbers.** Each checkpoint states test counts and wall time per
  tier, before and after the phase. The expected trend is down.

## Phases

Each phase lists what it builds, which bugs it closes, and its checkpoint.
"Parity" means the behavior as it is on `main` today, with its tests.

### Phase 0 — Baseline, inventory, draft-loss stopgap

- Record the current test state (`make test-unit`, `make test`,
  `make test-browser`) with honest notes on failures or timeouts; don't assume
  green. Capture reference screenshots of library, editor, preview, review.
- Write the **parity inventory** (see below) as a checked list in
  `docs/frontend-parity.md`, each item pointing to its current test(s).
  While mapping, flag GUI tests that are redundant with lower-level tests or
  only pin implementation details; they are candidates to drop, not to port.
- **B1 stopgap in NiceGUI:** when the sidecar changes externally and the open
  slide has a dirty draft, don't rebuild the editor; keep the draft, reload the
  other slides, and show a banner offering "keep mine" / "use file version".
  Regression test first (typing without blur, then an external write). This
  data-loss fix should not wait for Phase 4.

Checkpoint: inventory reviewed; B1 verified in the real editor.

### Phase 1 — Service layer and API inside the current app

- Extract explicit service operations from `gui/state.py` / `gui/app.py`
  over the existing Python core. Services take explicit deck token, slide ID,
  and engine options — no shared `EditorState.index` or "selected engine".
- Content-based source revisions (narration, PDF, config, review);
  per-deck serialized writes; same-directory temp file + atomic replace;
  409 on expected-revision mismatch.
- Backend-owned job manager (generate, preview, export, render-page) with IDs,
  immutable input snapshots, progress, cooperative cancellation, subprocess
  cleanup. Jobs are independent of browser connections.
- Immutable, per-job preview artifacts (**B4**); tested Range/206 media routes.
- Blocking parse/hash/rasterize/assemble/prune off the event loop (**B3**).
- `/api/v1` routes + SSE, mounted on NiceGUI's FastAPI app. OpenAPI → TS DTO
  generation command and drift check (the check can land with Phase 2).
- The NiceGUI editor switches its own save/generate/preview paths to the new
  services, so the services are exercised by real use immediately.

Checkpoint: API tests green in CI; NiceGUI editor behaves identically on a
demo deck, with saves no longer stalling the UI and overlapping previews
playing their own tracks.

*As built* (`src/slidesonnet/server/`): `revisions.py` (content hashes),
`decks.py` (`DeckService`: per-deck lock, revision-checked atomic writes,
debounced orphan sweep), `editing.py` (block/orphan/voice edits by explicit
slide id), `jobs.py` + `events.py` (job manager, SSE bus), `previews.py`
(immutable artifacts + manifest), `media.py`, `snapshots.py`, `schemas.py`,
`routes.py`, `context.py`/`app.py` (mounting, host/origin/session guard),
`openapi.py` (schema export for the TS types). Two deliberate gaps: the
review routes wait for Phase 5, where their consumer is built; and the
NiceGUI editor keeps its per-clip generation queue (`gui/jobs.py`, now
behind the shared per-engine lock) until the Vue editor's generate commands
replace it in Phase 4. Preview and export in the NiceGUI editor already run
as backend jobs.

### Phase 2 — Frontend toolchain, packaging, and the library in Vue

- Scaffold `frontend/` (Vite, Vue, Router, Pinia, Vitest, ESLint, `vue-tsc`).
- Build into `src/slidesonnet/server/static/`; recursive package-data rule
  (**B5**); wheel + sdist include assets; installing either works without Node.
  Clear error if a developer launches an unbuilt checkout.
- CI: add the frontend job (lint, type-check, Vitest, build, DTO drift).
  Release workflow builds the frontend before wheel/sdist.
- Port the **library view** (`/`) to Vue: registered decks, grouping, scan
  limits, natural ordering, stable deep links into the (still NiceGUI) editor.
- Makefile/dev startup: Vite dev server proxying `/api` and SSE (no buffering)
  to the Python server.

Also in Phase 2: the design brief and token set, and the approved library
mockup the library port is built to.

Checkpoint: `pip install` of the built wheel in a clean venv, no Node on PATH,
opens the Vue library and navigates into the NiceGUI editor and back.

### Layout redesign (runs alongside Phases 2–5)

The redesign happens screen by screen, just ahead of each screen's port, so
every Vue screen ships once in its new form (no port-then-redesign churn).

1. **Design brief (Phase 2, before the library port).** Starting from the
   Phase 0 reference screenshots, list the layout problems and goals for each
   screen, and fix a token set (palette, type scale, spacing, radii) plus
   the shared components (buttons, fields, cards, dialogs, panes).
2. **Mockups per screen.** Before porting a screen, produce a clickable
   HTML mockup (2–3 directions for the editor, fewer for smaller screens),
   using the real deck content from the screenshots. The maintainer picks
   one or asks for changes. No port starts on an unapproved layout.
3. **Build to the approved mockup.** Checkpoints compare the result to the
   mockup, not to the old UI.

Constraints: dark theme stays the default; slide aspect ratio and a large
slide view stay central; keyboard flows (arrows, Ctrl+K, Alt+←/→, Ctrl+S)
keep working; every behavior in the parity inventory stays reachable. Moving
a control is fine; dropping one needs the maintainer's approval, recorded in
the inventory.

Starting observations from the Phase 0 screenshots (`dev/frontend-baseline/`):

- **Library:** decks are a plain list with a one-line status; the top-level
  folder is repeated as a section header over a single deck; PDFs in cache
  folders (`*/cache/slides`) show up as phantom "no narration yet" decks
  (a discovery bug, fixed in the library port).
- **Header:** the deck name reads `basel-problem / basel-problem` when the
  folder and deck share a name.
- **Editor:** the transport (play, deck play, stop, speed, scrubber) sits
  at the bottom of the narration column, below the fold on long slides.
  Engine, voices, auto-generate, *Generate missing*, and *Export* are stacked
  at the bottom of the right console with a large empty area above them.
  Transition-in, start silence, utterances, and end silence all get equal
  visual weight; the utterance text is what matters most.
- **Filmstrip:** thumbnails carry tiny status dots that are hard to read.
- **Narrow windows:** the footer hints wrap into several lines; the console
  collapses, but its controls have no alternative home.

### Phase 3 — Browser-owned playback controller

- A typed TS playback module (`frontend/src/features/playback/`): one `<audio>`
  element as the clock; slide, transition, scrubber, and labels derived from
  `currentTime` via requestAnimationFrame; resync on seek, pause, resume, rate
  and visibility change; explicit listener cleanup. Port `morph.html` effects
  into it. No playback ticks to Python (**B2**).
- Python returns a preview manifest (artifact ID, revisions, media URL,
  duration, cues, page image URLs, transition schedule from existing timing
  logic). Browser visuals are approximate; FFmpeg output is authoritative.
- Ship it **embedded in the NiceGUI editor first**, replacing `on_timeupdate`
  and `morph.html`. The same module moves into the Vue editor in Phase 4
  unchanged. Playback slide stays separate from editing slide, preserving
  today's edit-safe following.

Checkpoint: preview in the real editor follows audio with no round trip;
seek/speed/pause/stop verified; Vitest covers cue lookup and the controller.

### Phase 4 — Editor in Vue

Starts from the approved editor mockup (see *Layout redesign*).
Largest phase; split into sub-branches as needed (e.g. 4a view + navigation +
layout, 4b narration editing + drafts, 4c voices/generation/diagnostics/export).
While incomplete, the Vue editor is reachable only behind a temporary opt-in
(`slidesonnet edit --frontend vue` or similar); `/d/{token}` defaults to
NiceGUI until 4 is at parity, then the default flips. The flag is removed in
Phase 6 — it is scaffolding, not a deliverable.

- Implement the editing and conflict rules below. This is where **B1** gets its
  real fix: drafts are browser-owned and external reloads never touch them.
- Narration, pauses, voices, diagnostics, orphans, generation, auto-build,
  export — per the parity inventory.
- Playback controller from Phase 3.

Checkpoint: every editor item in the parity inventory checked; the Vue editor
becomes the default; maintainer uses it on a real course deck.

### Phase 5 — Review in Vue

- Port the full review surface (`gui/review_panel.py`, `gui/review.py`) over
  typed adapters to `review/*`: conversations, turn/status badges,
  accept/reopen/show closed, filter, next-your-turn, before/after and word
  diffs, removed slides, **declared-but-uncompiled slides** (IDs absent from the
  current PDF), external review-file changes. On-disk and CLI compatibility
  with `slidesonnet review` is unchanged.

Checkpoint: a full review round with an agent on a real deck.

### Phase 6 — Remove NiceGUI

- Move the routers to a plain FastAPI app factory (`create_app`, explicit
  registry and job-manager lifetimes, no process-global app). Uvicorn serves
  bundled assets in production.
- Delete NiceGUI UI, `gui/static/*` helpers, the in-process `user` plugin
  fixtures, the `gui` pytest marker, and the `--frontend` flag. Keep
  framework-independent logic and tests, relocating as needed.
- Drop `nicegui` from dependencies; add explicit FastAPI/Uvicorn/Pydantic.
- Migrate recognized `app.storage.general` preferences (`auto_build`,
  `single_slide_transitions`) to browser storage once; document any reset.
- Update README, CLAUDE.md, Makefile, release workflow, CHANGELOG.

Checkpoint: NiceGUI absent from runtime and test harness; packaged install
smoke test passes; all parity items checked.

## Code to read and preserve

| Existing code | Migration treatment |
|---|---|
| `src/slidesonnet/api.py` | Keep public Python API; services wrap it |
| `gui/app.py` | Inventory controls/behaviors; replaced screen by screen |
| `gui/state.py` | Extract reusable operations into services (Phase 1) |
| `gui/library.py` | Reuse discovery, natural ordering, registry, stable deck tokens |
| `gui/jobs.py` | Reuse queue concepts; job lifecycle becomes backend-owned |
| `gui/review.py`, `review/*` | Preserve review semantics and on-disk compatibility |
| `gui/review_panel.py` | Port the full review surface (Phase 5) |
| `gui/launch.py`, `gui/devserver.py`, `cli.py` | Preserve launch options; adapt dev startup |
| `gui/static/editor.css`, `theme.py` | Reuse tokens/layout intent; drop Quasar selectors |
| `gui/static/morph.html` | Port effects to the typed playback module (Phase 3) |
| `audio/*`, `video/*`, `render.py`, `timing.py` | Preserve synthesis/assembly/export timing |
| `deck.py`, `narration/*`, `cache.py`, `clean.py`, `pool.py` | Preserve formats, cache keys, preservation rules |
| `tests/test_gui*.py`, `tests/test_browser_journeys.py` | Map each behavior to a retained or replacement test |

The review design spec is `dev/DESIGN-review.md` (untracked, in the
maintainer's checkout); read it if available, otherwise treat the code and
`tests/test_review*.py` / `tests/test_gui_review*.py` as the spec.

## Target structure

Adjust names without weakening the boundaries:

```text
frontend/
  src/api/                  # generated DTOs, fetch wrapper, SSE client
  src/stores/               # snapshots, drafts, preferences, jobs
  src/features/library/
  src/features/editor/
  src/features/playback/    # controller, cue lookup, transition effects
  src/features/review/
  src/components/           # shared controls, dialogs, resizable panes
  src/styles/
  tests/
src/slidesonnet/server/
  app.py                    # create_app (Phase 6); router mounting before that
  schemas.py
  routes/                   # decks, editing, jobs, review, media, events
  services/                 # explicit operations over the Python core
  jobs.py
  events.py
  static/                   # generated frontend output, packaged recursively
```

The browser owns selection, focused field, unsaved drafts, open panels, filter
text, playback position, scrub state, and presentation preferences. Python owns
durable documents, validation, source revisions, diagnostics, media artifacts,
synthesis, export, and review records. Keep an immutable acknowledged snapshot
separate from editable browser drafts.

## Feature parity inventory

Maintained in `docs/frontend-parity.md` from Phase 0, each item referencing its
check. At minimum:

| Area | Required behavior |
|---|---|
| Launch/library | All current `edit` target forms, `--root`, host/port, no-browser, custom browser, WSL, app-window and dev modes; bounded discovery; stable deep links |
| Navigation | Buttons, arrows with typing-safe shortcuts, filmstrip, Ctrl+K filtering, Alt+←/→ deck switching; pending edits preserved |
| Layout | Slide aspect ratio, dark theme, resizable/collapsible panes, pane restoration, long-deck scrolling |
| Narration | Add/delete/reorder utterances and pauses; text, direction, voice, pace; leading/trailing silence; inherited/default values; explicit and automatic save |
| Transitions | Effect families/directions/durations; shared boundary ownership; first/last slide; single-slide preview toggle |
| Voices/TTS | Named voices and per-engine mappings; backend selection; cache badges; per-utterance/slide/all-missing generation; force regeneration; warmup/errors; local-only auto-build; paid-operation confirmation |
| Playback | Single/deck preview, start at current slide, play/pause/resume/stop, seek, speed, edit invalidation, obsolete build cancellation, editing while preview plays |
| Diagnostics/orphans | Per-slide and deck diagnostics; unattached narration attach/append/delete; missing/unmarked/duplicate slides |
| Review | As listed in Phase 5 |
| Export | Readiness checks and blockers, explicit draft export, progress/errors, output naming, subtitles and transitions |
| Files | Live PDF/sidecar/config/review refresh; malformed/intermediate writes keep the last good state with a useful error |

Prefer existing test markers as `data-testid` values. Preserve keyboard focus
and native text undo during background updates; never recreate an input
because a job badge changed. Dialogs need keyboard navigation, accessible
names, focus trapping, and focus restoration.

## API contract

Defined and tested in Phase 1, before components depend on it. Route names are
a proposed shape, not a second home for domain logic:

| Route | Purpose |
|---|---|
| `GET /api/v1/library` | Registered decks, grouping, scan limitations |
| `GET /api/v1/decks/{token}` | Snapshot, revisions, pages, narration, diagnostics, capabilities |
| `PATCH /api/v1/decks/{token}/slides/{slide_id}` | Validated block edit with expected revision |
| `POST /api/v1/decks/{token}/commands` | Discriminated commands for voice/orphan operations |
| `POST /api/v1/decks/{token}/jobs` | Generate, preview, export, or render-page job |
| `GET /api/v1/jobs/{job_id}` | Authoritative status, result, error, progress |
| `POST /api/v1/jobs/{job_id}/cancel` | Cooperative cancellation |
| `GET /api/v1/decks/{token}/review` | Review state and diffs |
| `POST /api/v1/decks/{token}/review/commands` | Typed adapters to review operations |
| `GET /api/v1/events` | Deck/job/source events for the subscriber |

Typed, discriminated command bodies — not arbitrary dicts or Python method
names. Errors carry stable codes and user-readable messages; 404 unknown
resource, 422 invalid input, 409 revision mismatch. Never serialize secrets or
unrestricted filesystem paths. DTOs must represent slide IDs absent from the
current PDF.

SSE events carry a sequence ID, deck token when applicable, and a source
revision or job ID. Events are hints to refetch; on reconnect or a sequence
gap, refetch snapshots and active job statuses. Coalesce progress events.

## Editing and conflict rules (Phase 4; server side in Phase 1)

1. Key drafts by deck token and slide ID, with a browser-local segment key for
   input identity. Don't add UI IDs to the sidecar format.
2. Autosave valid edits after a short debounce (start at 500 ms). Ctrl+S and
   actions that consume narration (preview, generate, export) flush and await
   an acknowledged revision. Typing never waits on the network.
3. Serialize saves per deck. A response acknowledges only the draft version it
   carried; newer keystrokes stay dirty. Drop late responses from obsolete
   deck/view sessions.
4. Every durable mutation checks its expected revision; the server re-reads
   before writing, writes atomically, and records the new revision only on
   success. Preserve existing serialization and review bookkeeping.
5. External reload updates clean state. A dirty draft is kept, and the user is
   shown both versions with explicit choices (keep mine / use file / reconcile).
   Never silently overwrite either side, including for a removed slide.
6. Show unsaved/saving/saved/conflict/error accurately. `beforeunload` is a
   warning fallback, not persistence.
7. *Recommended, may follow Phase 4:* local draft recovery (IndexedDB) with
   base revision and timestamp, restored after refresh/crash with a visible
   choice; deleted only on matching save acknowledgement or explicit discard.

Atomic replace prevents truncated files but is not a true compare-and-swap
against external programs that ignore locks; document that narrow race rather
than promising universal locking. Don't turn the sidecar into a database.

## Playback, artifacts, and jobs

- One `<audio>` element is the playback clock (Phase 3). Generation tokens stop
  a canceled or superseded preview from starting. A later edit invalidates the
  preview; stale results never attach to a newer revision.
- Preview artifacts are unique and immutable per job. Immutable hashed assets
  cache hard; HTML and snapshots revalidate. Keep review base images and
  per-deck media isolation; resolve paths under allowed roots, including
  symlink checks; reject unknown tokens.
- Jobs belong to the backend, not an SSE connection. Disconnects don't cancel
  or duplicate work. Deck switching still cancels session-owned generation
  while keeping completed clips; one tab leaving doesn't cancel another's
  work. Export survives navigation and is rediscoverable while the server runs.
- Cancelling an asyncio waiter doesn't stop a worker thread or subprocess;
  keep cooperative cancellation and subprocess cleanup, and distinguish
  "cancel requested" from "stopped". Bound concurrency per engine, preserving
  model reuse. Deduplicate synthesis by existing cache identities.
- Paid generation and forced regeneration require an explicit approved
  command; reconnects and autosave never authorize spending. Credentials stay
  in Python.

## Server operation and distribution

- Loopback by default; deliberate host overrides preserved. One origin for
  frontend, API, events, media. Validate Origin/Host for mutations and bind
  them to a same-origin session token; no wildcard credentialed CORS. Deck
  tokens are lookup IDs, not credentials.
- Coalesce file watching; keep the last good snapshot while a PDF recompiles.
  Debounce cache pruning; never prune artifacts in active use.
- SPA fallback serves `/` and valid deck routes on refresh; unknown API and
  asset URLs return real errors, not `index.html`.
- Bundle fonts/icons; no CDN fetches at runtime.
- A source checkout may need Node to rebuild the frontend; installing a
  published wheel or sdist must not.

## Validation

Regression scenarios, each assigned to the phase that makes it testable.
Local-only browser tests are marked (L).

- **Phase 0/4:** type without blur, externally edit the same or another block;
  the draft survives and the file isn't overwritten. Include a PDF recompile
  and a removed/renamed slide. (Vitest for store logic; (L) end to end.)
- **Phase 1:** conflicting writes with stale revisions → 409; concurrent
  previews get distinct immutable tracks; Range/206 and invalid ranges; job
  cancel/force-regenerate/idempotent create; shutdown leaves no orphan
  workers/subprocesses. (API tests, CI.)
- **Phase 2:** built wheel installed in a clean venv without Node opens a deep
  link and loads all assets. (Packaging smoke test.)
- **Phase 3:** multiple short cues, seek both ways, change speed, pause, tab
  visibility, stop during a pending build; no stale job starts playback.
  (Vitest for the controller; (L) end to end.)
- **Phase 4:** type during an in-flight slow save, switch decks, fail a save;
  no newer edit is falsely marked saved. Two tabs, conflicting writes.
  Keyboard-only navigation, focus retention, dialogs, pane resize, narrow
  windows, long narration, Unicode/RTL text. Export blockers and draft export.
- **Phase 5:** review start/message/accept/reopen/filter/diff/removed-slide and
  declared-uncompiled flows; CLI interoperability.

Performance: report numbers on a stated fixture and machine. Use a synthetic
200-page deck with several utterances per page. Typing, resizing, and seeking
must not wait on the network; opening one slide must not wait for the whole
deck to rasterize. Virtualize the filmstrip only if measurements justify it.

## Per-phase handoff

At each checkpoint the implementing agent reports: what changed, exact
validation commands and results (including any pre-existing failures,
investigated and named — never silently skipped), updated parity checkboxes,
known limitations, and representative screenshots. Old tests are never
deleted to get green; each replaced test maps to its new coverage.
