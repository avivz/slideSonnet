# Frontend migration: implementation handoff

- Date: 2026-09-28
- Baseline: `1b4442a` on `feat/review-loop`
- Document branch: `docs/frontend-migration`

## Objective and delivery scope

Replace the NiceGUI frontend with a Vue 3 application backed by the existing
Python domain code. Deliver the complete transition in one implementation
branch and one release. Internal milestones below are implementation order,
not separate releases or requests for approval. Do not stop at a prototype,
an API skeleton, or a player embedded in the old frontend.

The finished product must still launch with `slidesonnet edit`, work locally,
and support the existing library, narration editor, review workflow, preview,
generation, and export. Keep the current visual design and information layout
recognizable. Improve interaction reliability without combining this migration
with a product redesign.

Retain the Python CLI, PDF processing, sidecar format, review records, TTS
engines, audio cache, shared pool, subtitle timing, and FFmpeg export pipeline.
Do not add accounts, cloud hosting, collaboration infrastructure, a database,
SSR, or a desktop shell. The current browser/app-window launch support remains.

## Decisions

| Concern | Choice |
|---|---|
| Frontend | Vue 3 single-file components, Composition API, strict TypeScript |
| Build | Vite; npm with a committed lockfile and documented supported Node version |
| Navigation | Vue Router; retain `/` and `/d/{token}` URLs |
| Shared UI state | Pinia; separate server snapshots, local drafts, jobs, and playback |
| Presentation | Port existing CSS tokens/layout; use semantic HTML and accessible controls |
| Backend | FastAPI application factory, Uvicorn, explicit Pydantic request/response models |
| Commands | HTTP JSON API under `/api/v1`; generate TypeScript DTOs from OpenAPI |
| Updates | Server-Sent Events (SSE) for source changes and job progress |
| Media | Same-origin HTTP with byte-range support and versioned artifact URLs |
| Testing | Existing Python tests, API tests, Vitest, and Playwright browser journeys |
| Installation | Compiled frontend bundled in the Python distribution; no Node at runtime |

Vue's official scaffold supports Vite, TypeScript, Router, Pinia, and test
tooling. See the [Vue quick start](https://vuejs.org/guide/quick-start).
Vite builds static production assets; FastAPI supports mounting static files.
See [Vite production builds](https://vite.dev/guide/build.html) and
[FastAPI static files](https://fastapi.tiangolo.com/tutorial/static-files/).
These capabilities support this design; the ownership and lifecycle rules
below are project-specific recommendations.

Use a small dependency set. Do not reproduce Quasar's entire component system
just to retain its appearance. Do not introduce another state/query framework
alongside Pinia unless a concrete implementation need justifies it.

## Why this migration is worthwhile

The Python core already provides useful separation through `api.py`, the
narration models, rendering modules, and review operations. Preserve it.
The frontend has accumulated roughly 3,000 lines in `gui/app.py`, plus state,
review UI, and JavaScript helpers. The problem is not just file size:
browser interaction and server operations share too much mutable state.

Specific issues to resolve during the transition:

1. **Draft loss on external edits.** In `EditorView._poll_sources`, a changed
   sidecar causes a reload and a complete editor rebuild. Unlike the explicit
   save-conflict path, this does not preserve live input. A temporary NiceGUI
   simulation reproduced a field changing from `MY UNSAVED DRAFT` to
   `External text.` after an external write. Make this a permanent regression
   scenario in the new browser suite.
2. **Split playback timing.** Python handles audio `timeupdate` events and
   changes the selected slide; `static/morph.html` drives transitions against
   the browser audio clock. The resulting visual timing depends partly on
   server round trips. Move all transport visuals to one browser controller.
3. **Work on the UI event path.** Saving invokes serialization, reload,
   review bookkeeping, and cache pruning. Move blocking file/media operations
   off the async server event loop, and avoid unnecessary full-deck refreshes.
4. **Browser coverage missing from CI.** Existing Playwright journeys are
   excluded by `.github/workflows/ci.yml`. The new frontend needs a small,
   deterministic browser suite in CI.

Evidence limits: the preceding review passed Ruff and strict mypy, but broader
test runs stalled and were interrupted. The draft-loss assertion reproduced;
its temporary test run also stalled during completion. No complete browser
usability review or performance benchmark was performed. Establish a fresh
baseline rather than treating the old suite as known green.

## Code to read and preserve

Paths are relative to the repository root. Existing behavior and tests are the
source of truth where this document does not explicitly change a behavior.

| Existing code | Migration treatment |
|---|---|
| `src/slidesonnet/api.py` | Keep public Python API; wrap operations in HTTP/service adapters |
| `gui/app.py` | Inventory all controls and behaviors; replace UI and route wiring |
| `gui/state.py` | Extract reusable operations; eliminate server ownership of UI selection/drafts |
| `gui/library.py` | Reuse bounded discovery, natural ordering, registry, and stable deck tokens |
| `gui/jobs.py` | Reuse useful queue concepts; make lifecycle independent of browser connections |
| `gui/review.py`, `review/*` | Preserve review semantics and on-disk compatibility |
| `gui/review_panel.py` | Port the full review interaction surface |
| `gui/launch.py`, `gui/devserver.py`, `cli.py` | Preserve launch options; adapt development startup |
| `gui/static/editor.css`, `theme.py` | Reuse visual tokens and layout intent; remove framework selectors |
| `gui/static/morph.html` | Port effects to typed browser code, with explicit lifecycle cleanup |
| `audio/*`, `video/*`, `render.py`, `timing.py` | Preserve synthesis/assembly/export timing logic |
| `deck.py`, `narration/*`, `cache.py`, `clean.py`, `pool.py` | Preserve formats, cache keys, and preservation rules |
| `tests/test_gui*.py`, `tests/test_browser_journeys.py` | Map each meaningful behavior to a retained or replacement test |

Inspect the branch's actual review implementation, including newly declared
slides that have not yet been compiled. Do not assume all review slide IDs
are present in the current PDF. Do not depend on untracked `dev/` documents
from somebody else's checkout.

## Ownership and module boundaries

Suggested structure; adjust names without weakening the boundaries:

```text
frontend/
  src/api/                  # generated DTOs, fetch wrapper, SSE client
  src/stores/               # snapshots, drafts, preferences, jobs
  src/features/library/
  src/features/editor/
  src/features/playback/    # controller, cue lookup, transition effects
  src/features/review/
  src/components/          # shared controls, dialogs, resizable panes
  src/styles/
  tests/
src/slidesonnet/server/
  app.py                    # create_app, lifespan, static assets
  schemas.py
  routes/                   # decks, editing, jobs, review, media, events
  services/                 # explicit operations over existing Python core
  jobs.py
  events.py
  static/                   # generated frontend output, packaged recursively
```

The browser owns selection, focused field, unsaved draft values, open panels,
filter text, playback position, scrub state, and presentation preferences.
Python owns durable documents, validation, source revisions, diagnostics,
media artifacts, synthesis, export, and review records. Keep an immutable
acknowledged snapshot separate from editable browser drafts.

Backend operations must take explicit deck/slide identifiers and engine
options. Do not expose a shared `EditorState.index` or selected engine that
one tab can change underneath another request. A service may adapt existing
helpers internally, but mutable operation context must be isolated.

Use a FastAPI app factory with explicit registry and job-manager lifetimes.
Avoid process-global application instances that leak state between tests.
One supported local server process is sufficient; do not add distributed jobs.

## Feature parity inventory

Before removing NiceGUI, maintain a checked parity list referencing tests.
At minimum cover these behaviors:

| Area | Required behavior |
|---|---|
| Launch/library | All current `edit` target forms, `--root`, host/port, no-browser, custom browser, WSL, app-window and development modes; bounded discovery; stable deep links |
| Navigation | Buttons, arrows with typing-safe shortcuts, filmstrip, Ctrl+K filtering, Alt+left/right deck switching; preserve pending edits |
| Layout | Slide aspect ratio, dark theme, resizable/collapsible panes, responsive pane restoration, long-deck scrolling |
| Narration | Add/delete/reorder utterances and pauses; text, direction, voice, pace; leading/trailing silence; inherited/default values; explicit save and automatic save |
| Transitions | Existing effect families/directions/durations; shared boundary ownership; first/last slide behavior; single-slide preview toggle |
| Voices/TTS | Named voice management and per-engine mappings; backend selection; cache badges; per-utterance/per-slide/all-missing generation; force regeneration; warmup/errors; local-only auto-build; paid-operation confirmation |
| Playback | Single/deck preview, start at current slide, play/pause/resume/stop, seek, speed, edit invalidation, obsolete build cancellation, editing while preview plays |
| Diagnostics/orphans | Per-slide and deck diagnostics; unattached narration attach/append/delete; missing/unmarked/duplicate slide handling |
| Review | Start/clear review, conversations and messages, turn/status badges, accept/reopen/show closed, filtering, next-your-turn, before/after and word diffs, removed-slide views, declared uncompiled slides, external review changes |
| Export | Current readiness checks and blockers, explicit draft export, progress/errors, existing output naming, subtitle and transition behavior |
| Files | Live PDF/sidecar/config/review refresh; malformed/intermediate writes retain last good state and show useful errors |

Prefer existing test markers as `data-testid` values where useful. Preserve
keyboard focus and native text undo during background updates; avoid
recreating input components just because a job badge changed. Dialogs need
keyboard navigation, accessible names, focus trapping, and focus restoration.

## API contract

Define and test the contract before building most components. Route names
below are a proposed shape, not a second source of domain logic:

| Route | Purpose |
|---|---|
| `GET /api/v1/library` | Registered decks, grouping, scan limitations |
| `GET /api/v1/decks/{token}` | Snapshot, revisions, pages, narration, diagnostics, capabilities |
| `PATCH /api/v1/decks/{token}/slides/{slide_id}` | Validated block edit with expected revision |
| `POST /api/v1/decks/{token}/commands` | Discriminated commands for voice/orphan operations |
| `POST /api/v1/decks/{token}/jobs` | Generate, preview, export, or render-page job |
| `GET /api/v1/jobs/{job_id}` | Authoritative status, result, error, progress |
| `POST /api/v1/jobs/{job_id}/cancel` | Explicit cooperative cancellation |
| `GET /api/v1/decks/{token}/review` | Review state and diffs |
| `POST /api/v1/decks/{token}/review/commands` | Typed adapters to existing review operations |
| `GET /api/v1/events` | Deck/job/source events, filtered to the subscribing session's needs |

Use typed, discriminated command bodies rather than arbitrary dictionaries or
Python method names. Represent errors with stable codes and user-readable
messages. Return 404 for unknown resources, 422 for invalid input, and 409
for an expected-revision mismatch. Never serialize secrets or unrestricted
filesystem paths into a snapshot.

Snapshots should include separate source revisions where useful: narration,
PDF, config, and review. Revisions for durable edits must be based on content,
not only `(mtime, size)`. DTOs must represent IDs absent from the current PDF.
Generated types need a reproducible update command and a CI drift check.

SSE events carry sequence/event ID, server-instance ID, deck token when
applicable, source revision or job ID, and a typed payload. Events are hints
to update/refetch state; a missing event must not permanently corrupt state.
On reconnect or a sequence gap, fetch authoritative snapshots and active job
statuses. Clean up streams on shutdown; coalesce progress rather than emitting
one UI event per synthesized audio sample.

## Editing and conflict rules

Implement these rules before enabling autosave:

1. Key drafts by deck token and slide ID, with a browser-local segment key
   for stable input identity. Do not change the sidecar format to add UI IDs.
2. Save valid edits after a short debounce (start with 500 ms). Ctrl+S and
   actions consuming narration flush the draft immediately and await an
   acknowledged revision. Typing must never wait for network completion.
3. Serialize saves per deck. Each request captures the submitted draft
   version; its response acknowledges only that version, leaving any newer
   keystrokes dirty. Discard late responses from obsolete deck/view sessions.
4. Every durable mutation checks its expected revision. Serialize in-process
   writes per deck, re-read before writing, and write via a same-directory
   temporary file plus atomic replace. Preserve existing serialization and
   review bookkeeping semantics. Record the new revision only after success.
5. External reload updates clean state. If a relevant draft is dirty, retain
   it and show both versions with explicit choices to keep editing, use the
   external version, or apply a reconciled draft against the latest revision.
   Never silently overwrite either version, including for a removed slide.
6. Store recoverable drafts locally (IndexedDB is suitable), including base
   revision and timestamp. Restore after refresh/crash with a visible recovery
   choice; delete recovery data only after the matching save acknowledgement
   or explicit discard. Handle unavailable storage without claiming recovery.
7. Show unsaved/saving/saved/conflict/error states accurately. `beforeunload`
   is a warning fallback, not the persistence mechanism. Navigation may retain
   a recoverable draft, but must not falsely claim it was saved to the sidecar.

Atomic replacement prevents truncated files; it does not create a true CAS
against arbitrary external programs that ignore locks. Document that narrow
race honestly. Coordinate slideSonnet-owned writers where feasible, and test
external edits before the commit check without promising universal locking.
Do not turn the sidecar into an internal database.

## Playback, artifacts, and jobs

Use one HTML audio element as the playback clock. A browser controller derives
the displayed slide, transition state, scrubber, and labels from `currentTime`.
Use requestAnimationFrame while visible/playing and resynchronize on seek,
pause, resume, rate change, and visibility change. Do not send playback ticks
to Python. Clean up animation callbacks and media listeners on unmount.

Return a preview manifest containing artifact ID, source revisions, media
URL, duration, cues, page image URLs, and transition schedule. Python computes
the schedule from existing timing logic; the browser renders it. Reuse effect
semantics from `morph.html`, but distinguish approximate browser transitions
from FFmpeg output. Do not claim sample-accurate browser visuals.

Separate the playback slide from the editing slide. Following playback must
not destroy focused inputs; preserve the existing edit-safe following behavior.
Use generation tokens to prevent a canceled or superseded preview from starting.
Flush saves before preview/generation/export and bind the job to that accepted
revision. A later edit invalidates the preview; stale results must not attach
to the new document revision.

Preview jobs need unique immutable artifact paths. Rewriting a shared
`track.wav` behind different query strings is insufficient when tabs or jobs
overlap. Serve audio with tested Range/206 and invalid-range behavior. Cache
immutable hashed assets aggressively; HTML and mutable snapshots revalidate.
Keep review base images and per-deck media isolation. Resolve paths beneath
allowed artifact roots, including symlink checks, and reject unknown tokens.

Jobs belong to the backend rather than an SSE connection. Temporary disconnects
must not cancel or duplicate generation. Preserve explicit deck-switch
cancellation of session-owned generation while keeping completed cached clips;
one tab leaving must not cancel another tab's work. Define ownership/subscriber
references when jobs are deduplicated. Export survives view navigation and is
rediscoverable while the server remains running.

Give each job an immutable input snapshot, ID, status, progress, result/error,
and cancellation signal. Cancelling an asyncio waiter alone does not stop a
worker thread or subprocess. Retain cooperative cancellation and subprocess
cleanup; distinguish requested cancellation from confirmed completion. Bound
concurrency according to engine capabilities, preserving model reuse.

Deduplicate synthesis by existing cache identities. Make retried job creation
idempotent within the server session, including after a lost response. Paid
generation and forced regeneration require an explicit approved command;
reconnects and autosave must never authorize spending. Keep credentials in
Python and retain the existing test guards against real paid calls.

## Server operation and distribution

Keep loopback as the default host and preserve deliberate host overrides.
Serve frontend, API, events, and media on one origin in production. Validate
origins/hosts for local write access; do not enable wildcard credentialed CORS.
Bind mutations to a same-origin session/request token. Opaque deck tokens are
lookup identifiers, not authorization credentials. Development proxy rules
must also support SSE without buffering.

Run blocking parsing, hashing, rasterization, assembly, and export outside the
async event loop. Preserve synchronization around mutable models and file
writes when offloading. Coalesce file watcher/polling updates and keep the last
good snapshot while a PDF is mid-recompile. Debounce cache pruning and ensure
it cannot remove artifacts in active use.

Production must use Uvicorn serving bundled assets, not a Vite development
server. Add explicit FastAPI/Uvicorn and schema dependencies rather than
depending on NiceGUI's transitive installation. Remove NiceGUI from runtime
dependencies when the transition is complete.

Build the frontend into `src/slidesonnet/server/static/` using a reproducible
build command. Include nested JS/CSS/font/image assets in wheels and sdists;
the current `gui/static/*` packaging glob is not sufficient. For a release:
build assets first, build wheel and sdist, then verify rebuilding a wheel from
the sdist works without Node. A source checkout may require Node to rebuild
the frontend; installing a published wheel/sdist must not. Fail clearly if a
developer launches an unbuilt checkout. Bundle fonts/icons required for normal
operation rather than fetching UI dependencies from CDNs at runtime.

SPA fallback serves `/` and valid deck-page routes on refresh. Missing API
routes and missing asset URLs must return real errors, not `index.html`.
Preserve custom browser and WSL/app-window invocation and shutdown behavior.
Update README, Makefile, dev startup, publish workflow, dependency locks, and
package-data rules together. Audit NiceGUI storage preferences and migrate
recognized non-sensitive values once where practical; document any reset.

## Implementation order within the single migration

1. Establish the baseline and feature/test inventory. Reproduce draft loss;
   record existing test failures/timeouts and capture representative UI views.
2. Extract Python services and build the API, schemas, revisions, media routes,
   job lifecycle, event stream, and app factory. Test without a frontend.
3. Scaffold Vue and implement library, routing, layout, snapshots, and durable
   drafts. Prove save/reload/conflict behavior before adding auto-generation.
4. Implement narration, voices, diagnostics, orphans, generation, and export.
5. Implement browser-owned playback and all transition/scrub/speed behavior.
6. Port the complete review workflow and external change synchronization.
7. Integrate packaging and CLI launch, migrate tests, and run parity checks.
8. Remove obsolete NiceGUI UI, assets, plugin fixtures, dependencies, and
   documentation after replacements pass. Keep framework-independent tests
   and logic, relocating them if necessary. Finish with one default frontend.

Do not simply delete old tests to obtain green CI. Map replaced tests to their
new coverage; preserve domain assertions even when their UI harness changes.
Do not leave permanent dual-frontend support or a feature flag as the finished
deliverable. Rollback is the previous release/commit, with compatible files.

## Validation and acceptance

Use deterministic PDFs and generated short audio fixtures for ordinary CI.
No paid API calls, model downloads, or real TTS engines in browser smoke tests.
Keep heavier real-engine and FFmpeg integration checks as explicit tiers.
New browser tests should exercise the production frontend against the real
Python API, with synthesis stubbed at the existing engine boundary.

Required regression scenarios:

- Type without blur, externally edit the same block or another block, and
  wait for refresh. The draft remains recoverable and the external file is
  not overwritten. Include a PDF recompile and a removed/renamed slide.
- Type while a save is in flight; return responses slowly; navigate between
  decks; fail a save; refresh and recover. No newer edit becomes falsely saved.
- Open two tabs and issue conflicting writes. Detect revisions without
  sharing selection/engine state. Reconnect without duplicate synthesis.
- Play multiple short cues, seek in both directions, change speed, pause,
  switch tabs/visibility, and stop during a pending build. No stale job starts
  playback and no server tick is needed for slide changes.
- Build previews concurrently for different slides/tabs. Each plays its own
  immutable track; verify media ranges, refreshed images, and cache behavior.
- Generate, cancel, force-regenerate, switch decks, and disconnect. Verify
  engine cancellation boundaries, cache preservation, idempotency, and paid
  confirmation rules. Shut down without orphan workers/subprocesses.
- Exercise review start/message/accept/reopen/filter/diff/removed-slide and
  declared-uncompiled-slide flows; retain on-disk/CLI interoperability.
- Exercise all export blockers, explicit draft export, progress, and errors.
- Run the packaged application outside the repository with Node unavailable;
  open a deep link, load all assets, seek audio, and use the library/editor.
- Test keyboard-only navigation, focus retention, dialogs, pane resizing,
  narrow windows, long narration, and Unicode/RTL text without content loss.

Report performance on a stated fixture and machine, not invented numbers.
Use a synthetic 200-page deck with several utterances per page. Check that
typing, resizing, and seeking do not wait for network requests; opening one
slide must not await rasterizing the entire deck. Profile long tasks, excessive
full-deck rerenders, and unbounded DOM/image loading; virtualize the filmstrip
if measurements justify it. Record cold versus cached startup separately.

Completion gates:

- [ ] Every parity item has an implemented behavior and referenced check.
- [ ] Python lint/type checks and relevant retained tests pass; existing
      failures are investigated and accurately reported, not silently skipped.
- [ ] Frontend lint, `vue-tsc`, Vitest, production build, and DTO drift check pass.
- [ ] Deterministic Playwright smoke tests run in CI against the new stack.
- [ ] Conflict, job lifecycle, media isolation, and artifact tests pass.
- [ ] Wheel and sdist packaging/install smoke tests pass without Node at runtime.
- [ ] Normal UI operation works without CDN/network access, apart from explicitly
      requested network TTS/model acquisition.
- [ ] NiceGUI is absent from the final runtime and test harness; retained
      Python domain behavior and file formats remain compatible.
- [ ] README, development commands, release workflow, and change notes match
      the delivered application.

The implementing agent's final handoff should state what changed, list exact
validation commands/results, identify any unresolved limitations, and include
representative screenshots. A partial parity list is unfinished work, not a
completed migration.
