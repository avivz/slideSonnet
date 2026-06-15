# Roadmap

Current version: 1.0.0a0 (alpha) — the PDF + narration-sidecar editor rewrite.

See `CHANGELOG.md` for shipped changes.

Lane tags: **[agent]** = an agent can do it end-to-end · **[agent→human]** =
agent does the work, human approves/verifies · **[human]** = needs the human
(paid, irreversible, or account-bound).

## Now — publish 1.0.0a1

1. [ ] **Repo public pre-flight, then flip visibility** — secrets scan,
   license check, README accuracy pass by agent (drop or caveat the
   ElevenLabs install section pending the Inworld switch below); human runs
   `gh repo edit --visibility public`. Must precede the PyPI tag (the package
   links to the GitHub URL). **[agent→human]**
2. [ ] **Tag `v1.0.0a1` and push** — bump `src/slidesonnet/__init__.py`, move
   CHANGELOG Unreleased → a1, push tag; triggers TestPyPI → PyPI → GitHub
   Release. Ship with the Kokoro-rendered demo videos; don't block on the
   paid HQ render. **[human]**
3. [ ] **Crossfade compositing.** *Story:* As a deck author, I want the
   `crossfade: N` transition I set in the editor to render as an actual
   crossfade in the MP4, so the export matches what the editor promises.
   Today it's stored, edited, and conflict-checked but renders as a hard
   cut. *Acceptance examples:* (a) two-slide deck with
   `transition-out: crossfade 1.0` → exported video blends for 1 s and total
   duration shrinks by 1 s; (b) audio acrossfades with no click; (c)
   all-`cut` decks export identically to today. *Appetite:* two days. Needs
   `build_timeline` to learn overlap (it assumes back-to-back cuts); a
   legacy unwired `concatenate_segments_xfade` sits in
   `src/slidesonnet/video/composer.py` — predates the v1 rewrite, don't
   assume it's drop-in (deliberately kept through the 2026-06 dead-code
   sweep for this item). **[agent]**

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
   own little PR:
   - When narration text is edited, immediately (before blur) flip the box's
     regenerate icon to *generate* and mark the slide not-up-to-date; if the
     edit is undone while typing, revert. (Partly related to editor pass #3,
     which already revokes the loaded track on edit — this is the per-box icon
     + dirty-state half that's still open.)
   - Play at 1.5×/2× speed for preview.
   - Generate Kokoro audio quietly in the background once text has been stable
     for a while.
   - Let "play all" start before everything is generated, and pause if
     playback ever catches up to the generation frontier.
   - Make "generate all" interruptible (it currently can't be stopped mid-run;
     also verify the same for generation inside "play all").

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
7. **Slide transitions** — fade and wipe (left/right/up/down) transitions
   between pages, giving limited animation for Beamer-style sub-slides (a
   PDF whose consecutive pages are overlay incrementals of one logical
   slide). Composite the transition during the FFmpeg video step; needs a
   way to mark which page boundaries are sub-slide steps vs. real slide
   changes, plus a per-transition type/duration knob. FFmpeg's `xfade`
   filter already implements a large gallery of transitions
   (<https://trac.ffmpeg.org/wiki/Xfade>) — expose the full set if it's
   cheap to wire the transition name straight through to `xfade`.

## Done (v1 rewrite)

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
