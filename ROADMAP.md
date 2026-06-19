# Roadmap

Current version: 1.0.0a1 (alpha, published to PyPI 2026-06-16) — the PDF +
narration-sidecar editor rewrite. Repo is public.

See `CHANGELOG.md` for shipped changes. A large post-a1 batch sits in CHANGELOG
`[Unreleased]`, on `main`, untagged: the background generation queue + auto-build,
the portable voice layer, the Qwen3 local engine (built-in CustomVoice speakers,
prioritized auto-gen, progress UI, cancellable play / cancel-all), the in-editor
Voices dialog + named-only utterance picker, auto-prune of local orphans, the
**full transition gallery, per-slide start/end silences, and centered-overlay
transitions** (the last three landed 2026-06-18 — see Done), the **Inworld cloud
engine** (ElevenLabs now removed), and the **paid-synth confirmation + `.env`
loading fixes**. None of it is tagged yet, but **CI is green again as of
2026-06-19** — the `test`-job hang that blocked every push since the qwen-voices
merge is fixed (see Done). So 1.0.0a2 is **unblocked**: the top item below is now
shipping it (after the one prune-policy fix that gates it).

Lane tags: **[agent]** = an agent can do it end-to-end · **[agent→human]** =
agent does the work, human approves/verifies · **[human]** = needs the human
(paid, irreversible, or account-bound).

## Now — next feature work (toward 1.0.0a2)

1. [ ] **Tag & ship 1.0.0a2 — now unblocked (CI is green).** *(The single
   highest-leverage item now that CI passes on `main` (633ccc5): a large
   `[Unreleased]` batch sits on `main`, shipped and tested but installable by
   no one.)* *Story:* As a slideSonnet user on PyPI, I want the work that's
   already on `main` — the full transition gallery, per-slide silences and
   centered-overlay transitions, the Qwen3 local engine, the portable voice
   layer, the Voices dialog, and the background generation queue — in an
   installable release, so I'm not stuck on a1's feature set. *Acceptance
   examples:* (a) `src/slidesonnet/__init__.py` `__version__` is bumped to
   `1.0.0a2`; (b) `CHANGELOG.md`'s `[Unreleased]` is retitled `[1.0.0a2] —
   <date>` with a fresh empty `[Unreleased]` above it; (c) `make test-unit` is
   green locally and CI's lint/typecheck/test/build all pass on `main`; (d)
   `git tag v1.0.0a2 && git push origin v1.0.0a2` drives the publish workflow
   (TestPyPI → PyPI → GitHub Release) to green. *Sequencing:* CI is green (the
   publish workflow runs the same suite), so the one gate left is the prune-policy
   fix (#2) — land it first so a2 doesn't ship the Qwen3-audio-loss risk;
   everything else in Now/Next is post-a2. *Appetite:* an afternoon (mostly
   verification + the human's tag push). **[human→agent]**

2. [ ] **Per-engine cache prune policy — stop auto-prune from throwing away
   Qwen3 audio.** *(The one gate before a2 — see #1.)* *(Risk surfaced by the just-shipped auto-prune of local
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
   (c) Inworld (paid) is still never auto-swept (unchanged); (d) the keep/drop
   decision reads from a single per-engine policy on `BackendSpec` (e.g.
   `prune_policy: eager | keep-paid | keep-expensive-local | never`), not a
   hardcoded `paid` check, so a new engine declares its policy in one place;
   (e) `slidesonnet clean --keep nothing` still removes everything on explicit
   request. *Appetite:* half a day. *Design note:* add the policy field to the
   registry in `tts/__init__.py`, replace the `parsed[1] in API_BACKENDS` test in
   `prune_local_orphans` with a policy lookup; repro test in `test_clean.py`
   (Qwen3 orphan survives, Kokoro orphan removed). **[agent]**
3. [ ] **Bug: changing a pause/edge-silence doesn't refresh the loaded "Play
   all" track.** *(Open bug, priority-1 quality — full write-up in
   `dev/KNOWN_ISSUES.md`. Not an a2 blocker; pick up right after the release
   path above.)* *Symptom:* after **Play all**, change a slide's pause length or
   Start/End silence, then press **Play all** again — the preview still plays the
   *old* pauses. The loaded whole-deck track isn't revoked because the
   silence/pause number fields commit only on `blur`/Ctrl+S, so a play press while
   the field still has focus never rebuilds (resume replays the stale track).
   Sibling of the just-fixed external-edit stale-preview bug (see Done) — both are
   the "stale loaded track" family; the fix here is to flush open fields on any
   play press and rebuild if the flush changed the block. *Repro test (first
   action, browser tier — the in-process `user` sim is blind to focus/blur):* Play
   all a generated deck, change End-silence, press Play all again *without*
   blurring, assert the new track's duration reflects the change. *Appetite:* half
   a day. **[agent]**
4. [ ] **Bug: a renamed named-voice lingers in the per-utterance voice picker.**
   *(Open bug, priority-1 quality — full write-up in `dev/KNOWN_ISSUES.md`. Not an
   a2 blocker.)* *Symptom:* rename a voice in the **Voices…** dialog (e.g.
   `lecturer` → `host`) and save — the per-utterance **Voice** picker still offers
   `lecturer`, and utterances that used it still show `lecturer` (now resolving as
   *unmapped*) instead of following the rename. *Cause:* the rename updates the
   deck's `voices:` map key but nothing rewrites the references —
   `EditorState.edit_voices` is handed only the new full map, so it can't tell a
   rename from a delete-old + add-new. *Fix:* make rename a first-class op (track
   per-row old→new identity in the Voices dialog, rewrite every utterance `voice:`
   and `default-voice` == old → new before saving). *Repro test (first action):*
   in `tests/test_voices.py` — seed `voices: {lecturer}` + an utterance
   `voice: lecturer`, rename → `host`, assert the utterance now references `host`,
   `voice_options()` no longer contains `lecturer`, and the sidecar round-trips
   with no `lecturer` left. *Appetite:* half a day. **[agent]**
5. [ ] **Qwen3 own-voice: record + judge the reference clip.** *(The engine is
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
6. [ ] **Validate Inworld on a real paid run — smoke test + voice-quality
   judgement.** *(The engine shipped on `main` and ElevenLabs is removed — see
   Done. This is the one human step left before Inworld is a trusted render path;
   it gates the HQ demo re-render, Next #3.)* *Story:* As the deck author, I want
   to run a small paid Inworld synthesis and judge the voice, so I can decide
   whether to use it for the HQ demo. *Acceptance examples:* (a) with
   `INWORLD_API_KEY` in `.env`, `slidesonnet tts <deck> --engine inworld`
   synthesizes a handful of real clips, each content-addressed cached (a re-run
   makes zero API calls) and costing a few cents; (b) the human listens and records
   a verdict (ship / tune voice+emotion / not yet); (c) Markdown-style emotion
   control and a ~5–15 s own-voice clone are spot-checked if the verdict is "tune".
   *Appetite:* an hour (mostly the human's; the agent drives the CLI and reports
   cost + cache hits). *Note:* the supporting fixes already landed — `.env` loads
   on the synthesis path (anchored at the deck dir) and "Generate missing" confirms
   before billing a paid engine. **[human→agent]**
7. [ ] **Accelerated narration playback (1.25×/1.5×/2×).** *Story:* As a deck
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
8. [ ] **Minor UX flow fixes** — small editor quality-of-life items, each its
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
9. [ ] **Orphaned-narration leftovers** (tray already shipped): a deck-level
   "Checks · deck" console section for pageless diagnostics, and saving
   pending edits before PDF-triggered reloads. *Note:* the keystroke-loss
   part is now mostly handled — a PDF/config-only refresh keeps the field
   (editor pass #1); what remains is saving edits before a *sidecar*-triggered
   reload, and never auto-saving on those. *Acceptance:* a sidecar edited on
   disk while you have unsaved field text saves your text first (no silent loss),
   and never auto-saves on a sidecar-triggered reload. *Appetite:* half a day each.
   **[agent]**
## Next — toward 1.0 final

1. [ ] **Unify logging across the project** (from inbox; reaffirmed 2026-06-19 as
   the requested "general sweep for logs"). Generation feedback is
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
   traceback at the configured level, no longer silently swallowed. *Recent
   example (2026-06-19):* the `.env`-not-loaded bug surfaced only as a terse
   `[gen] … FAILED` print; a configured logger with the traceback would have
   pointed straight at the missing-key cause. *Appetite:*
   half a day. **[agent]**
2. [ ] **Test audit remainder** — browser (Playwright) tier landed; remaining
   gaps to fill deliberately: export timing modes end-to-end, `check`
   diagnostics on real overlay decks, editor save/reload paths. Finish with
   a joint human+AI review of coverage and quality. **[agent→human]**
3. [ ] **HQ demo re-render with Inworld** — replaces the previously planned
   ElevenLabs render (ElevenLabs is now removed — see Done). Blocked on Now #6
   (the Inworld paid validation + voice-quality verdict). Human triggers the render;
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
8. [ ] **Open / switch decks from within the editor.** *(Was Now; deferred
   post-a2 — a session-management feature, not release-blocking.)* *Story:* As a
   user with several decks, I want to open another deck from inside `slidesonnet
   edit` without quitting and relaunching on a new path, so I can move between
   projects in one session. *Acceptance examples:* (a) an "Open deck…" control
   accepts another deck PDF (same or another directory) and re-points the whole
   editor — filmstrip, sidecar, diagnostics, audio cache, live-reload poller —
   onto it; (b) switching while the current deck has unsaved narration edits saves
   them first (or prompts), never silently dropping them (shares the
   save-before-reload guard with the orphaned-leftovers Now item); (c) the new
   deck's `slidesonnet.toml` engine/voices take effect (re-read, not the prior
   deck's); (d) the transport is stopped and rewound on switch — no audio from the
   previous deck bleeds into the new one; (e) decks are discoverable: a path input
   plus, if cheap, a list of sibling `*.pdf` that have a `.narration` sidecar in
   the launch directory. *Appetite:* ~one to two days. *Design note:* today
   `build_editor` constructs a single `EditorState` from the launch path and
   starts one live-reload poller; switching means tearing down that poller and
   re-initializing state in place (or routing to a fresh page) rather than
   assuming one deck per process. **[agent]**
9. [ ] **Wire the director's note to supporting models.** *(Was Now; deferred
   behind the Inworld/Qwen3 engine work it depends on.)* *Story:* As a deck
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
10. [ ] **Config audit — what's necessary vs vestigial.** A pass over the
   user-facing config surface (`slidesonnet.toml` → `config.py`/`models.py`) and
   the project's own config files to find keys/sections that are dead, redundant,
   or now defaulted-away. Known candidates: `[tts] backend` (kept only as the
   initial editor default — the engine picker is session-state; full removal as a
   config key was deferred — see Done). (The `elevenlabs_*` keys are already gone —
   see Done, ElevenLabs removal.) *Story:* As someone configuring a deck, I want the documented config to be
   only what still does something, so I'm not cargo-culting dead keys. *Acceptance
   examples:* (a) a written inventory of every config key with a keep/drop/merge
   call and reason; (b) dropped keys removed from `Config`/`TTSConfig` parsing,
   their defaults, and the docs, with a `### Removed`/`### Changed` CHANGELOG note;
   (c) `make test-unit` + typecheck green. *Appetite:* half a day. **[agent→human]**
11. [ ] **Pre-assemble the "Play all" track in the background (opt-in).** *Story:*
   As a deck author who has finished generating narration, I want the whole-deck
   audio track assembled in the background while I'm idle, so pressing **Play all**
   starts instantly instead of waiting for the FFmpeg concat. *Acceptance examples:*
   (a) a new checkbox (e.g. **"Pre-build Play-all audio"**), **off by default** and
   persisted like "Auto-generate as I edit"; with it on, once the generation queue
   is idle *and* every clip is cached, the whole-deck track assembles in the
   background, and a later **Play all** uses it with no visible "building preview"
   wait; (b) the pre-build never competes with generation — it gates on the queue's
   idle signal (`JobQueue.await_idle` / `_idle`, `gui/jobs.py`) and only fires when
   nothing is pending or running, and a real Play preempts it; (c) any edit
   (narration text, voice, per-slide silence, transition) or a fresh generate
   invalidates the prebuilt track, which re-assembles in the background once things
   settle (debounced) — Play all never serves stale audio; (d) with the checkbox
   **off**, behavior is unchanged (assemble on demand at Play-all time). *Appetite:*
   half a day. *Design note:* reuse `preview_deck`/`build_preview`; cache the
   assembled track keyed to a deck/config/voice hash so an edit invalidates it.
   Complements the Now #8 sub-item "let Play all start before everything is
   generated" — that's *partial* play mid-generation; this is *instant* play once
   the deck is fully generated and idle. **[agent]**
12. [ ] **Cache inventory — show what's cached (count + size) before clearing it.**
   *(From a 2026-06-19 request; the visibility precursor to a cache-clearing UX
   the user plans to build. The counting already exists —
   `clean.py::_count_dir(path) -> (files, bytes)` and `CleanResult.removed_mb`.)*
   *Story:* As a deck author about to clear the TTS cache, I want to see how many
   utterances are cached and how much disk they use — and how much a clear
   reclaimed — so I can decide whether to clear and confirm afterward that
   something actually happened. *Acceptance examples:* (a) a cache-status readout
   reports the **number of cached utterance clips** and their **total size in MB**
   for the deck's content-addressed audio cache (`.slidesonnet/audio/`), e.g.
   "142 clips · 86.3 MB"; (b) it separates the reclaimable audio cache from render
   artifacts so the number matches what a clear would remove at the chosen
   `--keep` level; (c) clearing then reports the before→after delta ("removed 96
   clips · freed 58.1 MB") for visible confirmation — surface the existing
   `CleanResult.removed_mb`; (d) the inventory is a pure read (mutates nothing) and
   pairs with the planned `clean --dry-run` (Later #5). *Open question — surface:*
   CLI (a `cache`/`clean --dry-run` header) and/or an editor panel? The request
   ties it to the editor's cache-clearing flow, so likely both — **decide the
   surface before build.** *Appetite:* half a day (sizing is `_count_dir`; the work
   is the surface + before/after delta). **[agent]**

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
   interface). (Qwen3-TTS local shipped — see Done; Inworld is Now #6; the Qwen3
   DashScope cloud mode is in Next.)
5. **Multi-deck playlists** — concatenate several PDFs into one video.
6. **`--json` output** for CI/automation.
7. **Batched synthesis for heavy engines (use the spare iGPU).** *(Was Now;
   deferred — a throughput optimization that only pays off once a real Qwen3
   own-voice render is happening, which is itself gated on the record+judge step.)*
   *Story:* As a deck author on a local GPU, my Qwen3 generation pins the iGPU at
   only ~50% because autoregressive decoding is latency-bound, not compute-bound —
   so the queue should synthesize a small *batch* of nearby clips in one
   `generate` call (qwen_tts's `generate_custom_voice`/`generate_voice_clone`
   already accept list inputs and run the sequences together), filling the idle
   gaps without the thread-safety hazard of two `generate()`s on one cached model
   or the ~2× memory of a second model instance. *Acceptance examples:* (a) with
   auto-build on and several uncached clips near the cursor, the worker pops up to
   N (e.g. 2–4) and synthesizes them in a single batched call, measurably raising
   iGPU utilization and clips/min over the one-at-a-time loop; (b) batching
   respects the distance priority (the batch is the N best-next clips) and the
   play preempt still aborts the whole in-flight batch promptly; (c) light/realtime
   engines (Kokoro) and the CLI path are unaffected — batching is opt-in per
   engine via a `batch_size`/capability, default 1; (d) a batched clip's cache
   file, duration, and hash are identical to generating it alone (batching is a
   throughput optimization, not a content change). *Appetite:* ~two days.
   *Design note:* the worker currently pops one `JobHandle`; batching means
   popping the top-N pending by priority into one synth call and a
   `synthesize_batch` on the engine (default = loop), with the heavy path
   overriding it. **[agent]**
8. *(Promoted & merged into the transition gallery on 2026-06-15 — the
   sub-slide-animation use case and the full xfade gallery shipped as part of it;
   see Done.)*

## Done (v1 rewrite)

- [x] **External narration edits no longer leave a stale preview** (2026-06-19,
  `a3638b6`; CHANGELOG `[Unreleased]` `### Fixed`, ships in a2). With a whole-deck
  or single-slide preview loaded, hand-editing the `.narration` sidecar on disk
  (e.g. changing a transition) reloaded the editor's fields but kept the *old*
  preview track — pressing play resumed stale audio and the stale transition
  morph instead of rebuilding. `_poll_sources` now revokes a loaded preview track
  on any external reload (mirroring what `replace_block` already does for in-GUI
  edits). Found while using the editor; reproduced first as browser journey 11
  (`test_external_edit_revokes_loaded_preview`), red→green. The in-GUI blur-timing
  sibling (silence/pause fields) is still open — now Now #3.
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
