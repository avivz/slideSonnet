---
paths:
  - "src/**/*.py"
---

# Architecture

slideSonnet v1 is a PDF + narration-sidecar editor. There is **no** source→video
compile pipeline, no doit graph, no parsers.

## Data flow

```
deck.pdf  ──► pdf/reader.read_page_ids  ──► [slide-ids, in page order]
deck.narration ──► narration/format.parse_sidecar ──► [PageNarration blocks]
                         │
              deck.load_deck  ──►  Deck + diagnostics.diagnose (id-only)
                         │
        ┌────────────────┼─────────────────────────────┐
   audio/synth      timing/render                  subtitles
 (cache-aware TTS)  (DeckTimeline:                (SRT/VTT from the
        │            page durations,               same timeline)
  audio/track        cue sheet)
 (per-page audio          │
  + deck track)     render.compose_video ──► video/composer (FFmpeg) ──► deck.mp4
```

## Key modules

- **pdf/reader.py** — `read_page_ids` (PyMuPDF, extracts invisible `SSID:` markers),
  `rasterize` (pdftoppm → page PNGs).
- **narration/model.py** — `Segment` (speech|pause; speech carries per-utterance
  `voice`/`pace`/`direction`), `Transition` (cut|crossfade), `PageNarration`
  (segments + `transition_in`/`transition_out`), `Deck`.
- **narration/format.py** — parse/serialize the indented block sidecar grammar
  (round-trip stable; `utterance:`/`pause:`/`transition-*:` lines);
  `parse_segments`/`serialize_body` (lossy plain-text helper), `pace_to_speed`.
  `FORMAT_VERSION` + the optional `# slidesonnet-format: N` header (a comment, so
  old parsers skip it; a greater N logs an upgrade warning).
- **diagnostics.py** — id reconciliation (auto/missing/orphan/order/unmarked/
  transition-conflict); `boundary_transition` (earlier slide's transition wins).
  Duplicate ids (page *and* sidecar) are auto-disambiguated in `deck.py`, not here.
- **deck.py** — `load_deck`, `save_deck` (skips empty placeholder blocks),
  `dedupe_page_ids`, `dedupe_block_ids` (repeated `@id` → `id-2`, keeps text),
  default sidecar path.
- **timing.py** — `TimingMode` (tts/estimate/fixed), `compute_page_timing` → `PageTiming`.
- **render.py** — `build_timeline` (`DeckTimeline`), `subtitle_entries`,
  `render_audio_track`, `compose_video`.
- **audio/synth.py** — cache-aware per-segment TTS; pace→speed; `page_speech_durations`,
  `cached_durations`.
- **audio/track.py** — `make_silence`, `build_page_audio`, `assemble_track`, `cue_sheet`.
- **subtitles.py** — `format_srt`, `format_vtt`, `split_text`, `SubtitleEntry`.
- **config.py** — optional `slidesonnet.toml`: `Config` (tts/video/voices/pronunciation).
- **cache.py** — `<deck-dir>/.slidesonnet/` layout: `audio/` is content-addressed and
  shared across decks in the dir; `render/<deck-stem>/` is per-deck (render artifacts
  use positional names, so sharing them would interleave two decks' files).
- **hashing.py** — content-addressed audio filenames (`{text_hash}.{backend}.{config_hash}.ext`).
- **tts/** — `BACKENDS` registry (name → extension/paid/factory; the single source
  the CLI choices, config validation, hashing extensions, and clean's paid set
  derive from), `create_tts`, `TTSEngine` base (incl. `list_voices`/`default_voice`),
  Kokoro, ElevenLabs, pronunciation. Adding an engine = one `BackendSpec` + the
  `Backend` Literal in models.py (a test pins them in sync).
- **video/composer.py** — FFmpeg: `compose_segment`, `compose_silent_segment`,
  `concatenate_segments`, `concatenate_audio`, `get_duration`.
- **gui/state.py** — UI-free `EditorState` (nav, edit→sidecar, save, TTS, preview, export).
- **gui/app.py** — NiceGUI view; `build_editor`, `run_editor`. Whole-deck preview plays
  one assembled track and flips the page image on cue-sheet boundaries.
- **api.py** — typed entry points mirroring the CLI: `sty_text`/`write_sty`,
  `init_sidecar`, `check_deck`, `synthesize_deck`, `export`, `write_subs`, `build_preview`.
- **cli.py** — Click commands: `sty`, `init`, `check`, `tts`, `export`, `subs`, `edit`,
  `clean`, `doctor`.
- **doctor.py** / **clean.py** — dependency checks; graduated cache cleanup.

## The `\ssid` macro

`slidesonnet.sty` (also at `src/slidesonnet/templates/slidesonnet.sty`, shipped as
package data; `slidesonnet sty` writes it out). It stamps each emitted page with an
invisible `SSID:<id>` marker via PDF text rendering mode 3 (`\pdfliteral{3 Tr}`),
keyed by absolute page number so overlay steps each get their own id. The repo-root
copy and the packaged copy must stay identical (guarded by `test_api.py`).

## The timeline is the single source of truth

`DeckTimeline` (per-page `PageTiming` with lead/tail) drives the export, the preview
cue sheet, and the subtitles — so what you preview is what you export. tts mode uses
real audio durations; estimate/fixed use the model.
