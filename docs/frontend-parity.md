# Frontend parity inventory

Companion to [`frontend-migration.md`](frontend-migration.md). Every behavior the
NiceGUI editor has today, the tests that pin it, and what happens to those
tests in the port. A box is checked when the Vue frontend implements the
behavior **and** its replacement check exists.

## Baseline (Phase 0, 2026-09-28, `main` @ `3cacdb5`)

Machine: the maintainer's WSL2 laptop. Serial runs, warm caches.

| Tier | Command | Result | Wall time |
|---|---|---|---|
| Unit (CI tier) | `make test-unit` | 1029 passed, 57 deselected | 148 s |
| Browser (local) | `make test-browser` | 20 passed | 143 s |
| Integration (local) | `pytest -m integration` | 36 passed, 1 skipped | 168 s |

All three tiers are green; no pre-existing failures or timeouts. Reference
screenshots (library, editor, slide 2, 900 px window) are in the untracked
`dev/frontend-baseline/`.

Frontend-facing tests today: **~330 of ~1,090** (`test_gui.py` 83,
`test_gui_state.py` 82, `test_gui_layout.py` 38, `test_gui_switching.py` 28,
`test_gui_library.py` 25, `test_browser_journeys.py` 20, `test_jobs.py` 16,
`test_gui_review.py` 16, `test_gui_browser_launch.py` 15,
`test_gui_review_model.py` 7). The rest (narration format, render, TTS, review
ops, CLI, clean, pool, …) are domain tests and are untouched by the migration.

## Progress by phase

Boxes below are checked only when the **Vue** frontend has the behavior. Test
moves that happen earlier are recorded here, so the mapping stays auditable.

### Phase 1 — services and API (`migration/phase-1`)

New tests (all CI tier, no NiceGUI): `test_server_api.py` (22),
`test_server_jobs.py` (9), `test_server_media.py` (12),
`test_server_previews.py` (4), `test_server_revisions.py` (4), plus
`test_proc.py` cancellation (2).

Moved or removed:

| Test(s) | Now | Why |
|---|---|---|
| `test_gui.py::test_morph_schedule_*` (2), `test_single_slide_morph_*` (3) | `test_server_previews.py` (2 tests) | the schedule is server code now; merged into two tables |
| `test_gui.py::test_replaying_preview_reloads_the_new_track` | dropped | pinned the `?t=` refetch workaround for B4; every build is its own immutable file now (`test_server_api.py::test_previews_are_immutable_per_build_*`, `test_server_previews.py::test_published_tracks_are_immutable_*`) |
| `test_gui_switching.py::test_each_deck_serves_its_own_page_images`, `test_media_route_refuses_*` (2), `test_assembled_track_is_never_cached_immutably`, `test_only_a_real_content_stamp_*` | `test_server_media.py`, `test_server_api.py::test_media_refuses_*` | the media route is plain FastAPI; tested without the in-process NiceGUI server |
| `test_gui_state.py::test_reload_reuses_page_ids_when_pdf_unchanged` | rewritten in place | revisions are content hashes: a touch without a content change no longer re-reads the PDF |

Bugs closed: **B3** (the orphaned-audio sweep left the save path — a save on
the basel demo went from ~15 ms to ~4.5 ms; the sweep grows with the audio
folder, so large decks gain more) and **B4** (content-addressed preview
tracks). New along the way: jobs can be cancelled for real — a cancelled job
kills its running ffmpeg/pdftoppm (tools run in their own process group) — and
every synthesis path takes a per-engine lock, always after the deck's render
lock, so the editor queue, API jobs, previews, and export never drive one
model from two threads.

### Phase 2 — toolchain, packaging, library in Vue (`migration/phase-2`)

New: `frontend/` (Vue 3, strict TS, Pinia, Vue Router, Vitest, ESLint,
`vue-tsc`), 28 Vitest tests in ~1.3 s; `test_server_frontend.py` (2);
`test_server_api.py::test_deck_stats_*` (1); `scripts/smoke_installed_frontend.py`
(CI, against a fresh wheel and sdist install).

| Test(s) | Now | Why |
|---|---|---|
| `test_gui_switching.py::test_library_*` (5), `test_empty_root_explains_*` | `frontend/tests/LibraryView.test.ts`, `library.test.ts`, API stats test | the library is a Vue page |
| `test_gui_switching.py::test_library_page_carries_the_leaving_handler` | dropped | guarded NiceGUI's connection-lost popup on a page that is no longer NiceGUI |
| `test_gui_switching.py::test_unknown_token_falls_back_to_the_library` | kept, lands on a placeholder | the editor route is still NiceGUI |

Bug closed: **B5** (recursive package data; wheel and sdist both carry the
built bundle, verified by installing each in a clean venv). Found in the
port: phantom decks from pre-1.0 `cache/` folders (fixed).

The library layout follows `docs/frontend-design.md` — built to that brief
without a separately approved mockup, because the maintainer asked for
Phases 1–3 before reviewing; it is the thing to react to at this checkpoint.

### Phase 3 — browser-owned playback (`migration/phase-3`)

New: `frontend/src/features/playback/` — `cues.ts`, `morph.ts` (the
transition effects, ported from `gui/static/morph.html`, which is deleted),
`controller.ts` (one `<audio>` clock; slide, overlay, scrubber, and clock
derived per animation frame), `dom.ts`, and `embed.ts`, built to
`/ui/embed/playback.js` and loaded by the NiceGUI editor. 23 Vitest tests
(cue lookup table, effects table, controller: slide reporting, seeks both
ways, seek-to-slide, start-at, rate pinning, pause/resume/stop, stale plays,
hidden-tab resync, listener cleanup; overlay and transport DOM).

| Test(s) | Now | Why |
|---|---|---|
| `test_gui.py::test_seek_bar_tracks_position_and_resets_on_stop` | dropped | position and clock are drawn in the browser; covered by `playback.test.ts` (transport) and browser `test_transport_play_stop_and_deck_cue_flip` |
| `test_gui.py` player-reset tests (5) | keep; assert the transport's `data-loaded` instead of the old slider | the Python side still owns load/stop |
| `test_gui.py::test_deck_playback_cue_flip_saves_*`, `test_cue_flip_is_deferred_*` | keep until Phase 4; driven by the `ssslide` event instead of `timeupdate` | the NiceGUI editor still follows the player (once per slide now) |
| browser `test_editing_during_deck_playback_*` | extended | now also asserts the stage shows the playing slide while the editor's follow is deferred — the B2 regression check |
| browser morph journeys (2) | check `data-morph` on the overlay | the overlay also holds the playing slide during deck previews now |

Bug closed: **B2** — no playback tick reaches Python; the stage flips on the
audio clock in the browser, and Python hears one `ssslide` event per slide
change (to move the editor along, deferred while a field is focused).

### Phase 4 — the editor in Vue (`migration/phase-4`)

Opt-in while Phase 5 brings over the review panel: `slidesonnet edit
--frontend vue` (or `SLIDESONNET_FRONTEND=vue`). The default flips when the
review tab is in (end of Phase 5); the flag goes in Phase 6.

Backend additions: the per-deck **generation queue** (`server/generation.py` —
`gui/jobs.JobQueue` owned by the server, one per deck × engine, shared by tabs,
with owner-scoped cancel for "leaving drops only my clips"), `/meta`
(transition gallery, engines), `/engines/{e}/voices`, `/decks/{t}/pages`,
generation status/enqueue/cancel/focus routes, `warm` and nearest-first
`render_pages` jobs, and snapshot extras (per-clip audio, resolved voice
labels, silence defaults, model warm, neighbours, page aspect).

Frontend: `stores/editor.ts` (drafts, autosave, rebase/conflict),
`stores/generation.ts` (queue + auto-generate), `stores/player.ts` (preview
jobs + the Phase 3 controller + following), `features/playback/transport.ts`
(the play-button state machine), and the editor components.

New tests: Vitest `editorStore.test.ts` (7), `transport.test.ts` (10 cases),
`editorComponents.test.ts` (9); browser `test_browser_vue.py` (7 journeys:
navigation keys, typing autosave without blur, **B1 end to end** — an outside
edit while typing shows both versions and overwrites neither, block editing,
generation badge, real-audio transport + deck follow, keyboard deck
switching); `test_server_api.py` generation/meta tests (3); `test_jobs.py`
owner cancel (1).

Rows now implemented in Vue (their boxes flip when NiceGUI is removed in
Phase 6, together with the retired tests): navigation, layout/panes, narration
editing and saving, transitions, voices/engines, generation/auto-build/jobs,
playback, diagnostics/orphans/live files, export. Not yet: review (Phase 5).

### Phase 5 — review in Vue (`migration/phase-5`)

Backend: `server/review.py` — one cached `ReviewModel` per deck, a read model
(`GET /decks/{t}/review`: conversations, changes, unfiled, **pending** —
declared in an open conversation but in neither base nor PDF — badges, base
order, base images, word diffs) and typed author commands (`POST
.../review/commands`: start, comment, reply, accept, reopen, clear,
file_unrequested; comment and reply send at once, as before). On-disk format
and CLI untouched (`review/ops.py` does every write).

Frontend: `stores/review.ts` (strip with removed slides after their old
predecessor, conversation filter, arrows within it, next-your-turn, removed
slide view), `ReviewPanel.vue`, compare view on the stage (D toggles
before-only), narration word diff, filmstrip review badges and moved marks,
console Audio | Review tabs with a waiting count.

Tests: `test_server_review.py` (2: a full round incl. pending ids; filing +
refusals), Vitest `review.test.ts` (4), browser `test_a_review_round_with_the_agent`.

The Vue editor is now the default (`--frontend nicegui` opens the old one
until Phase 6).

### Phase 6 — NiceGUI removed (`migration/phase-6`)

The editor is FastAPI + Uvicorn (`server/app.py::create_app`, `server/run.py`)
serving the Vue app; `nicegui` is no longer a dependency. The pure modules
moved into `server/` (`library`, `launch`, `queue` — the per-clip generation
queue — and `review_model`); `gui/` is gone, as are the in-process `user`
plugin, the `gui` marker, and the `--frontend` flag.

Retired tests and where their behavior is covered now:

| Retired | Covered by |
|---|---|
| `test_gui.py` (76 in-process NiceGUI tests) | Vitest `editorStore`, `editorComponents`, `narration`, `transport`, `playback` tests; API tests; browser journeys (navigation, typing autosave, B1 conflict, block editing, generation badge, transport + follow, deck switching) |
| `test_gui_state.py` (82) | `test_server_editing.py` (13: boundary ownership, block edits, byte-stable hand edits, duplicates, unmarked pages, orphans, voices incl. rename + file paths, per-engine unmapped voices, statuses, review notes + audio sweep on save), `test_server_api.py` (engine choice, conflicts, jobs, pages, previews), Vitest `narration.test.ts` (edge silences) |
| `test_gui_layout.py` (38) | Vitest `transport.test.ts` (the 13 play-button state tests as one table); pane sizing and responsive collapse live in the Vue page (covered by the browser journeys' navigation and the narrow screenshot check); dev-mode tests replaced by `test_server_run.py` + `test_cli.py::test_edit_dev_*`; page aspect is part of the snapshot |
| `test_gui_switching.py` (16), `test_gui_review.py` (16) | Vitest library + review tests, browser `test_keyboard_deck_switching` and `test_a_review_round_with_the_agent`, API review tests |
| `test_error_showcase.py` (in-process) | the same file, rewritten against the API (5, incl. 2 real-Kokoro previews) |
| NiceGUI browser journeys (20) | `test_browser_journeys.py` (8, against the Vue editor) |
| `test_gui_browser_launch.py` (15) | `test_launch.py` (4 tests, 12 cases) |
| 3 registry-neighbour tests | 1 |
| 6 CLI `edit` tests | 1 table (4 cases) + 1 for `--dev` |

Found and fixed at the end: a PDF caught mid-recompile (missing or unreadable)
now gives a retryable 503 and the editor keeps its last good view; right-to-
left narration (Hebrew) lays out with `dir="auto"`.

### Final numbers (2026-09-28, the maintainer's WSL2 laptop)

| | Phase 0 (`main` @ `3cacdb5`) | After Phase 6 |
|---|---|---|
| Python unit tier (CI) | 1029 tests, 148 s | 839 tests, 35 s |
| Frontend (CI) | — | 90 Vitest tests, ~4 s; lint, `vue-tsc`, build |
| Browser tier (local) | 20 journeys, 143 s | 8 journeys, 105 s |
| Integration tier (local) | 36 passed + 1 skipped, 168 s | 34 passed + 1 skipped, 201 s (Kokoro load dominates) |
| Frontend-facing tests | ~330 | ~242 (152 Python + 90 Vitest) |

API timings on a synthetic 200-page deck (3 kB narration per slide): snapshot
24 ms (81 kB JSON), page list 3 ms, one slide save 106 ms — of which ~62 ms is
the `fsync` that makes the atomic save durable. Saves never block typing
(autosave runs after a pause, in the background), so no filmstrip
virtualization was needed.

## How to read the Tests column

- **keep** — UI-free logic (`gui/state.py`, `gui/library.py`, `gui/jobs.py`,
  `gui/launch.py`, `gui/review.py`). It moves into `server/services/` with its
  tests; only the import path changes.
- **port→API** — becomes an API/service test (FastAPI test client, CI).
- **port→Vitest** — becomes a Vitest store/component test (CI).
- **port→browser** — stays a real-browser journey (local only). Reserved for
  focus, timing, media, and keyboard paths a DOM simulation can't see.
- **drop** — redundant with another listed test, or pins a NiceGUI mechanism
  or a workaround the port removes. The reason is given.
- **merge** — collapse the listed tests into one parametrized test.

Target: the ~330 frontend-facing tests shrink noticeably. Estimates per area
are in the last column; the real count is reported at each checkpoint.

## Launch and library

| ✓ | Behavior | Current tests | Disposition |
|---|---|---|---|
| [x] | Browser choice: `--browser`, `$BROWSER`, WSL `wslview`, desktop default, `{url}` placeholder | `test_gui_browser_launch.py` (15) | keep; **merge** the 7 browser-choice tests and 3 `find_chromium` tests into two tables (15 → ~5) |
| [x] | App-window mode (`--app`) | `test_app_invocation_*` (3) | keep |
| [x] | Dev mode: watcher + worker, banner once, no reopen on reconnect | `test_gui_layout.py::test_dev_*`, `test_should_*`, `test_devserver_*` (7) | Phase 2 added `make frontend-dev` (Vite + proxy) for the Vue side; the NiceGUI dev server stays for the editor until Phase 6, then goes with its tests |
| [x] | Deck token stable, path-derived, spelling-independent | `test_gui_library.py::test_token_*` (2) | keep |
| [x] | Bounded discovery: nesting, dot/vendor pruning, depth/visit caps, natural sort, missing root | `test_gui_library.py` discovery tests (10) | keep |
| [x] | Registry: resolve, refuse unregistered, explicit deck/sidecar, neighbours wrap, rescan, grouping | `test_gui_library.py` registry tests (13) | keep; **merge** the 3 neighbour tests |
| [x] | Library page: grouped by week, card opens deck, size + remaining, unnarrated count, PDFs without narration, empty-root help | `frontend/tests/LibraryView.test.ts` (4), `library.test.ts`; `test_server_api.py::test_library_and_snapshot_*`, `test_deck_stats_*`; browser `test_library_card_opens_a_deck` | done in Phase 2. The browser journey stays until Phase 4: it is the one check that a Vue page hands off to the NiceGUI editor |
| [x] | **Bug:** PDFs in `*/cache/slides` folders are listed as phantom "no narration yet" decks | `test_gui_library.py::test_prunes_dot_dirs_and_vendor_dirs` | fixed in Phase 2: the pre-1.0 `cache/` folder is pruned from discovery |
| [x] | Unknown token falls back to the library | `test_unknown_token_falls_back_to_the_library` | port→Vitest (router) |

## Navigation and layout

| ✓ | Behavior | Current tests | Disposition |
|---|---|---|---|
| [x] | Prev/next buttons, arrows (typing-safe), filmstrip jump | `test_navigation`, `test_filmstrip_jump`, `test_nav_direction_*` (3); browser `test_navigate_via_buttons_keys_and_filmstrip` | port→Vitest (**merge** nav-direction into one table); keep **one** browser journey for real key events |
| [x] | Deck switcher: header name, Alt+←/→ wrap, Ctrl+K palette filter, "nothing matches", lone deck disables arrows | `test_gui_switching.py` (7), filter tests (2); browser `test_alt_arrow_*`, `test_ctrl_k_*` | port→Vitest; **merge** browser Alt/Ctrl+K into one keyboard journey |
| [x] | Switching saves the current slide first; stops generation without prompting | `test_switching_saves_*`, `test_switching_stops_*` | port→Vitest (flush-before-navigate) + API (session-owned jobs cancelled) |
| [x] | Panes: collapse/expand buttons, remembered width, clamp order, responsive collapse/restore | `test_in_panel_collapse_buttons`, `test_toggled_width_*` (3), `test_clamp_*` (4), `test_responsive_*` (4); browser `test_pane_collapse_and_expand` | port→Vitest; **merge** the 11 pure-layout tests into 2 tables; **drop** the browser journey (DOM sim covers it once layout is client-side) |
| [x] | Slide aspect ratio | `test_page_aspect_*` (2) | keep |
| [x] | Slide/cards splitter | `test_stage_has_draggable_slide_editor_divider` | port→Vitest |
| [x] | Status flash on the bottom bar | `test_action_messages_flash_on_the_bottom_bar` | port→Vitest |
| [x] | NiceGUI "connection lost" popup suppressed while leaving | `test_pages_suppress_*`, `test_*_carries_the_leaving_handler` (3) | **drop** — NiceGUI websocket mechanism; no equivalent in the SPA |

## Narration editing and saving

| ✓ | Behavior | Current tests | Disposition |
|---|---|---|---|
| [x] | Text edit persists; Ctrl+S saves the focused field | `test_edit_persists`, `test_ctrl_s_saves_the_field_being_typed` | port→Vitest (draft store + save) + API (`PATCH` slide) |
| [x] | Add/delete/reorder utterances and pauses; per-utterance voice/pace/direction | `test_per_utterance_voice_and_pace_persist`, `test_added_utterance_round_trips_unset_voice`; browser `test_block_editing_add_attrs_reorder_delete` | port→API for persistence; port→Vitest for the card list; keep the browser journey (reorder + focus) |
| [x] | Leading/trailing silence fields materialize on save | `test_per_slide_silence_fields_*`; state `test_split_edge_silences_*`, `test_bracket_silences_*` | keep state tests; port→Vitest for the fields |
| [x] | No-op save writes nothing; one block's edit leaves others byte-stable | state `test_no_change_save_is_a_noop`, `test_editing_one_block_leaves_the_other_raw`, `test_save_returns_true_on_normal_write`, `test_save_on_unmarked_page_*`, `test_replace_block_*` (3) | keep (service tests) |
| [x] | Draft survives background updates (badge, recompile, poll) | `test_pdf_only_refresh_keeps_narration_field`, `test_ctrl_s_saves_without_rebuilding_field` | **drop** both — they guard against NiceGUI rebuilding widgets; replace with one Vitest "background snapshot update never touches a dirty draft" test |
| [x] | External sidecar edit: elsewhere keeps the draft; same slide hands it back with Keep/Copy; save after external edit refuses | `test_external_edit_elsewhere_*`, `test_external_edit_to_the_same_slide_*`, `test_save_after_external_sidecar_edit_*`; state `test_save_refuses_*`, `test_non_block_save_also_refuses_*`; browser `test_external_sidecar_edit_reloads_live` | state → API (409 on revision mismatch); GUI → Vitest (conflict UI); keep **one** browser journey covering type-without-blur + external write (the B1 regression) |
| [x] | Typing survives a recompile that drops the slide (lands in the tray) | `test_typing_survives_recompile_that_drops_the_slide` | port→Vitest + API |
| [x] | Under review, own saves are filed; outside review touch nothing | state `test_own_narration_save_is_noted_in_review`, `test_saves_outside_review_touch_nothing` | keep |
| [x] | Local clips orphaned by an edit are pruned; paid audio kept | state `test_editing_an_utterance_prunes_stale_local_audio` | keep (plus: prune never removes in-use artifacts, Phase 1) |

## Transitions

| ✓ | Behavior | Current tests | Disposition |
|---|---|---|---|
| [x] | Family + direction picker persists | `test_transition_picker_family_and_direction_persist`; browser `test_transition_out_family_and_direction_persist` | port→Vitest; **drop** the browser duplicate |
| [x] | Incoming transition = previous slide's out; editing it writes there; first slide keeps its own; unchanged doesn't rewrite | state tests (5); browser `test_incoming_transition_matches_previous_slide_out` | keep state tests; **drop** the browser duplicate |
| [x] | Morph schedule: only animated boundaries, clamp to span, single-slide in/out, black frame at ends, toggle gates it, toggle defaults off | `test_morph_schedule_*` (2), `test_single_slide_*` (4) | keep the schedule as Python (manifest); **merge** into one table; toggle default → Vitest |
| [x] | Morph overlay animates during preview; single-slide gating | browser `test_transition_morph_overlay_*`, `test_single_slide_preview_transitions_gated_*` | **merge** into one browser journey (Phase 3) |

## Voices and engines

| ✓ | Behavior | Current tests | Disposition |
|---|---|---|---|
| [x] | Voices dialog: add, delete, rename (rewrites refs), byte-stable no-op, qwen3 path relative, clears unmapped warning | GUI `test_voices_dialog_*`, `test_changing_a_named_voice_uncaches_*`; state `test_edit_voices_*` (6) | keep state tests (service); GUI → Vitest dialog test (1–2) |
| [x] | Voice picker: named voices only, labels engine voice, "default" option + resolved label, picking default clears | GUI `test_picker_labels_*`, `test_voice_box_*` (3); state `test_editor_voice_options_*` (2), `test_editor_default_voice_label_*`, `test_resolved_engine_voice_*` | keep state; **merge** the 4 GUI picker tests into one Vitest table |
| [x] | Engine picker switches the session engine; re-points cost gates and cache lookup; config engine used otherwise | GUI `test_engine_picker_*`; state `test_actions_let_on_disk_config_*`, `test_gui_engine_pick_*` (2), `test_jobs_context_uses_*`, `test_backend_options_*` | keep state; the "session engine" becomes an explicit request field (no shared state) — rewrite as API tests |
| [x] | Warmup for heavy engines; generation-time estimate; paid/realtime flags | state `test_model_warmup_*`, `test_warm_active_engine_*`, `test_est_gen_seconds_*`, `test_tts_is_*` (2) | keep |

## Generation, auto-build, jobs

| ✓ | Behavior | Current tests | Disposition |
|---|---|---|---|
| [x] | Job queue: dedupe, coalesce identical segments, skip cached unless forced, await, failures surface, priority (current→ahead→behind), re-rank on move, cancel-unless-wanted, cancelled re-queues, cancel-all, progress burst | `test_jobs.py` (16) | keep — becomes the backend job manager's tests (Phase 1) |
| [x] | Per-clip badge: amber while typed text diverges, green when cached, reverts on undo, clears after save | `test_editing_text_flips_gen_badge_*`, `test_saving_an_edit_clears_the_stale_badge`, `test_segment_generate_button_flips_*`; browser `test_editing_a_generated_utterance_flips_badge_before_blur` | port→Vitest (merge the 3 GUI tests); **drop** the browser duplicate (badge is client state now) |
| [x] | Generate missing: count, disabled when none, filmstrip amber badges, cancel-all ✕ | `test_generate_missing_*` (2), `test_filmstrip_flags_*`, `test_cancel_all_button_*`; state `test_uncached_count_*`, `test_generation_target_helpers` | keep state; GUI → Vitest (one component test) |
| [x] | Editor stays live and queues while a clip generates; play awaits in-flight generation once | `test_editor_stays_live_*`, `test_play_awaits_in_flight_*` | port→API (job lifecycle) + Vitest |
| [x] | Typed-without-blur text is what gets generated | browser `test_typing_then_generating_without_blur_*` | port→Vitest (flush-before-action); **drop** the browser journey once flush is client-side |
| [x] | Auto-build: local-only, allowed for slow local, starts off, off on engine switch, sweep excludes current, debounce after edit, structural edits schedule, external changes sweep | `test_auto_build_*` (5), `test_switching_engine_turns_*`, `test_enabling_auto_build_*`, `test_structural_edit_schedules_*`, `test_external_change_sweeps_*`; browser `test_auto_build_generates_edited_slide_on_blur` | policy → Vitest store table (**merge** the 4 gating tests); sweep/debounce → Vitest with fake timers; **drop** the browser journey |
| [x] | Paid engine: preview and generate-missing ask first; confirm queues with `allow_paid`; popup names the session engine | `test_paid_engine_*` (3), `test_paid_confirm_names_*`; `test_jobs.py::test_paid_engine_refused_without_confirmation` | API test: a paid job without explicit approval is refused (the real guard); one Vitest test for the dialog |
| [x] | Real Kokoro: generate, cache, regenerate, blur-edit | browser `test_generate_cache_regenerate_and_blur_edit_with_real_kokoro` | keep as integration (local) |

## Playback

| ✓ | Behavior | Current tests | Disposition |
|---|---|---|---|
| [x] | Transport state machine: build→start, stop cancels pending, newer request supersedes, nav clears/keeps/seeks correctly, press toggles pause/resume, rebuild for another track, unload | `test_gui_layout.py::test_playback_*` (13) | port→Vitest as **one table-driven test** of the browser controller (13 → 1–2) |
| [x] | Play/pause/resume, seek bar + reset on stop, speed cycle + survives rebuild, stop-then-switch resets, grays out when pointless | `test_play_button_*`, `test_seek_bar_*`, `test_speed_*` (2), `test_stop_then_switch_*`, `test_transport_grays_out_*`; browser `test_speed_control_*`, `test_transport_play_stop_and_deck_cue_flip` | port→Vitest; keep **one** browser journey (real `<audio>`: play, seek, rate, stop) |
| [x] | Edits invalidate a loaded track: text, structure, pause length, generate, external edit; no-op blur keeps playing | `test_text_edit_revokes_*`, `test_structural_edit_resets_player`, `test_pause_length_edit_resets_*`, `test_generate_resets_rolling_player`, `test_no_op_blur_keeps_playing`; browser `test_external_edit_revokes_loaded_preview` | **merge** into one Vitest table (preview revision vs draft revision) |
| [x] | Play flushes a focused edit first; play-all starts at current slide | `test_play_press_flushes_*`, `test_play_all_starts_at_current_slide` | port→Vitest |
| [x] | Cancelling: stop during build, navigate away from pending single build; unaffected playback survives background generation | `test_stop_during_preview_build_*`, `test_navigating_cancels_*`, `test_generate_missing_keeps_unaffected_playback` | port→Vitest + API (cancel) |
| [x] | Following playback never destroys a focused field; pending edits saved on cue flip | `test_cue_flip_is_deferred_*`, `test_deck_playback_cue_flip_saves_*`; browser `test_editing_during_deck_playback_*` | **drop** all three — they guard the B2 server round trip. Replace with one Vitest test: playback slide ≠ editing slide, and following never touches a draft |
| [x] | Track refetch after a rebuild; assembled track never cached immutably | `test_replaying_preview_reloads_the_new_track`, `test_assembled_track_is_never_cached_immutably` | **drop** — B4 workaround; replaced by an API test that each preview job gets its own immutable URL |
| [x] | Cue lookup; progress forwarded to `build_preview`; export keeps render scratch | state `test_cue_start_finds_slide`, `test_preview_forwards_progress_*`, `test_gui_export_keeps_render_scratch` | keep (cue lookup also gets a TS twin in Vitest) |

## Diagnostics, orphans, and live files

| ✓ | Behavior | Current tests | Disposition |
|---|---|---|---|
| [x] | Diagnostics and per-slide console checks; audio status in console | `test_diagnostics_visible`, `test_console_*` (2); state `test_status_*` (5) | keep state; GUI → one Vitest test |
| [x] | Orphan tray: list, attach, append, delete, refuse bad targets | GUI `test_orphan_*` (3); state `test_orphan_*`, `test_attach_*`, `test_append_*`, `test_delete_orphan_*`, `test_unnarrated_pages_*` (7); browser `test_orphan_tray_badge_and_delete_flow` | keep state → service; GUI → one Vitest test; **drop** the browser duplicate |
| [x] | Live reload: sidecar, PDF, config; same-mtime change detected; missing/partial PDF and malformed config keep last good deck; errors reported once | GUI `test_recompile_while_editing_*`, `test_slide_image_refetches_after_recompile`; state `test_poll_*` (8), `test_pdf_change_*`, `test_config_change_*`, `test_reload_reuses_page_ids_*`, `test_external_changes_*`, `test_save_does_not_mask_*`, `test_own_save_does_not_trigger_reload` | keep state (becomes the source-revision service; content-based revisions make the same-mtime test simpler); GUI → one Vitest test on snapshot refresh; **drop** `test_slide_image_refetches_*` (versioned URLs make it structural) |
| [x] | Recompile adds/renames/shrinks: missing narration flagged, orphan error, index clamped; duplicate blocks disambiguated | state (4) | keep |
| [x] | Pages render in the background; reopening reuses them; deck opens before pages render | GUI `test_deck_opens_before_*`, `test_reopening_reuses_*`; state `test_page_images_never_render`, `test_render_pages_fills_in_*` | keep state; GUI → API (snapshot returns before rasterizing) |
| [x] | Media per deck: namespaced URLs, own images, refuse unregistered deck and path traversal, only a real content stamp is immutable | `test_gui_switching.py` media tests (6) | port→API (Phase 1); keep all — these are security/isolation checks |

## Review

| ✓ | Behavior | Current tests | Disposition |
|---|---|---|---|
| [x] | Review model: inactive until started, badges + conversations, capture cache, filing only when active, author edits, narration diff + base image, word diff | `test_gui_review_model.py` (7) | keep |
| [x] | Start review; deck note; slide note opens a conversation + badges the thumb; reply + accept; send releases wait; Enter sends; clear accepted | `test_gui_review.py` (7) | port→Vitest (conversation panel) + API (review commands) |
| [x] | Before/after for changed slides; none for unchanged; unrequested changes filed on recompile | `test_gui_review.py` (3) | port→API (diff payload) + Vitest (compare view) |
| [x] | One strip in current order, moved marks, removed slides after their old predecessor; conversation dims the rest, arrows stay inside | `test_gui_review.py` (3) | port→Vitest |
| [x] | Review tab badges what waits; closed conversations hidden until asked; deck opens without waiting for the comparison | `test_gui_review.py` (3) | port→Vitest + API |
| [x] | Declared-but-uncompiled slides | review ops tests (domain) | add an API test: DTOs carry ids absent from the PDF |

## Export

| ✓ | Behavior | Current tests | Disposition |
|---|---|---|---|
| [x] | Not-ready export explains blockers and offers a draft export | `test_export_when_not_ready_offers_a_draft` | port→Vitest + API (export job with `draft`) |
| [x] | Progress, errors, output naming, subtitles, transitions | domain tests (`test_api_export.py`, `test_export_integration.py`) | keep; add an API test for the export job lifecycle |

## Known redundancy found while mapping

Beyond the per-row notes above, these patterns recur and should be fixed as
tests are touched, even before their phase:

1. **Browser journeys that duplicate in-process tests.** 9 of the 20 browser
   journeys re-check something an in-process test already asserts (transition
   pickers ×2, pane collapse, orphan tray, badge flip, library card, external
   reload, speed, typed-text generate). Once the logic is client-side, Vitest
   sees it and the journey can go. Target: ~20 → ~6 journeys (navigation keys,
   block editing, B1 regression, real-audio transport, morph overlay, keyboard
   deck switching), plus the Kokoro integration test.
2. **One assertion per test over the same setup.** Playback state machine
   (13), pane layout (11), browser choice (10), voice picker (4), auto-build
   gating (4), morph schedule (6): ~48 tests that collapse into ~10 tables.
3. **Tests of workarounds.** 7 tests exist only to guard NiceGUI rebuilds or
   the B2/B4 round trips. They go away with the bugs, each replaced by one
   behavioral test.

Rough estimate of frontend-facing tests at the end: ~330 → ~220, with the
slow in-process `user` tests (~90 % of unit-tier wall time) replaced by
Vitest tests that run in seconds.
