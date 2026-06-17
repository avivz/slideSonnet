# Roadmap

Current version: 1.0.0a1 (alpha, published to PyPI 2026-06-16) — the PDF +
narration-sidecar editor rewrite. Repo is public.

See `CHANGELOG.md` for shipped changes. Post-a1 work (background generation
queue + auto-build) sits in CHANGELOG `[Unreleased]`, on `main`, untagged.

Lane tags: **[agent]** = an agent can do it end-to-end · **[agent→human]** =
agent does the work, human approves/verifies · **[human]** = needs the human
(paid, irreversible, or account-bound).

## Now — next feature work (toward 1.0.0a2)

1. [ ] **Transition gallery (full `xfade` set).** *Story:* As a deck author, I
   want to pick from FFmpeg's whole `xfade` transition gallery — not just a
   crossfade but `fade`, `wipeleft/right/up/down`, `slide*`, `dissolve`,
   `circleopen`, `pixelize`, etc. — set per page boundary, and have the export
   render exactly that. Across real slide changes a transition is a flourish;
   across **sub-slide steps** (consecutive PDF pages that are overlay
   incrementals of one logical Beamer/Typst slide) a wipe/slide reads as a
   *build animation*, recovering the motion a flat PDF throws away. Today only
   `cut`/`crossfade` exist in the model and even `crossfade` renders as a hard
   cut. **Render model (decided 2026-06-16): absorb-into-hold** — a `D`-second
   transition plays *during the outgoing slide's trailing hold*, so the deck's
   total duration and audio are unchanged and preview stays aligned (no timeline
   surgery). *Acceptance examples:* (a) `transition-out: wipeleft 0.5` → exported
   video wipes left over 0.5 s during slide A's tail hold; total duration equals
   the all-`cut` render (transition absorbed, not added/subtracted); (b)
   `crossfade N` still works (now one entry in the gallery, mapped to xfade
   `fade`); (c) an unknown/misspelled transition name is a `check`/parse error,
   not a silent cut; (d) all-`cut` decks export byte-identically to today; (e)
   the editor's transition picker offers the curated gallery via a short Type +
   Direction picker. *Appetite:* ~three days.
   *Progress (branch `feat/transition-gallery`):* ✅ contract (taxonomy module +
   model/grammar, `test_transition_gallery.py`); ✅ picker UX (Type+Direction
   selects, GUI + browser tests); ✅ rendering (`compose_transition_clip` +
   `compose_video` absorb-into-hold, integration-tested: total unchanged, morph
   clip produced); ✅ in-editor preview morph (a client-side overlay,
   `gui/static/morph.html` driven by `_morph_schedule`, approximates the xfade
   in the browser and **completes at the cue boundary** to match the export's
   timing — whole-deck *and* single-slide play, the latter showing the slide's
   own in/out transitions against a black frame at the deck ends;
   `test_morph_schedule_*`/`_single_slide_morph` + browser journeys); ✅
   `fadeblack`/`fadewhite` families ("Fade through black/white"); ✅ the
   preview audio track is fingerprint-cached so a repeat play does no ffmpeg. *Remaining follow-ups:*
   the transition is currently absorbed into the slide's `tail_seconds` hold only
   and **clamped** to it (a longer request is shortened + logged) — extend to
   also draw from the next slide's `pre_silence` lead and from trailing `pause:`
   segments, and add the "small added gap" fallback when a boundary has no hold;
   surface an over-long-transition warning in `slidesonnet check`; and the
   preview morph approximates a few families (e.g. `pixelize`/`dissolve` fall
   back to a fade) — fine for proofing, only the export is pixel-exact. Audio is left
   continuous (no acrossfade), which is correct for sub-slide builds. Gallery
   reference: <https://trac.ffmpeg.org/wiki/Xfade>. **[agent]**

2. [ ] **Portable voice layer — internal voice names + cross-engine map in the
   narration file.** *Story:* As a deck author, I want to name voices by an
   internal name (e.g. `lecturer`, `guest`) defined *in the narration file*, where
   each name maps to a concrete per-engine voice, plus a deck-level
   `default-voice`, so the same self-contained deck narrates under any engine
   without touching the script and the editor only ever shows my own names. This
   makes the `.narration` portable (the voice definitions travel with it) and is
   the foundation Qwen3 (Now #3) reaches its `.pt` prompts through. *Decision
   (2026-06-16): the map lives in the narration file* (portability over a terser
   script); toml `[voices.NAME]` stays as an optional shared fallback. *Acceptance
   examples:* (a) the sidecar gains an optional `voices:` block mapping internal
   names → per-engine voices (`lecturer: {kokoro: am_michael, qwen3:
   ./voice/lecturer.pt, elevenlabs: <id>}`, file-based voices stored relative to
   the deck dir) and a top-level `default-voice: lecturer`; it round-trips
   byte-stable and bumps the `# slidesonnet-format:` header to 2 (v1 files still
   parse; the greater-version upgrade-warning path already exists); (b) an
   utterance with `voice: guest` resolves to the active engine's `guest` voice,
   with no `voice:` it uses `default-voice`, with neither the engine default —
   switching `[tts] backend` kokoro→qwen3 renarrates the same script with **zero**
   sidecar edits; (c) the editor's voice picker shows internal names only (raw
   engine voices, if offered at all, drop to an advanced affordance), and the
   unset-voice placeholder shows the deck `default-voice`; (d) an internal name
   with no mapping for the active engine is a clean `check`/editor warning
   ("voice 'guest' has no qwen3 voice"), not a silent fallback or a crash; (e)
   backward-compat — a deck whose voices live in toml `[voices.NAME]` still works,
   and a narration `voices:` entry wins over a toml entry of the same name (shared
   library + per-deck override both work). *Appetite:* ~two days (grammar +
   parse/serialize + resolver + editor picker + tests). *Design notes:* the
   resolution is already built — `VoiceConfig.backend_voices` + `resolve_voice`
   (`models.py:25`) map a name → backend voice; extend the parser to read a sidecar
   `voices:` block and merge it over the toml map (sidecar wins), and teach
   `voice_options()`/`default_voice()` (`state.py:340`) to source from the deck map.
   **[agent]**
3. [~] **Qwen3-TTS own-voice engine (local XPU/GPU first).**
   *Progress (branch `feat/qwen3-tts`):* ✅ the engine + wiring landed — `qwen3`
   `BackendSpec` (free `.wav`, `realtime=False`), the `Backend` literal + sync
   test, `[tts.qwen3]` config (model/device/voice_prompt/language, prompt path
   resolved relative to the toml), lazy-and-warm model load, atomic WAV writes,
   content-hash cache key, clean `TTSError` on missing package/prompt/no-audio,
   `doctor` check, the `[qwen3]` extra + mypy overrides, and the editor
   auto-generate gate now keys on `paid OR not realtime` (disabled for Qwen3 with
   a "too slow" tooltip). All mocked-unit-tested (`tests/test_qwen3.py` + config/
   doctor/gui/registry tests); `mypy --strict` + ruff green. *Remaining:* the
   editor's first-load "Loading Qwen3 model…" status; the real-weights
   `@pytest.mark.integration` smoke test behind the extra (local-only); per-utterance
   multi-voice via the portable voice layer (Now #2); and the human records the
   ~10 s reference + judges the cloned voice. *Story:* As a deck
   author, I want a `--engine qwen3` local backend that narrates my deck in **my
   own voice** from a reusable voice-clone prompt, so I can ship a personal HQ
   render without paying a cloud TTS or sending my voice off the machine.
   Qwen3-TTS (Apache 2.0) clones from a tiny precomputed prompt artifact (a
   ~100 KB `.pt`: codec `ref_code` + speaker x-vector) and runs locally — on the
   laptop's Intel iGPU via the XPU path (~4× slower than real-time, fine for a
   cached offline render). The reference recordings and three ready `.pt`
   artifacts already exist in `dev/voice-profile/` (git-excluded — it's the
   user's voice identity). This is the *expressive / own-voice* path Kokoro can't
   do. *Decision (2026-06-16): local XPU/GPU only for the first cut* — `paid=False`,
   optional `[qwen3]` extra; the DashScope cloud mode is a deferred follow-up
   (Later) behind the same engine interface. *Acceptance examples:* (a) given
   `[tts.qwen3]` with `model`, `device`, and a `voice_prompt` path to a `.pt`
   artifact, `slidesonnet tts deck.pdf --engine qwen3` synthesizes one cached WAV
   per utterance in the cloned voice, and a re-run makes **zero** model calls
   (content-addressed; the cache key folds in the model id, device, and the
   prompt artifact's hash, so swapping the voice prompt invalidates the cache);
   (b) the engine is `paid=False` — the editor generates and auto-generates
   without the paid-confirm gate; (c) a missing `qwen_tts` package, a missing or
   unreadable `voice_prompt` file, or a model that produces no audio each surface
   as a clean `TTSError` with an install/config hint — never a traceback — and an
   atomic temp+rename write leaves no half-WAV on failure (like Kokoro); (d)
   `slidesonnet doctor` reports qwen3 configured/unconfigured from the package
   being importable **and** the prompt file existing; (e) every unit test mocks
   the Qwen3 model (no ~11 GB HF download, no XPU in CI); the real-weights path is
   a single `@pytest.mark.integration` test behind the `[qwen3]` extra, local-only.
   *Appetite:* ~two to three days for the agent's engine + mocked tests; human
   records/refreshes the ~10 s reference clip (the speed sweet spot) and judges the
   cloned voice. *Design notes:* device handling must avoid `device_map` on the
   Intel iGPU and use bf16 on XPU (see the [[intel-xpu-wsl-pytorch]] recipe and the
   `dev/voice-profile/README.md` usage block); `create_voice_clone_prompt` is the
   one-time step — the engine loads the existing `.pt` and reuses it so cloning
   costs the same as plain generation. *UI integration (decided 2026-06-16):* (1) **Qwen3 voices are reached through the
   portable voice layer (Now #2), never raw paths** — a Qwen3 voice is an internal
   name in the narration `voices:` block that maps to a `.pt` artifact path
   (relative to the deck dir); no path ever sits in a per-utterance `voice:` field,
   and the editor shows only the internal name (so the same script renarrates under
   Kokoro/Inworld unchanged). The artifact's **content hash** (not the path string)
   folds into the cache key, so editing the prompt invalidates while moving it
   doesn't churn. `list_voices()` returns `()` (names come from the deck's map);
   `default_voice()` defers to the deck `default-voice`. (2) **Auto-generate gate keys on a
   new engine-level "auto-generate safe" signal, not `paid`** — add the flag
   (Kokoro safe; Qwen3 *and* every paid engine not-safe), so the "Auto-generate as
   I edit" checkbox disables for Qwen3 with a *too-slow-to-fire-on-every-edit*
   tooltip (distinct from the paid "would bill" message); gate = `paid OR
   not-realtime`. *Hard implementation constraints (from the editor's call
   pattern):* `voice_options()`/`default_voice()` run `create_tts(...)` **every
   render tick** (`state.py:349,354`), so the Qwen3 constructor and those two
   methods must **not** touch the model — load it lazily and keep it **warm**
   across clips (cache the model + the loaded `.pt`, like Kokoro's `_pipeline_for`);
   give the first model load its own "Loading Qwen3 model…" status distinct from
   per-clip generation; a missing `qwen_tts`, a missing/unreadable prompt, or no
   XPU/CUDA each surface a clean `TTSError`, never a traceback or a silent CPU
   grind. Adding the backend is one `BackendSpec` in `tts/__init__.py` (now also
   carrying the auto-generate-safe flag), the `qwen3` arm of the `Backend` Literal
   in `models.py` (a test pins them in sync), and the `[tts.qwen3]` config fields.
   **[agent→human]**
4. [ ] **Switch the cloud engine: ElevenLabs → Inworld TTS.** *Story:* As a
   deck author who wants studio-grade narration, I want a `--engine inworld`
   cloud backend that synthesizes one cached clip per utterance, so I can
   render an HQ demo without paying ElevenLabs' ~10× rate. Inworld beats
   ElevenLabs on control *and* price (~$0.009/min vs ~$0.10–0.27/min), with
   Markdown-style emotion control, top quality-to-price on the 2026 arena,
   and instant own-voice cloning from a ~5–15 s clip (consent attestation
   standard; voice + clip leave the machine). Researched 2026-06-10. This is
   also the debt behind "ElevenLabs dropped pending the switch" in the a1 docs.
   *Acceptance examples:* (a) given `[tts.inworld]` with an API key, `slidesonnet
   tts deck.pdf --engine inworld` synthesizes one clip per utterance, each
   content-addressed cached (re-run makes zero API calls); (b) a mocked API
   failure surfaces as a clean `TTSError`, not a traceback, and leaves no
   half-written cache file (atomic write, like Kokoro); (c) `slidesonnet doctor`
   reports the engine as configured/unconfigured from the key's presence;
   (d) every Inworld test uses a mocked client — the suite never makes a real
   paid call (same guard pattern as the ElevenLabs conftest sentinel).
   *Appetite:* ~two days for the agent's engine + mocked tests. Agent implements
   behind the engine interface (a `[tts.inworld]` config section + extra); human
   supplies the key, runs a small paid smoke test, and judges voice quality.
   Decision point: keep ElevenLabs as a legacy optional backend or remove it
   outright (as was done with Piper). **[agent→human]**
5. [ ] **Accelerated narration playback (1.25×/1.5×/2×).** *Story:* As a deck
   author proofing narration, I want to play the preview faster so I can review
   a long deck without sitting through every clip at 1×. *Acceptance examples:*
   (a) a speed control in the transport (e.g. 1× / 1.25× / 1.5× / 2×, or a
   cycling button) sets the audio element's playback rate live — pressing it
   mid-play speeds up immediately with **no re-synthesis** and no cache write;
   (b) the chosen speed sticks across slide changes and across both
   *play-slide* and *play-all* (whole-deck preview), and the deck preview's
   automatic slide flips still land on cue at the faster rate; (c) the seek bar
   and elapsed/total clock stay consistent with the audio's media timeline while
   sped up (a 2× pass over a 10 s clip finishes in ~5 s of wall-clock);
   (d) speed is **preview-only** — it never affects the synthesized cache, the
   `pace:` directive, or the exported video. *Appetite:* an afternoon. *Design
   note:* this is HTML5 `audio.playbackRate` on the transport's player, not a
   TTS-level change — distinct from the per-utterance `pace:` directive, which
   re-synthesizes. Browser pitch-correction (`preservesPitch`) is on by default,
   so 2× stays natural, not chipmunked. **[agent]**
6. [ ] **Minor UX flow fixes** — small editor quality-of-life items, each its
   own little PR (the background job queue they build on shipped — see Done).
   *Appetite:* an afternoon each.
   - When narration text is edited, immediately (before blur) flip the box's
     regenerate icon to *generate* and mark the slide not-up-to-date; if the
     edit is undone while typing, revert. (Partly related to editor pass #3,
     which already revokes the loaded track on edit — this is the per-box icon
     + dirty-state half that's still open.) *Acceptance:* typing in an utterance
     flips its badge to amber within a keystroke; Ctrl-Z back to the original
     text restores the green badge without a save.
   - Let "play all" start before everything is generated, and pause if
     playback ever catches up to the generation frontier. *(builds on the queue)*
     *Acceptance:* pressing play-all on a half-generated deck starts immediately
     and pauses (not errors) when it reaches the first ungenerated clip, resuming
     once the queue catches up.
   - Make "generate all" / a queued background generation interruptible (today a
     queued sweep runs to completion; add a cancel/stop for the queue).
     *Acceptance:* a "Stop" on the sweep drains the queue and leaves already-made
     clips intact.
7. [ ] **Orphaned-narration leftovers** (tray already shipped): a deck-level
   "Checks · deck" console section for pageless diagnostics, and saving
   pending edits before PDF-triggered reloads. *Note:* the keystroke-loss
   part is now mostly handled — a PDF/config-only refresh keeps the field
   (editor pass #1); what remains is saving edits before a *sidecar*-triggered
   reload, and never auto-saving on those. *Acceptance:* a sidecar edited on
   disk while you have unsaved field text saves your text first (no silent loss),
   and never auto-saves on a sidecar-triggered reload. *Appetite:* half a day each.
   **[agent]**
8. [ ] **Open / switch decks from within the editor.** *Story:* As a user with
   several decks, I want to open another deck from inside `slidesonnet edit`
   without quitting and relaunching on a new path, so I can move between projects
   in one session. *Acceptance examples:* (a) an "Open deck…" control accepts
   another deck PDF (same or another directory) and re-points the whole editor —
   filmstrip, sidecar, diagnostics, audio cache, live-reload poller — onto it;
   (b) switching while the current deck has unsaved narration edits saves them
   first (or prompts), never silently dropping them (shares the save-before-reload
   guard with Now #5); (c) the new deck's `slidesonnet.toml` engine/voices take
   effect (re-read, not the prior deck's); (d) the transport is stopped and
   rewound on switch — no audio from the previous deck bleeds into the new one;
   (e) decks are discoverable: a path input plus, if cheap, a list of sibling
   `*.pdf` that have a `.narration` sidecar in the launch directory. *Appetite:*
   ~one to two days. *Design note:* today `build_editor` constructs a single
   `EditorState` from the launch path and starts one live-reload poller; switching
   means tearing down that poller and re-initializing state in place (or routing
   to a fresh page) rather than assuming one deck per process. **[agent]**

## Next — toward 1.0 final

1. [ ] **Test audit remainder** — browser (Playwright) tier landed; remaining
   gaps to fill deliberately: export timing modes end-to-end, `check`
   diagnostics on real overlay decks, editor save/reload paths. Finish with
   a joint human+AI review of coverage and quality. **[agent→human]**
2. [ ] **HQ demo re-render with Inworld** — replaces the previously planned
   ElevenLabs render (don't pay ElevenLabs for renders we're about to drop).
   Blocked on Now #2 (the Inworld engine). Human triggers the paid render;
   agent uploads to the `v0.0.0` GitHub Release (`gh release upload --clobber`)
   and refreshes README links. **[human→agent]**
3. [ ] **Qwen3-TTS DashScope cloud mode** — a `mode = "dashscope"` arm of the
   Qwen3 engine (Now #2) for users without a local GPU: ~$0.13/10 min, no infra,
   but the voice leaves the machine (and needs one-time voice enrollment). Same
   `BackendSpec`/engine interface, `paid=True`, the same mocked-client test guard
   as ElevenLabs/Inworld (never a real paid call in CI). Serverless GPU
   (Modal/RunPod, ~$0.01/10 min) is a further variant. Blocked on Now #2 landing
   the local engine first. **[agent→human]**
4. [ ] **Upload demo videos to YouTube** — needs the human's account/auth and
   an unlisted-vs-public decision; agent preps titles, descriptions, and
   chapter markers from the narration sidecars. **[human]**
5. [ ] **README refresh** — new video links, Kokoro install instructions,
   editor screenshots of the new dark studio theme. **[agent]**

## Later — before 1.0 final

1. **Narration schema validation** (decided 2026-06-12): publish an EBNF
   grammar of the sidecar format in docs (with `slidesonnet check` as the
   reference validator) and add `narration export --json` emitting a JSON
   projection with a published JSON Schema for LLM/CI round-tripping. Don't
   YAML-ify the format — the terse `@id` grammar is the product.
2. **Multi-take TTS / re-roll takes** — generation is stochastic; users may
   want to re-roll an utterance and keep/compare takes. Blocked on a cache
   design decision: today the cache is content-addressed (text+voice+config
   → one file), so N takes need a take index in the key or a side `takes/`
   store, plus UI to audition/pick. Until then the per-utterance generate
   button's "fresh take" re-roll overwrites the cached clip.
3. **`init` default sidecar UX** — richer scaffold comments (per-page titles
   pulled from the PDF outline, if present).
4. **Editor polish leftovers** — engine/voice picker, export dialog with
   timing/subtitle options. (Keyboard nav and single-slide preview already
   shipped — see CHANGELOG Unreleased.)
5. **`clean --dry-run`** — preview what would be removed.
6. **`check --fix`** — offer to re-sort the sidecar to PDF order and scaffold
   missing blocks in one step.
7. **Watch mode** — re-preview on sidecar save in the editor.
8. **Per-segment voice switching mid-utterance** — utterances already carry
   per-utterance voices; this is about a voice switch *within* one utterance
   (today: split into two utterances).

## Later — backlog

1. **Backend service/daemon architecture** (discussion wanted) — should
   slidesonnet stay a blocking per-invocation command, or become a resident
   service the GUI/CLI auto-spawn and attach to (socket/port discovery, idle
   shutdown)? Buys warm TTS models, shared cache state, faster editor
   startup. Agent writes an options memo; human decides. Post-1.0.
2. **id-injection adapters** (designed, deferred): Marp theme
   span, PPTX `python-pptx` textbox, Google Slides API. Same marker contract.
3. **Layered reconciliation** — optional text-fingerprint fallback when ids are
   missing, for non-Beamer sources.
4. **More TTS backends** — Cartesia, Azure, Google Cloud (follow the engine
   interface). (Qwen3-TTS local promoted to Now #2 on 2026-06-16; Inworld is
   Now #3; the Qwen3 DashScope cloud mode is Next #3.)
5. **Multi-deck playlists** — concatenate several PDFs into one video.
6. **`--json` output** for CI/automation.
7. *(Promoted & merged into Now #3 "Transition gallery" on 2026-06-15 — the
   sub-slide-animation use case and the full xfade gallery are now part of that
   item, not a separate backlog entry.)*

## Done (v1 rewrite)

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
