# Roadmap

Current version: **1.0.0a3 — published to PyPI 2026-09-29.** It ships the Vue
editor (NiceGUI is gone), the always-on agent review loop, the script view, slide-by-slide
Play all, the shared clip pool, Inworld delivery controls and the quick export
(`--fast`). `main` has nothing unreleased beyond it yet.

*Last PM pass 2026-09-29 (second pass, same day).* The code + UX reviews
landed: two independent reviews (ours: 6 code + 2 UX agents; Astra's) merged into
**`dev/REVIEW-TODO.md`** — the detailed, tiered checklist (importance × ease).
Now #1 and Next #7–#8 below point at its tiers; tick items off there.

**Demo status:** basel-problem HQ Inworld render shipped (YouTube). Showcase is
still Kokoro-only (Next #5). The demo PDFs are final (`\\ssfinal`) builds as of 1.0.0a3.

Lane tags: **[agent]** = an agent can do it end-to-end · **[agent→human]** =
agent does the work, human approves/verifies · **[human]** = needs the human
(paid, irreversible, or account-bound).

## Now — this week

1. [ ] **Fix the review's Tier 1–3 findings** (`dev/REVIEW-TODO.md`).
   **Status 2026-09-29:** batches (a)–(f) below are **done and on `main`** (each with
   regression tests; CHANGELOG "September 2026 review"), plus the Qwen3/golden
   cache-key batch and the pipeline, server and docs cleanups from Next #8. The editor UX quick wins are
   merged too, and so are the follow-up batches (Kokoro voices in every language,
   `review --narration`, `-q`/`-v` anywhere, blank lines skipped in export, duplicate
   `@id` agreement, orphan-action guards, the empty-new-line conflict). Heavy suites
   green on 9579d6f (36 passed); on c1ec424 one test failed once
   (not captured); the rerun on 41dd234 (Inworld merged) was **all green** (37 passed, 1
   skipped: the Qwen3 real-prompt test), so it was intermittent — likely a browser-tier
   flake under CPU load (cf. `test_keyboard_deck_switching`). Rerun once more before a3. Still open in Tier 3: paid work
   pinned to approved content, frontend dead code and missing frontend tests. Original scope:
   Two
   reviews agree the new editor and pipeline have real data-loss and paid-audio
   holes; a3 must not ship them. Work in parallel batches, each **repro test
   first** at the lowest level that sees it (pytest / Vitest; browser tier only
   for focus, timing, media):
   (a) **audio loss & paid safety** — one clip GC over sibling decks (per-deck
   `clean` and the on-save sweep delete other decks' clips, incl. paid),
   `--narration` override in sweep + review, `clean` dry-run/trash like
   `pool prune`, pool==legacy-dir `rmtree`, whole-deck `force` generate skipping
   paid approval, `make clean` deleting committed Inworld audio;
   (b) **narration round-trip** — ` #` truncates spoken text, newlines inject
   pauses/voices/blocks, nan/inf/negative numbers;
   (c) **frontend save soundness** — conflict map, load epochs, `flush()→bool`,
   route guards, Script-view focus + save indicator, review note/picked leaks;
   (d) **export correctness** — ~20 ms/slide A/V drift, atomic MP4 + render cache,
   `concat_list.txt` in the output dir / apostrophe paths, `export` succeeding on
   broken narration;
   (e) **server robustness** — review-log transactions, queue-worker death, job
   status/dedupe races, per-deck `.env`, media-route Host check, bare 500s;
   (f) **first run** — README install (`--prerelease`), quick start with
   `--draft`, v1 `init` header, pronunciation-in-toml docs, build skill's
   Inworld guard, release verify step.
   Also carried from the merge: the intermittent browser-journey flake ("not
   stable" at `seg-up-2`) and the unreproduced "Clear accepted hangs during
   playback" report. *Acceptance:* every Tier 1–2 box ticked with a regression
   test; Tier 3 ticked or consciously deferred in the file. *Appetite:* three to
   four days across parallel agents. **[agent]**
2. [ ] **Inworld delivery controls — decide the open questions, then spot-check.**
   **Built 2026-09-29** (CHANGELOG "Added"; `docs/authoring.md` "Delivery on Inworld"):
   inline pronunciation fixes `[Mengoli](/menˈɡoːli/)` / `[Dijkstra](DYKE-struh)` (captions
   and word marking show the display word; Inworld gets the spoken form; Kokoro/Qwen3 a
   respelling or the word, never IPA); `direct:` notes sent to `inworld-tts-2` only with
   `[tts.inworld] send_direction = true` (default off); stray `[`/`]` sent to tts-2 as
   `(`/`)` plus a `check` note; new `[tts.inworld]` keys `temperature`, `delivery_mode`,
   `language`, `text_normalization`, unset by default and added to the cache key only
   when set. AICODE verified: 39 decks, 2191 Inworld and 2191 Kokoro clip names unchanged.
   **Decided 2026-09-29 (to build):**
   (1) `/…/` values in the pronunciation dictionary go to Inworld only; Kokoro/Qwen3 get the
   plain word (as inline fixes do). Respellings still go to every engine. Inworld clip names
   unchanged; Kokoro clips with dictionary IPA re-key (free). Fixes the basel Kokoro demo,
   whose nine IPA names reach Kokoro verbatim today.
   (2) `send_direction` defaults to **on** everywhere (`= false` opts out). Re-keys only lines
   with a `direct:` note. AICODE's only note (week01 `01-10_welcome_to_ai_code`) was removed
   by the maintainer, so no AICODE clip re-keys.
   (3) The editor warns only on the likely typo `[word] (form)` (a space between `]` and
   `(`); plain brackets like "[0, 1]" get no note in the editor or in `check`.
   (4) Parked: nothing phoneme-level goes to Kokoro for now. A both-forms fix
   `[Mengoli](/menˈɡoːli/ | men-GO-lee)` (IPA to Inworld, respelling to Kokoro) is the
   cheap route if it is wanted later (Later backlog).
   **Paid spot-checks (human-triggered, a few cents; never in tests):**
   (i) `The work of Pietro [Mengoli](/menˈɡoːli/) began it.` on the default model and on
   `inworld-tts-1.5-max`; (ii) `[Leonhard Euler](/ˈleɪɒnhɑːrt/ /ˈɔɪlər/) summed it.`;
   (iii) `Drive at 50 km/h, and/or take 3/4 of it.`; (iv) `The interval [0, 1] is closed.`;
   (v) `This is the whole trick.` with `direct: slowly, in a low voice`, with and without
   `send_direction`; (vi) `delivery_mode` stable vs creative, two takes each; (vii)
   optional `temperature = 0.6` vs unset on 1.5-max; (viii) `[Dijkstra](DYKE-struh)` vs
   `[Dijkstra](dyke-struh)` on tts-2 (CAPS read as emphasis?). **[human]**
## Next — this month

1. [ ] **Bug: `pool prune --root <course>` refuses to run on a real course.**
   `discover_decks` (`server/library.py`, `max_depth=6`, `max_dirs=5000`, tuned
   for a GUI launch from `$HOME`) marks the *whole* scan truncated when any branch
   is too deep — in AICODE, the site's `site/dist/…` — so `pool prune` aborts
   (`cli.py:681`), while `pool migrate` has no such guard and silently works off a
   partial list. Workaround in use: name all decks explicitly (`just prune-pool`).
   *Acceptance examples:* (a) a course with decks at depth 2 and an unrelated
   8-deep build folder prunes normally; (b) a scan that really hit `max_dirs`
   still refuses, naming the limit and where it hit; (c) `pool migrate` refuses on
   a truncated scan the same way. *Repro test first:* `tests/test_pool*.py` with a
   tmp tree. *Appetite:* two hours. **[agent]**
2. [ ] **Bug: a renamed deck's render scratch is never cleaned.** `render_dir`
   is `<cache>/render/<pdf stem>/`, and `clean` removes only the current stem's
   folder, so a renamed deck strands its old scratch (298 MB found in AICODE
   2026-09-16). *Acceptance:* (a) `clean deck.pdf` also removes every
   `render/*/` whose name matches no `*.pdf` beside the deck, and says so;
   (b) `pool status deck.pdf` mentions stray render folders. *Repro test first:*
   `tests/test_clean.py`. *Appetite:* an hour. **[agent]**
3. [ ] **Choose where the video and the subtitles go, separately.** *Story:* As
   a course author rendering in git worktrees, I want the `.mp4` to land in one
   fixed place and the `.srt`/`.vtt` beside the deck (they are committed and
   translated), so removing a worktree never loses a render. *Acceptance
   examples:* (a) `[video] output_dir` (absolute, `~`, or toml-relative, like
   `[cache] audio_dir`) / `--output-dir` makes `export` with no `-o` write
   `<output_dir>/<stem>.mp4`; `-o` still wins; (b) `[video] subtitles_dir` /
   `--subtitles-dir`; once `output_dir` is set, subtitles default to beside the
   deck; with neither set nothing changes; (c) `pool status` (or `export --where`)
   prints the resolved paths without rendering. *Appetite:* half a day. **[agent]**
4. [ ] **Faster full export (follow-up to `--fast`).** The quick export shipped
   (2026-09-29; basel warm-cache: full ~115 s, `--fast` ~15 s first run, ~2 s repeat). Its
   profile found speed-ups that keep the full export's output **byte-identical**: (1) encode
   the AAC in parallel with the video and copy it in (~12 s); (2) keep the assembled audio
   track and page images between exports (~8 s); (3) cache each slide's encoded clip keyed on
   image hash + frame count + encoder settings, so a re-export re-encodes only changed
   slides (~90 s → seconds); (4) page lengths from WAV headers. Also: stills are rasterized
   at 150 dpi and upscaled to 1080p — a higher dpi would sharpen text; and `--fast` needs
   ffmpeg ≥ 5.1 (`-fps_mode vfr`) — add a `doctor` note. *Acceptance:* full-export
   stream hashes unchanged before/after; warm re-export after a one-slide edit under 15 s.
   *Appetite:* a day. **[agent]**
5. [ ] **Showcase HQ render + refresh the release assets and YouTube.** Showcase
   is Kokoro-only; basel is on YouTube but the `v0.0.0` release MP4s are still the
   March Kokoro cuts. Human triggers the paid showcase render; agent commits the
   paid audio, uploads with `gh release upload v0.0.0 … --clobber`, preps YouTube
   titles/descriptions/chapters from the sidecars, refreshes README links.
   *Depends on:* Now #2 (showcase will hit the same IPA-in-captions trap) and the
   final-build recompile in Now #3. **[human→agent]**
6. [ ] **Docs, README and skills after the UI change.** The editor, review loop,
   plain/final builds and pool all changed how the product is used. *Acceptance:*
   (a) README screenshots of the new editor (script view, Review tab) replace any
   old ones, and the editor section matches the Vue UI; (b) `docs/authoring.md`,
   `slidesonnet init` scaffolding and `--help` match narration format v2 and
   mention `\ssfinal`; (c) the committed skills (`beamer-writer`, `build`, `pm`,
   `ux-review`) know the review CLI, plain vs final builds and `--draft`, and
   `beamer-writer` emits a valid v2 preamble (checked against the demo sidecars);
   (d) `docs/frontend-parity.md`/`frontend-migration.md` are marked historical.
   *Appetite:* a day. **[agent]**
7. [ ] **Review Tier 4 — structural refactors** (`dev/REVIEW-TODO.md`):
   load-once `DeckContext` passed into `api` (root of the paid/positional-target
   bugs), a single generation path through the per-(deck, engine) queue,
   `VoicePlan` + one `effective_engine()` (editor defaults to Inworld, CLI to
   Kokoro), module layering fixes, splitting `cli.py`/`routes.py`/`EditorView.vue`,
   a frontend jobs store, typed job results, Play all that starts at once, and
   plain-language progress. *Acceptance:* behaviour unchanged (existing suites
   green), import graph has no cycles, the paid-approval tests from Now #1 still
   pass against the new path. *Appetite:* a week, after Now #1. **[agent]**
8. [ ] **Review Tier 5 — cleanup sweep** *(dead code, test trims, docs/rules drift
   and CI hygiene done 2026-09-29; left: Ruff rules, Prettier, pre-commit hooks)* (`dev/REVIEW-TODO.md`): ~450 lines of
   dead source + ~45 tests with it, ~100 more tests trimmed/parametrized, a
   golden cache-key table (the one test that guards every paid clip), NiceGUI
   remnants, stale rules/CLAUDE.md, pyproject/CI hygiene, stricter Ruff rules
   (`I`, `B`, `UP`) and Prettier for the frontend, both enforced in CI, plus fast pre-commit hooks. Folds into Next #6's
   docs pass. *Acceptance:* unit tier count and time drop; coverage stays ≥ 94%;
   `make lint typecheck test-unit test-frontend` green. *Appetite:* a day.
   **[agent]**
## Later — before 1.0 final

1. **Review loop follow-ups** (spec `dev/DESIGN-review.md`): highlight the
   pixels that changed in before/after; play the old narration next to its word
   diff (the base clip is already kept); quote selected narration text into a
   note; an optional Claude Code hook running `slidesonnet review status` after a
   LaTeX compile; plain-build support for themes beyond metropolis. *(Comment on
   several slides shipped — Ctrl-click in the filmstrip.)*
2. **Line-as-unit editing** (inbox 2026-06): insert a line between lines, and move
   a line together with the pause before it (new lines default to a 0.3 s leading
   pause). Re-check against the script view and Slide view before designing —
   the original note described the NiceGUI card editor.
3. **A trailing pause becomes the End silence field** (inbox 2026-08-23): adding
   a pause after the last line makes it the block's end silence, so the added
   pause visibly disappears in the card editor. Re-check in the Vue Slide view
   (a pause is now a thin rule) before deciding whether it's still a problem.
4. **Find a slide by its text** — search the PDF text layer (the review base
   already extracts it) from Ctrl+K.
5. **Cache inventory** — count + size of cached clips before clearing, and the
   before→after delta after; pairs with `clean --dry-run`. Now that clips live in
   a pool, `pool status` is the likely home.
6. **Config audit** — inventory every `slidesonnet.toml` key, drop the vestigial
   ones (`[tts] backend` is now only the editor's starting engine).
7. **Narration schema validation** — EBNF of the sidecar in docs, `narration
   export --json` + JSON Schema. Don't YAML-ify the format.
8. **Multi-take TTS** — re-roll and compare takes; needs a take index in the cache
    key or a side `takes/` store.
9. **`check --fix`**, **`clean --dry-run`**, **`init` scaffold with PDF-outline
    titles**, an **export dialog** with timing/subtitle options.
10. **Per-segment voice switching mid-utterance.**

## Later — backlog


1. **Cross-deck background generation.** The job queue is now server-side and
   survives a reload, but leaving a deck still cancels its generation
   (`stores/generation.ts` `leave`). Let deck A keep generating while you read
   deck B. *Open questions:* one worker or one per deck (rate limits, iGPU
   contention); where a detached failure shows up. ~two days.
2. **A resident editor server** — the editor is already a FastAPI server; the open
   question is whether the CLI should attach to a running one (warm models,
   shared cache state). Options memo, human decides. Post-1.0.
3. **id-injection adapters** — Marp, PPTX, Google Slides; same marker contract.
4. **Layered reconciliation** — text-fingerprint fallback when ids are missing.
5. **More TTS backends** — Cartesia, Azure, Google Cloud.
6. **Multi-deck playlists** — several PDFs into one video.
7. **`--json` output** for CI/automation (also review Tier 6).
8. **Review Tier 6 polish** (`dev/REVIEW-TODO.md`): CLI surface consistency
   (`tts --force`, `--config`, `check --json`, `NO_COLOR`), editor polish and
   accessibility, minor correctness, type tightening.

## Done (v1 rewrite)

- [x] **Published 1.0.0a3** (2026-09-29; tag `v1.0.0a3` at `abafafe`; PyPI, TestPyPI and
  GitHub Release). Heavy suites green (38 passed), demo PDFs recompiled as final builds,
  consolidated release notes with a Breaking list. The first publish run failed at the
  TestPyPI install check (a junk `fastapi` on TestPyPI); the workflow now takes only
  slidesonnet from TestPyPI and re-runs skip existing files; the tag was moved to the fix.
- [x] **Quick export `--fast`** (2026-09-29, `5b98731`; was Next #4). 720p, cuts, one
  variable-frame-rate encode, audio byte-identical to the full export; writes
  `<name>.fast.mp4`; editor "Quick export" box. basel warm: ~15 s vs ~115 s.
- [x] **Review Tier 3 closed** (2026-09-29): paid work pinned to the approved clip set,
  frontend dead code, missing frontend/server tests, and all fix-batch follow-ups.
- [x] **Deck-level checks in the editor** (2026-09-29, `3782666`; was Now #5). A
  "Deck checks" list shows findings no slide owns (out-of-order narration, an
  unattached block's error, linking to the tray); the error pill leads there.
- [x] **Preview bugs carried over from NiceGUI re-checked** (2026-09-29, `cd444bc`,
  `ba295dd`; was Now #4). Both survived in new forms and are fixed: a recompile keeps
  every thumbnail until its new picture lands, and the transition overlay in Watch as
  video lifts only once the next picture has decoded.
- [x] **Qwen3 own-voice clone: tried, not good enough** (verdict 2026-09-29; was
  Now #3, then Next #7). The maintainer recorded a reference, built the clone and
  judged the result: not good. Own-voice cloning is dropped, and with it the
  items that only served it: the per-utterance `.pt` content hash, the DashScope
  cloud-clone mode, and batched iGPU synthesis. The Qwen3 engine stays (built-in
  CustomVoice speakers).
- [x] **Review is always on; the Review tab centres on conversations**
  (2026-09-28/29, `a21c3f7`, `333b4d5`, `b88098f`, `36f14b1`; CHANGELOG
  `[Unreleased]`). The base is taken on first open (no Start review), **Reset
  comparison** re-bases the view without touching conversations, no clean level
  drops the base, conversations take titles (`review title`, `--title`), and
  Ctrl-click in the filmstrip tags several slides for one conversation (the
  "comment on several slides" follow-up).
- [x] **Play all plays slide by slide** (2026-09-28, `b9ee7ee`, `8b18d96`). Each
  slide's own track with the next one prefetched, scoped to the slides not
  greyed out, missing clips queued up front (one paid-engine prompt), "slide 3 of
  7". This delivered the former Now #4 (play before the deck is fully generated)
  and made the former Next #11 (pre-assemble the whole-deck track) moot. The old
  whole-deck preview is now **Watch as video**. A 0.8 s wake-up silence keeps
  Bluetooth speakers from swallowing the first word.
- [x] **Script view is the editor's default** (2026-09-28, merge `b8e06b1`): the
  whole deck's narration as one editable document, marking the spoken line to
  the current word during playback.
- [x] **Frontend migration: NiceGUI → FastAPI + Vue 3** (2026-09-28, merges
  `78da538`…`52cd32f`; was Now #6). Service layer + `/api/v1` + jobs/SSE,
  browser-owned playback, the editor and review in Vue, NiceGUI removed, first-use
  layout round. Unit tier 148 s → ~25 s. Plan and parity inventory in
  `docs/frontend-migration.md` / `docs/frontend-parity.md`. Optional follow-up
  not taken: IndexedDB draft recovery.
- [x] **Agent review loop merged** (2026-09-28, merge `0a4e920`; was Now #1).
  Plain-by-default builds (`\ssfinal` for final), base + diff by slide id,
  `<deck>.review` conversations and the `slidesonnet review` CLI, the export check
  (`--draft`), and the editor review tools. Spec `dev/DESIGN-review.md`.
  *Left over:* recompile the demo PDFs as final builds — now part of Now #3.
- [x] **Unsaved typing survives an external sidecar edit** (2026-09-28,
  `5bf2221`). The keystroke-loss half of the former Now #5.
- [x] **Export reports progress for every phase** (2026-09-24, `5a319f4`; was
  Next #13). One overall percent on stderr in a regex-friendly format, a
  per-phase timing line, and a progress bar in the editor's export.
- [x] **Shared speech-clip pool** (2026-09-16, `9e0ad66`): `[cache] audio_dir` /
  `SLIDESONNET_AUDIO_DIR` / `--audio-dir`, `pool status|migrate|prune`, render
  scratch deleted after a successful export, one silence file per duration,
  unchanged subtitle files not rewritten. Covers three inbox items (shared audio
  across worktrees, the 7.7 GB scratch, subtitle mtime churn).
- [x] **Subtitle fixes** (2026-08-27 `7ffcffa`, 2026-09-03 `207246c`): `subs
  --engine` and refusing guessed times (no more silent drift after an Inworld
  export), and no more invalid `,1000` millisecond stamps.
- [x] **Unified logging** (shipped in 1.0.0a2, `c329692`; was Next #1):
  `logging_setup.py`, `--quiet`/`--verbose`/`SLIDESONNET_LOG`, a rotating
  per-deck log file.


- [x] **Deck switching + a deck library in the editor** (2026-08-23; CHANGELOG
  `[Unreleased]`; was Now #1). `slidesonnet edit` now opens on a library of every
  deck under the scanned folder — `edit <folder>`, `edit <deck.pdf>`, or bare
  `edit` for the cwd, plus `--root` to widen the scope. Discovery walks *down*
  for a PDF with a sibling `<stem>.narration` (no VCS assumption), pruning
  dot-dirs/`node_modules`/deck caches and capped in depth and breadth so a huge
  tree reports a truncated scan instead of hanging; 13 decks in `~/courses/aicode`
  scan in ~5 ms. Decks are addressed by a deterministic token and routed at
  `/d/{token}`, so a switch is a page navigation (NiceGUI's own teardown does the
  cleanup) and back/forward, bookmarks, and two-decks-in-two-tabs all work.
  Ctrl+K palette, Alt+←/→ stepping (wrapping), header deck dropdown. Switching
  saves the edited slide first, stops the transport, re-points the run-log, and
  cancels generation for the deck being left (finished clips stay cached).
  **The `/ssmedia` blocker is fixed**: media is per-deck (`/ssmedia/{token}/…`,
  range requests preserved, unregistered tokens 404) — verified live with two
  decks open at once serving distinct images. New: `gui/library.py`,
  `gui/library_view.py`, `gui/theme.py`; 51 new tests (unit + in-process GUI +
  3 browser journeys covering the real keyboard path). *Deferred as designed:*
  lazy stats shipped, but recents-across-sessions did not; the `load_env`
  `os.environ` leak between decks stands (see Later backlog); cross-deck
  background generation stays in Later backlog #9.


- [x] **basel-problem HQ Inworld render shipped** (2026-06-19/20; was the basel
  half of Next #3). The basel deck was rendered on the Inworld cloud engine with
  drift-free subtitles (the MP3 drift fix), pronunciation tuned to IPA bound in
  `/slashes/` so Inworld speaks it phonemically, paid audio committed (23 `.inworld`
  clips, per the commit-paid-audio rule), pacing pauses tuned between blocks, and
  the result **published to YouTube** — README links it (`https://youtu.be/pjjHS9vhjpk`,
  "Inworld narration"). *Caveat:* the `v0.0.0` GitHub Release MP4 (`basel-problem.mp4`)
  is still the old March/Kokoro cut — only YouTube got the Inworld render; refreshing
  the release asset is folded into Next #3. The **showcase** HQ render is still
  pending (Kokoro-only) — see Next #3.
- [x] **`clean` no longer false-orphans preamble-voiced paid audio** (2026-06-19,
  `a40cc51`; CHANGELOG `[Unreleased]` `### Fixed`). `clean --keep current`/`exact`
  reconstructed cache keys from only `config.voices` + per-utterance `voice:`,
  ignoring the sidecar's portable voice preamble (`voices:`/`default-voice:`) and
  per-backend `resolve_voice` — so a default/preamble-voiced Inworld clip collapsed
  to voice `None`, mismatched the real key (a concrete voice id like `Tyler`), and
  was deleted as an orphan: silent loss of paid, regenerate-for-money audio (hit on
  the basel demo, whose voices live entirely in the preamble). Clean now mirrors
  synthesis exactly — merges the preamble over config, applies `default-voice`,
  resolves per-backend. Regression test in `tests/test_clean.py`.
- [x] **Default Inworld model bumped to `inworld-tts-2`** (2026-06-19, `a69ba00`;
  CHANGELOG `[Unreleased]` `### Changed`; was `inworld-tts-1.5-max`). Override per
  deck with `[tts.inworld] model`. The model is part of the audio cache key, so
  existing Inworld clips re-synthesize on next generate under the new default.
- [x] **Minor editor UX flow fixes — 3 of 4 shipped** (2026-06-19; CHANGELOG
  `[Unreleased]`; were Now #2 sub-items). (a) **Per-utterance dirty badge:** typing
  in an utterance flips its generate badge to amber (not-up-to-date) within a
  keystroke — before blur/save — and undo back to the original restores green
  (`BlockEditor._mark_text_dirty` + dirty-aware `sync_gen_buttons`; unit test +
  browser journey for the before-blur timing). (b) **Single-slide transition
  toggle:** a "Play transitions in single-slide preview" checkbox (off by default,
  session-local) gates the single-slide morph; whole-deck preview unaffected
  (`_single_slide_morph(enabled=…)` + `_arm_morph` reads `app.storage.general`).
  (c) **New-line default voice:** verified **already delivered** by the
  portable-voice layer — a newly added line stays unset and round-trips with no
  `voice:`, resolving deck-default→engine-default at synth; locked in with a
  regression test. The literal "show the engine voice id in the picker" reading was
  *deliberately rejected* earlier (`test_voice_box_default_option_without_a_named_default`:
  "never a raw engine id"), so no change there. The 4th sub-item (play-all before
  fully generated) is re-scoped to its own ~2-day item — see Now #2.
- [x] **Inworld (MP3) subtitle drift fixed** (2026-06-19; CHANGELOG `[Unreleased]`
  `### Fixed`; was Now #1). SRT/VTT subtitles slid progressively **late** on Inworld
  (`.mp3`) renders (~1–2 s by end of deck) because the subtitle timeline was built
  from per-clip `get_duration` (ffprobe `format.duration`, which over-reports an MP3
  by its encoder delay + padding) while `concatenate_audio` decodes to the true
  shorter length. `get_duration` now measures the *decoded* length for compressed
  audio-only clips (decode to PCM, as concat does), so per-clip durations sum to the
  assembled track; WAV/PCM and the muxed video keep the cheap header read. Went with
  candidate **(b)** — *not* the WAV-cache rewrite (a): no cache-format change, so
  already-cached paid `.mp3` audio renders drift-free with **no re-synthesis or
  re-billing**, and `clean`'s paid-keep logic is untouched. Repro test
  `tests/test_subtitle_drift.py` (free — libmp3lame tones, no Inworld call),
  red→green; full unit tier 737 passed, lint + `mypy --strict` green. This was the
  last defect gating a clean HQ demo with subtitles (Next #3).
- [x] **Accelerated narration playback (1× / 1.25× / 1.5× / 2×)** (2026-06-19;
  CHANGELOG `[Unreleased]` `### Added`; was Now #3). A cycling speed button in the
  editor transport sets the preview player's HTML5 `audio.playbackRate` live (no
  re-synthesis, no cache write); the rate sticks across slides and across
  play-slide/play-all (re-applied on each track load via `defaultPlaybackRate`),
  cue flips and the morph overlay stay locked to the faster audio clock, and
  `preservesPitch` keeps 2× natural. Preview-only — never touches the cache, the
  `pace:` directive, or the export. Unit tests cover the cycle + stickiness
  (`test_gui.py::test_speed_button_cycles_through_playback_rates`,
  `test_speed_setting_survives_a_preview_build`); the real-browser `playbackRate`
  assertion is browser-tier (`test_browser_journeys.py`).
- [x] **Published 1.0.0a2** (2026-06-19; tag `v1.0.0a2`). The whole post-a1 batch
  is now installable: the publish workflow ran TestPyPI → PyPI → GitHub Release all
  green. Shipped the transition gallery + per-slide silences + centered-overlay
  transitions, the Qwen3 local engine, the portable voice layer + Voices dialog,
  the background generation queue + auto-build, the Inworld cloud engine
  (ElevenLabs removed), the per-engine prune policy, the Play-all assembly bar, the
  `yuv420p` Windows-playback fix, and the editor bug-fix batch — all in
  `CHANGELOG [1.0.0a2]`. (Was Now #1.)
- [x] **Inworld validated on a real paid run** (2026-06-19; was Now #4). A real
  paid synthesis ran end-to-end; the engine works and the voice quality is good.
  *Verdict:* ship-worthy "up to the drift" — the one defect surfaced is the **MP3
  subtitle drift** (now Now #1), so a clean HQ demo with subtitles (Next #3) waits
  on that fix, not on the engine. The `.env`-on-synthesis and paid-confirm
  supporting fixes held up in the real run.
- [x] **Per-engine cache prune policy — Qwen3 audio survives an edit** (2026-06-19;
  CHANGELOG `[1.0.0a2]` `### Fixed`; the a2 gate, former Now #2). The silent
  on-edit orphan sweep keyed on `paid`, treating free-but-slow Qwen3 as cheap and
  silently deleting minutes of own-voice audio on an unrelated edit. Whether the
  sweep may drop a backend's orphans is now `BackendSpec.auto_prune_orphans` (only
  real-time local audio — Kokoro — is eager; Qwen3 and paid Inworld are kept);
  `prune_local_orphans` reads `AUTO_PRUNE_BACKENDS` instead of `API_BACKENDS`.
  `clean --keep nothing` still nukes all. Repro test
  `test_clean.py::test_prune_local_orphans_keeps_expensive_local_qwen3`.
- [x] **Changing a pause/edge-silence refreshes the loaded "Play all" track**
  (2026-06-19; CHANGELOG `[1.0.0a2]` `### Fixed`; former Now #3). The silence/pause
  number fields commit on blur, so a Play-all press before the blur resumed the
  stale loaded track. `PreviewPlayer.request_preview` now flushes the open field
  (`commit_audible`) on any play press and rebuilds when it changed. Turned out
  unit-testable (the in-process sim's `set_value` is the focused-uncommitted
  condition): `test_gui.py::test_play_press_flushes_focused_silence_edit_and_rebuilds`,
  verified red→green.
- [x] **Renaming a voice follows through to every reference** (2026-06-19;
  CHANGELOG `[1.0.0a2]` `### Fixed`; former Now #4). A rename updated only the
  `voices:` map key, leaving utterances pointing at the gone name (unmapped) and
  the picker offering it. The Voices dialog now tracks per-row old→new identity and
  `edit_voices(renames=…)` rewrites every utterance `voice:` and the `default-voice`
  old → new before saving. Repro test
  `test_gui_state.py::test_edit_voices_rename_rewrites_references`.
- [x] **Exported decks with transitions play on Windows again** (2026-06-19,
  `6aa0e65`; CHANGELOG `[Unreleased]` `### Fixed`, ships in a2). FFmpeg's `xfade`
  emitted `yuv444p` for transition clips while slide segments were `yuv420p`, so
  the stream-copy concat made a non-uniform H.264 stream — ffmpeg/VLC tolerated
  the mid-stream switch but Windows' 4:2:0-only decoder rejected it at the first
  transition (first slide played, then "unsupported codec settings"). Transition
  clips are now pinned to `yuv420p`. Repro test
  `test_composer.py::test_compose_transition_clip_is_yuv420p`.
- [x] **"Play all" shows an assembly progress bar** (2026-06-19, `fadf0f4`;
  CHANGELOG `[Unreleased]` `### Added`, ships in a2). Building the whole-deck
  preview concatenates a per-page WAV for every slide and can take a while on a
  long deck — previously just a spinner. The editor now shows an "Assembling
  audio · X/N" bar (reusing the generation progress bar) that advances per page;
  `api.build_preview`/`render.render_audio_track` gained a `progress` callback.
  The export-side sibling (a progress bar for the long FFmpeg render) is now
  Next #13.
- [x] **External narration edits no longer leave a stale preview** (2026-06-19,
  `a3638b6`; CHANGELOG `[Unreleased]` `### Fixed`, ships in a2). With a whole-deck
  or single-slide preview loaded, hand-editing the `.narration` sidecar on disk
  (e.g. changing a transition) reloaded the editor's fields but kept the *old*
  preview track — pressing play resumed stale audio and the stale transition
  morph instead of rebuilding. `_poll_sources` now revokes a loaded preview track
  on any external reload (mirroring what `replace_block` already does for in-GUI
  edits). Found while using the editor; reproduced first as browser journey 11
  (`test_external_edit_revokes_loaded_preview`), red→green. The in-GUI blur-timing
  sibling (silence/pause fields) also shipped in a2 (the play-press flush fix above).
- [x] **Fixed the CI `test`-job hang — the a2 release blocker** (2026-06-19,
  `e9b6744`; CI green on `main` at `633ccc5`). GUI unit tests that play/generate
  drove the background queue through real synthesis, but CI installs only `[dev]`
  (no `kokoro`/`torch`/`qwen_tts`), so the deck-synthesis path raised "kokoro
  package not installed" and errored 9 playback tests (earlier the dangling task
  ran the job to GitHub's 6h ceiling). *Fix:* an autouse, **`gui`-scoped** conftest
  fixture stubs `synth.create_tts` with a tiny-WAV engine (same rationale as the
  pdftoppm rasterize stub — GUI unit tests shouldn't shell out to a real backend);
  scoping to the `gui` marker keeps the real engine for the cache-key/pace tests
  (`test_kokoro`/`test_clean`/`test_synth`). Plus `--timeout=120
  --timeout-method=thread` on the CI command as a hang safety-net. Verified: the 9
  tests pass even with real `kokoro.synthesize` forced to raise; full unit tier 736
  passed; CI's lint/typecheck/test/build all green on `main`. *(Was Now #1.)*
- [x] **Remove the ElevenLabs backend outright** (2026-06-19, CHANGELOG
  `[Unreleased]` `### Removed`): Inworld is the sole cloud engine now (matches
  ElevenLabs quality at ~10× less). `tts/elevenlabs.py`, its `BackendSpec`, the
  `elevenlabs` extra + mypy override in `pyproject.toml`, the `[tts] elevenlabs_*`
  config keys and their validation, the `Backend` literal entry, and the
  `elevenlabs` branch of `engine_voice_choices` are all gone; the conftest
  ElevenLabs sentinel guard and all test-suite references are removed (the Inworld
  guard stays — `test_elevenlabs*.py` deleted, the rest converted to `inworld`);
  `slidesonnet doctor` no longer lists it; the example tomls dropped their dead
  `[tts.elevenlabs]` blocks and `elevenlabs` voice maps. `make test-unit` (706
  passed), lint, and typecheck stay green.
- [x] **Transition gallery + per-slide silences + centered-overlay transitions**
  (2026-06-18, CHANGELOG `[Unreleased]`): the former Now #1, fully shipped on
  `main`. The full FFmpeg `xfade` gallery behind a curated **Type + Direction**
  picker (`fade`/`wipe`/`slide`/`cover`/`reveal`/`circle`/`dissolve`/`pixelize`,
  plus `fadeblack`/`fadewhite`), an unknown name is a parse error not a silent
  cut, and a client-side **preview morph** (`gui/static/morph.html` driven by
  `_morph_schedule`) that completes at the cue boundary for whole-deck *and*
  single-slide play. Plus the reshaped follow-ups locked 2026-06-18: per-slide
  editable **Start/End silence** fields — the old invisible global lead/tail is
  now a positional, author-controlled `pause:` (absent = deck default, explicit
  replaces, `0` = no hold; the GUI materializes implicit→explicit on save while
  the CLI/API path stays implicit) — and **centered-overlay transitions** (a
  D-second transition is a pure visual overlay centered on the A→B boundary; the
  assembled audio track and the deck's total duration are byte-identical to the
  all-`cut` render, and an over-long transition clamps with a
  `slidesonnet check` `transition-too-long` warning). Tests: `test_render.py`
  (`_centers_transition_and_preserves_total`, `_clamps_to_shorter_slide`, silence
  helpers), `test_diagnostics.py` (`transition-too-long`), GUI/state start/end
  silence fields, `test_transition_gallery.py`, morph-schedule + browser journeys.
- [x] **Editor voice/generation polish batch** (2026-06-18, CHANGELOG
  `[Unreleased]`): a run of editor work on `main` after the portable-voice/Qwen3
  merge — the **Voices…** dialog to create/edit the deck's named voices
  (pick-or-type per engine, Default-voice picker, byte-stable round-trip; was the
  former Now #2); a **named-only** per-utterance voice picker (raw engine ids no
  longer listed) with an explicit **default** option that shows the resolved
  engine voice (e.g. `lecturer (am_michael)`); **auto-prune of local orphans** on
  save (`prune_local_orphans` — see the per-engine-policy follow-up now in Now #2);
  Qwen3 **built-in CustomVoice speakers** (Vivian default) so it narrates out of
  the box, **prioritized auto-gen** (best-next clip, re-prioritized on nav, Qwen3
  no longer locked out), a **generation progress UI** (deck count bar + per-clip
  elapsed/estimate), **cancellable play** and a **✕ cancel-all**, auto-generate
  now **starts off each session** and resets on engine switch, Kokoro's default
  voice is now `am_echo`, and fixes (queue reads cache under the picked engine,
  Qwen3 foreign-voice fallback, visible background-job outcomes, silenced torch
  load warnings). State/GUI/jobs tests throughout.
- [x] **Portable voice layer — internal names + cross-engine map in the sidecar**
  (2026-06-17, merged to `main` in PR #1; CHANGELOG `[Unreleased]`): the `.narration`
  grammar grew a deck-level preamble (`default-voice:` + a `voices:` block mapping
  an internal name → per-engine voice), parsed via `parse_document`/`NarrationDoc`
  (list-only `parse_sidecar` still works), `FORMAT_VERSION` bumped to 2 with a
  byte-stable round-trip (v1 files untouched). `Deck` carries `voices`/
  `default_voice`; load/save populate and re-emit them; `synth.speech_refs` merges
  the deck map over the toml library (deck wins) and applies `default-voice`, so a
  kokoro→elevenlabs switch renarrates with **zero** sidecar edits. Both
  `slidesonnet check` *and* the editor warn on a named voice with no mapping for
  the active engine (`voice-unmapped`); in the editor the warning lights the slide
  and follows the engine picker. `tests/test_voices.py` + grammar/state/diagnostic
  tests. *Remaining GUI-edit affordance split out to Now #2.*
- [x] **Qwen3-TTS local own-voice engine** (2026-06-17, merged to `main` in PR #1;
  CHANGELOG `[Unreleased]`): a free `--engine qwen3` backend (the `[qwen3]` extra)
  that narrates a deck in a cloned voice from a local `.pt` prompt — the expressive
  / own-voice path Kokoro can't do. `qwen3` `BackendSpec` (`realtime=False`),
  `[tts.qwen3]` config, lazy-and-warm load with a process-wide `_MODEL_CACHE`,
  atomic WAV writes, content-hash cache key, clean `TTSError` on missing
  package/prompt/no-audio, `doctor` check. Per-utterance voices reach the `.pt`
  through the portable voice map (relative to the deck dir); the editor shows a
  distinct "Loading the voice model…" status on first load and disables
  auto-generate (`paid OR not realtime`). Fully mocked-unit-tested
  (`tests/test_qwen3.py`) plus a local-only real-weights smoke test behind the
  extra. *Human record-and-judge step split out to Now #5; a per-utterance `.pt`
  content-hash cache nicety is the only remaining debt (Next).*
- [x] **GUI generation-engine picker (session-only)** (2026-06-17, merged to `main`
  in PR #1; CHANGELOG `[Unreleased]`): an **Engine** dropdown in the editor console
  (installed engines + the active one) sets a session `selected_backend`; generate
  / "Generate missing" / preview / export thread it through the api, and the paid +
  realtime auto-build gate, voice picker, audio badges, and footer all follow it.
  Never written to disk (relaunch returns to Kokoro). Fixed a latent bug where
  `auto_build_active()` ignored the realtime gate. State + GUI tests. *`[tts] backend`
  is kept as the initial default; full removal as a config key stays deferred.*
- [x] **Published 1.0.0a1 — first public alpha** (2026-06-16): repo flipped to
  public, `v1.0.0a1` tagged and pushed; the publish workflow shipped TestPyPI →
  PyPI → GitHub Release (CI + Publish both green at 02:07 / 03:04 UTC). All
  pre-flight blockers (LICENSE, sidecar-grammar docs rewrite, ElevenLabs dropped
  from docs, PyMuPDF AGPL note, secrets scan) cleared first. Shipped with the
  Kokoro-rendered demo videos; the HQ re-render is deferred to Next (post-Inworld).
- [x] **All editor-pass known issues resolved** (KNOWN_ISSUES #1–#9, 2026-06-15):
  the seven editor-reliability bugs + the recompile won't-repro (#8) + the CI
  typecheck regression (#9) are all fixed with green tests and recorded in
  CHANGELOG a1. `dev/KNOWN_ISSUES.md` retired (empty).
- [x] **Background generation job queue + auto-build on save** (2026-06-15):
  audio synthesis moved off the editor's single busy gate onto a background
  worker (`gui/jobs.py`), keyed on the content-addressed cache filename so two
  requests for one clip coalesce and **play** awaits any in-flight job instead
  of racing or double-synthesizing. Per-utterance generate, "generate missing",
  and play all route through it; the per-clip button shows a queued/generating
  spinner. New opt-in **"Auto-generate as I edit"** checkbox (off by default,
  persisted, local-only) fills the deck in the background and regenerates each
  edited slide after a debounce, skipping the utterance under the cursor. Kokoro
  writes were made atomic (temp+rename) for safe concurrency. Covered by
  `tests/test_jobs.py` + new GUI flow tests (responsiveness, play-awaits-job,
  paid-disabled, sweep, debounced incremental). The former Next #8.
- [x] **CI typecheck fix** (2026-06-15): `main`'s `typecheck` job had been red
  since 2026-06-12 — `mypy` couldn't find `numpy` (`kokoro.py:132`), which ships
  only with the `[kokoro]` extra while CI's typecheck installs `.[dev]`. Added
  `numpy.*` to `[[tool.mypy.overrides]]`. KNOWN_ISSUES #9.
- [x] **Editor reliability pass** (2026-06-15): seven bugs found running a real
  course deck through the editor, each reproduced in a test first, then fixed —
  PDF/config refresh no longer dumps unsaved narration, `(mtime,size)` change
  detection catches same-second recompiles, mid-playback edits revoke the loaded
  track, Ctrl-S saves in place, "play all" starts at the current slide,
  "generate missing" leaves unaffected playback alone, and slide images cache-
  bust after a recompile. An eighth (recompile→top-slide) was closed
  won't-reproduce. Per-bug record in `dev/KNOWN_ISSUES.md`; commit `f932525`.
- [x] **Non-destructive sidecar save** (shipped 2026-06-12). Unedited saves are
  byte-identical, edits rewrite only the touched block, comments above an edited
  block survive, and hand-wrapped `text:` lines parse as continuations.
- [x] **Re-verified both demos end-to-end with Kokoro** (2026-06-12) — `make
  basel`/`showcase` + `check-*`; reconciled clean, human approved the MP4s
  (audio "decent but not amazing", acceptable for a1, to be superseded by the
  HQ re-render).
- [x] **Full-codebase review remediation** (2026-06-12) — five PR groups
  (bugs/safety, dead-code sweep, test suite, editor perf, refactors); per-item
  record in `dev/REVIEW-2026-06.md`.
- [x] **v2 converged and merged to `main`** (2026-06-12): editor UX pass
  (structured utterances/pauses/transitions, block editor, per-utterance
  generation, unattached-narration tray, transport rework, live reload),
  real-browser Playwright test tier, CI green on `main` *at merge time* (the
  typecheck job later regressed — see Now #1 / KNOWN_ISSUES #9). Stale branches
  (`v2`, `ux-pass`) deleted.
- [x] **Python floor set to 3.13** (2026-06-12) — CI only ever tested 3.13;
  `requires-python` now matches instead of advertising an untested 3.12.
- [x] Branch `v2` (né `v2-narration-editor`); old source→video pipeline removed.
- [x] M0 backend spine: `\ssid` macro, PDF id extraction, sidecar parse/serialize,
  id-only diagnostics, timing model, `init`/`check`/`doctor`/`sty`.
- [x] M1 headless media: cache-aware TTS, audio track + cue sheet, video export
  (tts/estimate/fixed, `--silent`), SRT/VTT subtitles, typed `slidesonnet.api`.
- [x] M2/M3 NiceGUI editor: nav, edit, per-slide TTS, whole-deck preview, diagnostics.
- [x] Demos converted to the new format (basel-problem + showcase).
- [x] Docs (README, CHANGELOG), Makefile, `mypy --strict` + ruff + tests green.
- [x] `\ssid` invisible (PDF text-mode-3) slide-id markers, overlay-step aware,
  validated against real overlay decks.
- [x] Round-trip-stable sidecar grammar (`@id`, `:voice`/`:pace`, `[pause N]`).
- [x] PyMuPDF id extraction + `pdftoppm` rasterization.
- [x] id-only diagnostics (duplicate/auto/missing/orphan/order).
- [x] Timing model: tts / estimate(wpm) / fixed:N; silent renders.
- [x] Cache-aware synthesis (content-addressed, pace→speed), reused FFmpeg composer.
- [x] SRT + WebVTT, segment/slide granularity.
- [x] NiceGUI editor with automated user-simulation tests.
- [x] Typed `slidesonnet.api` mirroring the CLI.
- [x] Optional `slidesonnet.toml` config; `.slidesonnet/` cache layout.
- [x] **Kokoro 82M replaces Piper as the local TTS engine** (2026-06-10).
  Clearly more natural sound (near top of the open-weights TTS arena) at
  ~2× real-time on CPU (RTF ~0.5), so no GPU needed. Notes kept from the
  evaluation: Intel iGPU acceleration possible via the XPU/IPEX path; the
  *vanilla* OpenVINO GPU backend fails on Kokoro (unsupported 3D-tensor
  interpolation) — don't go that route. Limited expressive control (voice
  pick + blending only), so Qwen3 remains the expressive/own-voice path.
