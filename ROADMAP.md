# Roadmap

Current version: 1.0.0a0 (alpha) — the PDF + narration-sidecar editor rewrite.

See `dev/DESIGN-narration-editor.md` for the design, `CHANGELOG.md` for shipped
changes.

## Now — finish the v1 rewrite

- [x] M0 backend spine: `\ssid` macro, PDF id extraction, sidecar parse/serialize,
  id-only diagnostics, timing model, `init`/`check`/`doctor`/`sty`.
- [x] M1 headless media: cache-aware TTS, audio track + cue sheet, video export
  (tts/estimate/fixed, `--silent`), SRT/VTT subtitles, typed `slidesonnet.api`.
- [x] M2/M3 NiceGUI editor: nav, edit, per-slide TTS, whole-deck preview, diagnostics.
- [x] Demos converted to the new format (basel-problem + showcase).
- [x] Docs (README, CHANGELOG), Makefile, `mypy --strict` + ruff + tests green.
- [ ] **ElevenLabs re-render of the demos** — regenerate `basel-problem` and
  `showcase` with the cloud voices (`slidesonnet.toml` already maps them) and
  upload the HQ MP4s to the GitHub Release. *Deferred per build decision (no paid
  TTS during the build).*
- [ ] Update CI matrix / `publish.yml` smoke test for the new dependency set
  (PyMuPDF, NiceGUI) and the `1.0.0` tag.
- [ ] Refresh README example video links once the HQ renders are uploaded.

## Next — before 1.0 final

1. **`init` default sidecar UX** — richer scaffold comments (per-page titles
   pulled from the PDF outline, if present).
2. **Editor polish** — keyboard shortcuts (←/→ nav, ⌘S), single-slide preview
   button, an engine/voice picker, export dialog with timing/subtitle options.
3. **`clean --dry-run`** — preview what would be removed.
4. **`check --fix`** — offer to re-sort the sidecar to PDF order and scaffold
   missing blocks in one step.
5. **Watch mode** — re-preview on sidecar save in the editor.
6. **Per-segment voice** — allow a voice switch mid-block (today voice is
   per-slide; multi-voice needs splitting into separate `\ssid` steps).

## Later — backlog

1. **id-injection adapters** (designed, deferred — see DESIGN §11): Marp theme
   span, PPTX `python-pptx` textbox, Google Slides API. Same marker contract.
2. **Layered reconciliation** — optional text-fingerprint fallback when ids are
   missing, for non-Beamer sources.
3. **Hebrew / RTL TTS** — research in `dev/hebrew-tts-research.md`.
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

- [x] Branch `v2-narration-editor`; old source→video pipeline removed.
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
