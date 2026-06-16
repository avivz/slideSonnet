# Roadmap

Current version: 1.0.0a0 (alpha) — the PDF + narration-sidecar editor rewrite.

See `CHANGELOG.md` for shipped changes.

Lane tags: **[agent]** = an agent can do it end-to-end · **[agent→human]** =
agent does the work, human approves/verifies · **[human]** = needs the human
(paid, irreversible, or account-bound).

## Now — publish 1.0.0a1

1. [ ] **Flip visibility to public.** Pre-flight pass run 2026-06-15 — all
   blockers cleared, only the human action remains:
   - ✅ **`LICENSE`** — exists, valid MIT, tracked (the earlier "missing"
     finding was a false alarm from a shell glob error).
   - ✅ **Sidecar-grammar docs rewritten** — `README.md` and `docs/authoring.md`
     converted from the removed flat `:voice`/`:pace`/inline-`[pause]` format to
     the v1 block format (`utterance:`/`text:`/`pause: N`/`transition-*`).
   - ✅ **ElevenLabs dropped** from both docs (pending the Inworld switch,
     Next #1).
   - ✅ **PyMuPDF AGPL-3.0 note** added to the README License section.
   - ✅ **Secrets** — none in tree or across 232 commits of history; `.env`
     never tracked + gitignored (guarded by `tests/test_no_secrets.py`); `dev/`
     never committed; logo + `--keep exact` present/accurate.

   Remaining: human runs `gh repo edit --visibility public`. Must precede the PyPI tag
   (the package links to the GitHub URL). **[agent→human]**
2. [ ] **Tag `v1.0.0a1` and push** — bump `src/slidesonnet/__init__.py`, move
   CHANGELOG Unreleased → a1, push tag; triggers TestPyPI → PyPI → GitHub
   Release. Ship with the Kokoro-rendered demo videos; don't block on the
   paid HQ render. **[human]**
3. [ ] **Transition gallery (full `xfade` set).** *Story:* As a deck author, I
   want to pick from FFmpeg's whole `xfade` transition gallery — not just a
   crossfade but `fade`, `wipeleft/right/up/down`, `slide*`, `dissolve`,
   `circleopen`, `pixelize`, etc. — set per page boundary, and have the export
   render exactly that. Across real slide changes a transition is a flourish;
   across **sub-slide steps** (consecutive PDF pages that are overlay
   incrementals of one logical Beamer/Typst slide) a wipe/slide reads as a
   *build animation*, recovering the motion a flat PDF throws away. Today only
   `cut`/`crossfade` exist in the model and even `crossfade` renders as a hard
   cut. *Acceptance examples:* (a) `transition-out: wipeleft 0.6` →
   exported video wipes left over 0.6 s and total duration shrinks by 0.6 s;
   (b) `crossfade N` still works (now just one entry in the gallery, mapped to
   xfade `fade`/`dissolve`); (c) an unknown/misspelled transition name is a
   `check` error, not a silent cut; (d) all-`cut` decks export byte-identically
   to today; (e) the editor's transition picker offers the full gallery as a
   dropdown. *Appetite:* ~three days (the gallery itself is nearly free once
   one xfade type is wired — the cost is the model/grammar/editor plumbing).
   *Design notes:* `TransitionKind` (`narration/model.py`) grows from
   `cut|crossfade` to carry an xfade transition name; the sidecar grammar
   `transition-out: <name> <seconds>` passes `<name>` straight through to
   xfade's `transition=` param. `build_timeline` must learn overlap (it assumes
   back-to-back cuts); a legacy unwired `concatenate_segments_xfade` sits in
   `src/slidesonnet/video/composer.py` (predates the v1 rewrite — don't assume
   it's drop-in). Audio: acrossfade across real slide changes; across a
   sub-slide build the narration is usually continuous, so don't force an audio
   blend there. Gallery reference: <https://trac.ffmpeg.org/wiki/Xfade>.
   **[agent]**

## Next — after a1

1. [ ] **Switch the cloud engine: ElevenLabs → Inworld TTS** — Inworld beats
   ElevenLabs on control *and* price (~$0.009/min vs ~$0.10–0.27/min), with
   Markdown-style emotion control, top quality-to-price on the 2026 arena,
   and instant own-voice cloning from a ~5–15 s clip (consent attestation
   standard; voice + clip leave the machine). Researched 2026-06-10. Agent
   implements the engine behind the engine interface (mocked unit tests, a
   `[tts.inworld]` config section + extra); human supplies the API key, runs
   a small paid smoke test, and judges voice quality. Decision point: keep
   ElevenLabs as a legacy optional backend or remove it outright (as was
   done with Piper). **Needs acceptance examples before build** — e.g.
   "given `[tts.inworld]` with a key, `slidesonnet tts deck.pdf --engine
   inworld` synthesizes one clip per utterance, content-addressed cached"
   plus a mocked API-failure example. **[agent→human]**
2. [ ] **Orphaned-narration leftovers** (tray already shipped): a deck-level
   "Checks · deck" console section for pageless diagnostics, and saving
   pending edits before PDF-triggered reloads. *Note:* the keystroke-loss
   part is now mostly handled — a PDF/config-only refresh keeps the field
   (editor pass #1); what remains is saving edits before a *sidecar*-triggered
   reload, and never auto-saving on those. *Appetite:* half a day each.
   **[agent]**
3. [ ] **Test audit remainder** — browser (Playwright) tier landed; remaining
   gaps to fill deliberately: export timing modes end-to-end, `check`
   diagnostics on real overlay decks, editor save/reload paths. Finish with
   a joint human+AI review of coverage and quality. **[agent→human]**
4. [ ] **HQ demo re-render with Inworld** — replaces the previously planned
   ElevenLabs render (don't pay ElevenLabs for renders we're about to drop).
   Human triggers the paid render; agent uploads to the `v0.0.0` GitHub
   Release (`gh release upload --clobber`) and refreshes README links.
   **[human→agent]**
5. [ ] **Qwen3-TTS own-voice engine (third optional backend)** — narrate
   decks in the user's own voice from a ~10 s reference clip. Qwen3-TTS
   (Apache 2.0) clones via a tiny reusable prompt artifact (~100 KB `.pt`:
   codec tokens + speaker embedding); quality clearly above Piper. Runs
   three ways: local GPU (works on Intel iGPU via XPU, ~4× slower than
   real-time — fine for cached re-renders), serverless GPU (Modal/RunPod,
   ~$0.01/10 min), or the official DashScope API (~$0.13/10 min, no infra,
   but voice leaves the machine). Evaluated 2026-06-10; assets + lessons in
   `dev/voice-profile/`. Agent implements behind the engine interface as an
   optional extra; human records the reference clip and judges the cloned
   voice. **[agent→human]**
6. [ ] **Upload demo videos to YouTube** — needs the human's account/auth and
   an unlisted-vs-public decision; agent preps titles, descriptions, and
   chapter markers from the narration sidecars. **[human]**
7. [ ] **README refresh** — new video links, Kokoro install instructions,
   editor screenshots of the new dark studio theme. **[agent]**
8. [ ] **Minor UX flow fixes** — small editor quality-of-life items, each its
   own little PR (the background job queue they build on shipped — see Done):
   - When narration text is edited, immediately (before blur) flip the box's
     regenerate icon to *generate* and mark the slide not-up-to-date; if the
     edit is undone while typing, revert. (Partly related to editor pass #3,
     which already revokes the loaded track on edit — this is the per-box icon
     + dirty-state half that's still open.)
   - Play at 1.5×/2× speed for preview.
   - Let "play all" start before everything is generated, and pause if
     playback ever catches up to the generation frontier. *(builds on the queue)*
   - Make "generate all" / a queued background generation interruptible (today a
     queued sweep runs to completion; add a cancel/stop for the queue).

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
   interface). (Qwen3-TTS and Inworld promoted to Next on 2026-06-11.)
5. **Multi-deck playlists** — concatenate several PDFs into one video.
6. **`--json` output** for CI/automation.
7. *(Promoted & merged into Now #3 "Transition gallery" on 2026-06-15 — the
   sub-slide-animation use case and the full xfade gallery are now part of that
   item, not a separate backlog entry.)*

## Done (v1 rewrite)

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
