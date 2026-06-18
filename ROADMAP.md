# Roadmap

Current version: 1.0.0a1 (alpha, published to PyPI 2026-06-16) — the PDF +
narration-sidecar editor rewrite. Repo is public.

See `CHANGELOG.md` for shipped changes. A large post-a1 batch sits in CHANGELOG
`[Unreleased]`, on `main`, untagged: the background generation queue + auto-build,
the portable voice layer, the Qwen3 local engine (built-in CustomVoice speakers,
prioritized auto-gen, progress UI, cancellable play / cancel-all), the in-editor
Voices dialog + named-only utterance picker, auto-prune of local orphans, and the
transition-gallery core. None of it is tagged yet — 1.0.0a2 is the next release.

Lane tags: **[agent]** = an agent can do it end-to-end · **[agent→human]** =
agent does the work, human approves/verifies · **[human]** = needs the human
(paid, irreversible, or account-bound).

## Now — next feature work (toward 1.0.0a2)

1. [~] **Transition gallery (full `xfade` set) — core shipped, follow-ups
   remain.** *(The gallery itself is in `CHANGELOG [Unreleased]`; what's left is
   the absorb-source extension + the over-long warning, in "Remaining follow-ups"
   below.)* *Story:* As a deck author, I
   want to pick from FFmpeg's whole `xfade` transition gallery — not just a
   crossfade but `fade`, `wipeleft/right/up/down`, `slide*`, `dissolve`,
   `circleopen`, `pixelize`, etc. — set per page boundary, and have the export
   render exactly that. Across real slide changes a transition is a flourish;
   across **sub-slide steps** (consecutive PDF pages that are overlay
   incrementals of one logical Beamer/Typst slide) a wipe/slide reads as a
   *build animation*, recovering the motion a flat PDF throws away. Today only
   `cut`/`crossfade` exist in the model and even `crossfade` renders as a hard
   cut. **Render model (decided 2026-06-16, revised 2026-06-18): centered overlay**
   — a `D`-second transition is a *visual overlay centered on the A→B boundary*
   (D/2 over the tail of A, D/2 over the head of B), playing over whatever audio is
   already there (silence or speech); it never changes the audio or the deck's total
   duration, so preview stays aligned with no timeline surgery. (Supersedes the
   earlier "absorb into the outgoing tail only, clamp if too long" plan — see the
   reshaped follow-ups below.) *Acceptance examples:* (a) `transition-out: wipeleft 0.5` → exported
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
   preview audio track is fingerprint-cached so a repeat play does no ffmpeg.

   *Reshaped follow-ups — explicit per-slide silences + centered-overlay
   transitions (design locked 2026-06-18):* the invisible global hold/lead
   (`[video] tail_seconds`/`pre_silence`) becomes a **per-slide, editable
   silence** the author controls, and the transition becomes a centered visual
   overlay (above). Rules: (1) **every slide has a leading and a trailing
   silence** — not pinned blocks but *positional*: the last block, if a pause, *is*
   the trailing silence, otherwise an implicit default silence follows it (the
   front mirrors it). Adding an utterance inserts it *before* the trailing silence;
   moving an utterance after a pause demotes that pause to mid-slide and a fresh
   implicit silence reappears at the end. (2) **Absent = default; explicit
   replaces** — a slide with no authored silence renders with the deck default;
   authoring `pause: 2` as the trailing block makes the hold *exactly* 2s (not 2 +
   default), and `pause: 0` means no hold (the "really quick change" case). (3)
   **The GUI materializes implicit→explicit on save** — opening a deck and saving
   writes the start/end `pause:` lines for every slide (a one-time large diff, by
   design); the **CLI/API path leaves them implicit** and honors the defaults when
   absent. (4) **Centered-overlay render** — `transition-out: wipeleft 0.8` between
   A and B draws an 0.8s wipe centered on the boundary (0.4s over A's tail, 0.4s
   over B's head) as a pure visual overlay: the assembled audio track and the
   deck's total duration are byte-identical to the same deck rendered all-`cut`.
   Where the centered window overlaps speech (silence pool smaller than `D`), the
   morph simply plays over the narration — no clamp, no pad (can feel rushed on a
   real slide change; accepted). The one surviving clamp+warn case: a transition
   longer than twice the shorter adjacent slide can't be centered, so it's clamped
   and `slidesonnet check` warns. *Acceptance examples:* (a) the editor shows an
   editable **start silence** and **end silence** per slide, defaulting to the deck
   value; setting end silence to 0 flips with no hold; (b) `transition-out:
   wipeleft 0.8` renders centered on the boundary with the audio track + total
   duration byte-identical to the all-`cut` render; (c) a deck never opened in the
   GUI round-trips byte-stable and renders identically to today (defaults honored);
   (d) opening that deck in the GUI and saving materializes every slide's start/end
   `pause:` lines once, after which the render is still identical; (e) a 2s
   transition on a 0.3s slide is clamped with a `check` warning. *Appetite:* ~three
   days (model/grammar default-silence semantics + per-slide editor fields +
   centered-overlay render & preview-morph re-center + tests). The preview morph
   still approximates a few families (`pixelize`/`dissolve` → fade) — fine for
   proofing, only the export is pixel-exact. Gallery reference:
   <https://trac.ffmpeg.org/wiki/Xfade>. **[agent]**

2. [ ] **Per-engine cache prune policy — stop auto-prune from throwing away
   Qwen3 audio.** *(Risk surfaced by the just-shipped auto-prune of local
   orphans.)* `EditorState._write_and_reload` → `prune_local_orphans` sweeps any
   orphaned clip whose engine is **not paid** (`clean.py:102`, gated on
   `API_BACKENDS`). Qwen3 is `paid=False` but slow/expensive on the iGPU (seconds
   per clip), so an edit can silently discard minutes of just-generated own-voice
   audio. *Story:* As a deck author rendering with a heavy local engine, I want my
   freshly-generated Qwen3 clips to survive an edit, so I don't pay the
   regeneration cost for a one-word fix elsewhere in the deck. *Acceptance
   examples:* (a) editing utterance A's text does **not** delete a now-orphaned
   Qwen3 clip for the *old* text of A (or for an unrelated slide) — Qwen3 orphans
   are kept by default; (b) Kokoro orphans are still pruned eagerly (unchanged);
   (c) ElevenLabs (paid) is still never auto-swept (unchanged); (d) the keep/drop
   decision reads from a single per-engine policy on `BackendSpec` (e.g.
   `prune_policy: eager | keep-paid | keep-expensive-local | never`), not a
   hardcoded `paid` check, so a new engine declares its policy in one place;
   (e) `slidesonnet clean --keep nothing` still removes everything on explicit
   request. *Appetite:* half a day. *Design note:* add the policy field to the
   registry in `tts/__init__.py`, replace the `parsed[1] in API_BACKENDS` test in
   `prune_local_orphans` with a policy lookup; repro test in `test_clean.py`
   (Qwen3 orphan survives, Kokoro orphan removed). **[agent]**
3. [ ] **Qwen3 own-voice: record + judge the reference clip.** *(The engine is
   shipped and mocked-tested — see Done. This is the one human step gating a real
   own-voice render: nothing about Qwen3 has run on real weights + a real voice
   yet.)* *Story:* As the deck author, I want to record a ~10 s reference, build
   the `.pt` clone prompt, and judge the cloned voice, so I can decide whether
   Qwen3 is good enough to ship an own-voice render. *Acceptance examples:* (a) a
   fresh ~10 s reference is recorded and `create_voice_clone_prompt` produces a
   `.pt` under `dev/voice-profile/` (git-excluded); (b) `SLIDESONNET_QWEN3_PROMPT=…
   pytest -m integration -k real_weights` passes locally on the iGPU/XPU path
   (downloads real weights once, clones, writes a non-empty WAV); (c) the human
   listens to a short rendered sample and records a verdict (ship / refine the
   reference / not yet). *Appetite:* an afternoon (mostly the human's; the agent
   can drive the recording→`.pt`→smoke-test mechanics). *Note:* the `[qwen3]` extra
   isn't installed in the dev venv (heavy torch + multi-GB weights), so this also
   covers the one-time `pip install -e ".[qwen3]"`. **[human→agent]**
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
   - A newly-added utterance inherits the deck's default voice. Today
     `BlockEditor.add_segment` creates `Segment.speech("")` with **no** voice, so
     a new line shows the explicit "default" option and resolves through the
     fallback chain. Make that default explicit and visible, with a strict
     precedence: **deck default first** (sidecar `default-voice:`, or a config
     key); **if that doesn't exist, the engine default**. *Acceptance:* (a) with
     `default-voice: lecturer` set, adding a line starts on `lecturer` (shown
     selected in the picker); (b) with **no** deck default set, adding a line
     falls through to the active engine's own default (Kokoro `am_echo`, Qwen3
     Vivian) — **not an error**, the line is created unset and the "default" option
     stays valid with nothing pinned; (c) the new line round-trips: an unset line
     writes no `voice:` (stays portable), and a line is only written with an
     explicit `voice:` once the author changes it off the default. *Appetite:* an
     hour.
   - Toggle transitions in single-slide preview. A single-slide play currently
     *always* renders that slide's own in/out transitions (the preview morph,
     against a black frame at the deck ends) — useful for proofing the
     transition, but a needless flourish when you just want to hear one slide's
     narration. Add an editor checkbox to opt into it. *Acceptance:* a checkbox
     (e.g. "Play transitions in single-slide preview"), **off by default**, gates
     the single-slide morph — unchecked, a single-slide play uses a plain cut (no
     transition); checked, it plays the slide's in/out transitions as today. The
     whole-deck preview is unaffected either way, and the setting is local/editor
     state (not written to the deck).
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

9. [ ] **Wire the director's note to supporting models.** *Story:* As a deck
   author, I write a per-utterance *direction* — "cheerfully", "slow and somber",
   "as an aside" — and the engines that can act on a natural-language style cue
   actually do, so the same script can be delivered with intent rather than flat.
   The `direction` field already exists end-to-end (sidecar grammar `direct:`,
   the editor's per-utterance input, round-trip-stable) but **no engine consumes
   it today** — it's collected and ignored. The natural target is Qwen3, whose
   CustomVoice and VoiceDesign models take an `instruct=` style prompt
   (`generate_custom_voice(..., instruct=...)`); cloud engines map it to whatever
   style controls they expose (or ignore it). *Acceptance examples:* (a) an
   utterance with `direct: cheerfully` on Qwen3 CustomVoice passes that string as
   `instruct` and the clip is audibly more upbeat than the same text without it;
   (b) the direction joins the audio cache key (see the standing note in
   `hashing.py`) so editing the note regenerates exactly the affected clips and
   nothing else; (c) an engine that has no style input ignores the direction with
   no error, and the editor signals which engines honor it (mirroring how the
   voice picker marks per-engine support); (d) an empty/whitespace direction is
   indistinguishable from none (no spurious cache churn, no empty `instruct`).
   *Appetite:* ~one day. *Design note:* the per-segment `direction` already flows
   to `SpeechRef`; the work is threading it through `synth` → `TTSEngine.synthesize`
   (a new optional `direction` arg, default None, ignored by Kokoro) → Qwen3's
   `generate_custom_voice/voice_design`, plus folding it into the hash. **[agent]**

10. [ ] **Batched synthesis for heavy engines (use the spare iGPU).** *Story:* As
    a deck author on a local GPU, my Qwen3 generation pins the iGPU at only ~50%
    because autoregressive decoding is latency-bound, not compute-bound — so the
    queue should synthesize a small *batch* of nearby clips in one `generate`
    call (qwen_tts's `generate_custom_voice`/`generate_voice_clone` already accept
    list inputs and run the sequences together), filling the idle gaps without the
    thread-safety hazard of two `generate()`s on one cached model or the ~2×
    memory of a second model instance. *Acceptance examples:* (a) with auto-build
    on and several uncached clips near the cursor, the worker pops up to N (e.g.
    2–4) and synthesizes them in a single batched call, measurably raising iGPU
    utilization and clips/min over the one-at-a-time loop; (b) batching respects
    the distance priority (the batch is the N best-next clips) and the play
    preempt still aborts the whole in-flight batch promptly; (c) light/realtime
    engines (Kokoro) and the CLI path are unaffected — batching is opt-in per
    engine via a `batch_size`/capability, default 1; (d) a batched clip's cache
    file, duration, and hash are identical to generating it alone (batching is a
    throughput optimization, not a content change). *Appetite:* ~two days.
    *Design note:* the worker currently pops one `JobHandle`; batching means
    popping the top-N pending by priority into one synth call and a `synthesize_batch`
    on the engine (default = loop), with the heavy path overriding it. **[agent]**

## Next — toward 1.0 final

1. [ ] **Unify logging across the project** (from inbox). Generation feedback is
   ad-hoc: the job worker and editor `print("[gen] …")` straight to stdout, while
   the rest of the code uses module `logger`s whose output never appears because
   logging is never configured (no handler/level at CLI/editor startup) — so
   `logger.info`/`logger.exception` calls are invisible, which is why a swallowed
   background-job failure had to be band-aided with a `print`. *Story:* As someone
   running slideSonnet, I want consistent, level-controlled output so I can see
   progress and diagnose failures without reading the source. *Acceptance
   examples:* (a) logging is configured once at CLI/editor startup (handler +
   level), so a `logger.info` from any module reaches the terminal; (b) a
   `--verbose`/`--quiet` flag or `SLIDESONNET_LOG` env var sets the level;
   (c) the `print("[gen] …")` progress lines become structured `logger` calls (or
   are deliberately kept as the few user-facing progress lines, with everything
   else routed through logging); (d) a background-job failure is logged with a
   traceback at the configured level, no longer silently swallowed. *Appetite:*
   half a day. **[agent]**
2. [ ] **Test audit remainder** — browser (Playwright) tier landed; remaining
   gaps to fill deliberately: export timing modes end-to-end, `check`
   diagnostics on real overlay decks, editor save/reload paths. Finish with
   a joint human+AI review of coverage and quality. **[agent→human]**
3. [ ] **HQ demo re-render with Inworld** — replaces the previously planned
   ElevenLabs render (don't pay ElevenLabs for renders we're about to drop).
   Blocked on Now #4 (the Inworld engine). Human triggers the paid render;
   agent uploads to the `v0.0.0` GitHub Release (`gh release upload --clobber`)
   and refreshes README links. **[human→agent]**
4. [ ] **Qwen3-TTS DashScope cloud mode** — a `mode = "dashscope"` arm of the
   now-shipped Qwen3 engine (see Done) for users without a local GPU: ~$0.13/10 min,
   no infra, but the voice leaves the machine (and needs one-time voice enrollment).
   Same `BackendSpec`/engine interface, `paid=True`, the same mocked-client test
   guard as ElevenLabs/Inworld (never a real paid call in CI). Serverless GPU
   (Modal/RunPod, ~$0.01/10 min) is a further variant. The local engine has landed,
   so this is now unblocked. **[agent→human]**
5. [ ] **Qwen3 per-utterance `.pt` content-hash in the cache key** (debt from the
   shipped engine). A per-utterance voice-map `.pt` folds its *path*, not its
   *content hash*, into the clip cache key, so editing a clone artifact in place
   needs a manual regenerate (the config-default prompt already content-hashes).
   *Acceptance:* editing a `.pt` referenced by a `voices:` entry invalidates that
   voice's cached clips on the next generate; moving/renaming the file does not
   churn the cache. *Appetite:* an hour. **[agent]**
6. [ ] **Upload demo videos to YouTube** — needs the human's account/auth and
   an unlisted-vs-public decision; agent preps titles, descriptions, and
   chapter markers from the narration sidecars. **[human]**
7. [ ] **README refresh** — new video links, Kokoro install instructions,
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
   interface). (Qwen3-TTS local shipped — see Done; Inworld is Now #4; the Qwen3
   DashScope cloud mode is Next #3.)
5. **Multi-deck playlists** — concatenate several PDFs into one video.
6. **`--json` output** for CI/automation.
7. *(Promoted & merged into Now #3 "Transition gallery" on 2026-06-15 — the
   sub-slide-animation use case and the full xfade gallery are now part of that
   item, not a separate backlog entry.)*

## Done (v1 rewrite)

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
  extra. *Human record-and-judge step split out to Now #3; a per-utterance `.pt`
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
