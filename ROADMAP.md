# Roadmap

Current version: 1.0.0a0 (alpha) — the PDF + narration-sidecar editor rewrite.

See `CHANGELOG.md` for shipped changes.

Lane tags: **[agent]** = an agent can do it end-to-end · **[agent→human]** =
agent does the work, human approves/verifies · **[human]** = needs the human
(paid, irreversible, or account-bound).

## Now — converge and verify v2 (release critical path)

1. [ ] **Review & approve the UX pass (`v2-editor-ux`)** — code review +
   lint/typecheck/unit on the branch by agent; human approves look-and-feel
   in the live editor. Everything merges through this branch. **[agent→human]**
2. [ ] **Resolve loose ends** — the uncommitted `basel-problem.narration`
   edit in the working tree (human confirms it's wanted). **[agent→human]**
3. [ ] **Update `ci.yml` + `publish.yml` for v2** — add 3.12 to the test
   matrix (or drop the 3.12 claim from `pyproject.toml`), make CI run on the
   v2 branches, verify the publish smoke test against the new dependency set
   (PyMuPDF, NiceGUI). Gate for everything downstream — v2 has never run on
   GitHub CI. **[agent]**
4. [ ] **Better tests** — audit what the integration tests actually exercise
   vs. what slips through; fill gaps (export timing modes end-to-end, editor
   save/reload paths, `check` diagnostics on real overlay decks); finish with
   a joint human+AI review of coverage and quality. **[agent→human]**
5. [ ] **Re-verify both demos end-to-end with Kokoro** — `make basel`,
   `make showcase`, `make check-basel`, `make check-showcase`; validates the
   metropolis restyle + `.latexmkrc` + Kokoro changes together. Human watches
   the resulting MP4s. **[agent→human]**

## Next — publish 1.0.0a1

1. [ ] **Merge `v2-editor-ux` → `v2` → `main`**, watch CI green (after Now #1
   is approved). **[agent]**
2. [ ] **Repo public pre-flight, then flip visibility** — secrets scan,
   license check, README accuracy pass by agent; human runs
   `gh repo edit --visibility public`. Must precede the PyPI tag (the package
   links to the GitHub URL). **[agent→human]**
3. [ ] **Tag `v1.0.0a1` and push** — triggers TestPyPI → PyPI → GitHub
   Release. Ship with the Kokoro-rendered demo videos; don't block on the
   paid ElevenLabs render. **[human]**
4. [ ] **ElevenLabs HQ re-render of the demos** — costs API credits, human
   triggers the render; agent uploads to the `v0.0.0` GitHub Release
   (`gh release upload --clobber`) and refreshes README links. **[human→agent]**
5. [ ] **Upload demo videos to YouTube** — needs the human's account/auth and
   an unlisted-vs-public decision; agent preps titles, descriptions, and
   chapter markers from the narration sidecars. **[human]**
6. [ ] **README refresh** — new video links, Kokoro install instructions,
   editor screenshots of the new dark studio theme. **[agent]**

## Later — before 1.0 final

1. **`init` default sidecar UX** — richer scaffold comments (per-page titles
   pulled from the PDF outline, if present).
2. **Editor polish leftovers** — engine/voice picker, export dialog with
   timing/subtitle options. (Keyboard nav and single-slide preview already
   shipped — see CHANGELOG Unreleased.)
3. **`clean --dry-run`** — preview what would be removed.
4. **`check --fix`** — offer to re-sort the sidecar to PDF order and scaffold
   missing blocks in one step.
5. **Watch mode** — re-preview on sidecar save in the editor.
6. **Per-segment voice** — allow a voice switch mid-block (today voice is
   per-slide; multi-voice needs splitting into separate `\ssid` steps).

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
   interface).
5. **Qwen3-TTS backend with own-voice cloning** — narrate decks in the user's
   own voice from a ~10 s reference clip. Qwen3-TTS (Apache 2.0) clones via a
   tiny reusable prompt artifact (~100 KB `.pt`: codec tokens + speaker
   embedding); quality clearly above Piper. Runs three ways: local GPU (works
   on Intel iGPU via XPU, ~4× slower than real-time — fine for cached
   re-renders), serverless GPU (Modal/RunPod, ~$0.01/10 min), or the official
   DashScope API (~$0.13/10 min, no infra, but voice leaves the machine).
   Evaluated 2026-06-10; assets + lessons in `dev/voice-profile/`.
6. **Inworld TTS managed backend** — test it as a cloud engine (follow the
   engine interface). Beats ElevenLabs on control *and* price (~$0.009/min vs
   ElevenLabs ~$0.10–0.27/min), with Markdown-style emotion control and top
   quality-to-price on the 2026 arena. Most relevant here: **instant own-voice
   cloning from a ~5–15 s clip**, making it a managed counterpart to the Qwen3
   own-voice plan — no GPU infra, but the voice + reference clip leave the
   machine (privacy tradeoff vs local Qwen3). Consent attestation now standard.
   Researched 2026-06-10.
7. **Multi-deck playlists** — concatenate several PDFs into one video.
8. **Crossfade / transitions** between slides in the export.
9. **`--json` output** for CI/automation.

## Done (v1 rewrite)

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
