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
  `voice`/`pace`/`direction`), `Transition` (`kind` + `seconds`; `kind` is a
  gallery name), `PageNarration` (segments + `transition_in`/`transition_out`), `Deck`.
- **narration/transitions.py** — the curated xfade gallery: `FAMILIES` (Cut, Fade,
  Fade through black/white, Dissolve, Wipe/Slide/Cover/Reveal × Left/Right/Up/Down,
  Circle Open/Close), `TRANSITION_NAMES` (every valid stored name: `cut` is the
  default, `crossfade` a legacy alias for `fade`), `xfade_name` (stored name →
  FFmpeg xfade `transition=`; `None` for a cut).
- **narration/format.py** — parse/serialize the indented block sidecar grammar
  (round-trip stable; `utterance:`/`pause:`/`transition-*:` lines);
  `serialize_body` (lossy plain-text view, used by review), `pace_to_speed`.
  `FORMAT_VERSION` + the optional `# slidesonnet-format: N` header (a comment, so
  old parsers skip it; a greater N logs an upgrade warning).
- **narration/spoken.py** — inline pronunciation fixes `[display](spoken)` inside
  `text:`: `display_text` (captions/editor), `engine_text` (per engine: IPA to
  Inworld only, respellings to all; the dictionary applies outside fixes),
  `round_brackets`/`has_stray_brackets`. `Config.speech_text(seg, backend)` is the
  exact text an engine is sent and hashed (Inworld: + `tts.inworld.request_text`,
  brackets → parens on tts-2, `direct:` note when `send_direction`).
- **diagnostics.py** — id reconciliation (auto/missing/orphan/order/unmarked/
  transition-conflict); `boundary_transition` (earlier slide's transition wins).
  Duplicate ids (page *and* sidecar) are auto-disambiguated in `deck.py`, not here.
- **deck.py** — `load_deck`, `save_deck` (skips empty placeholder blocks),
  `dedupe_page_ids`, `dedupe_block_ids` (repeated `@id` → `id-2`, keeps text),
  default sidecar path.
- **timing.py** — `TimingMode` (tts/estimate/fixed), `compute_page_timing` → `PageTiming`.
- **render.py** — `build_timeline` (`DeckTimeline`), `subtitle_entries`,
  `render_audio_track`, `compose_video` (transitions are visual overlays centred on
  the page boundary — `transition_morph_seconds`, `frame_plan` — so the audio
  timeline and total duration don't change). Each still/morph clip is cached
  under `render/<deck>/clips/` by `clip_key` (image hashes, frames, picture
  settings, xfade, ffmpeg build + CPU count), so a re-export encodes only changed
  clips; the track's AAC (`track_aac`, kept too) is encoded alongside and copied
  in. `prune_render_scratch` drops the PCM page/track WAVs after export.
- **audio/synth.py** — cache-aware per-segment TTS; pace→speed; `page_speech_durations`,
  `cached_durations`. **audio/durations.py** — `ClipDurations`, the saved clip
  lengths in `<pool>/durations.json` (a cache; stale entries are re-measured).
- **audio/track.py** — `make_silence`, `build_page_audio`, `assemble_track`, `cue_sheet`.
- **subtitles.py** — `format_srt`, `format_vtt`, `split_text`, `SubtitleEntry`.
- **config.py** — optional `slidesonnet.toml`: `Config` (tts/video/voices/logging/
  pronunciation/`[cache] audio_dir`/`[video] output_dir` + `subtitles_dir`).
- **cache.py** — `<deck-dir>/.slidesonnet/` layout: `render/<deck-stem>/` is per-deck
  (positional names, so sharing would interleave two decks' files). Audio is
  content-addressed and lives in a *speech-clip pool*, resolved by
  `resolve_audio_dir`: `--audio-dir` > `$SLIDESONNET_AUDIO_DIR` > `[cache] audio_dir`
  in `slidesonnet.toml` > the default `<deck-dir>/.slidesonnet/audio/` (shared by
  the decks in that dir). Pointing worktrees/decks at one pool shares paid clips.
- **pool.py** — pool maintenance behind `slidesonnet pool`: `pool_status`,
  mark-and-sweep `plan_prune`/`apply_prune` (live set = every deck's sidecar;
  paid/slow-backend orphans go to `<pool>/trash/`, `empty_trash` deletes), and an
  advisory `index.jsonl` (snippets for dry runs, never used to decide deletion).
- **hashing.py** — content-addressed audio filenames (`{text_hash}.{backend}.{config_hash}.ext`).
- **tts/** — `BACKENDS` registry (name → extension/paid/factory; the single source
  the CLI choices, config validation, hashing extensions, and clean's paid set
  derive from), `create_tts`, `TTSEngine` base (incl. `list_voices`/`default_voice`),
  Kokoro, Inworld, Qwen3, pronunciation. Adding an engine = one `BackendSpec` + the
  `Backend` Literal in models.py (a test pins them in sync).
- **video/composer.py** — FFmpeg: `compose_silent_segment`, `compose_transition_clip`
  (one xfade clip per animated boundary), `concatenate_segments`, `encode_aac` +
  `mux_copy`, `concatenate_audio`, `get_duration`, `encoder_identity`; for the
  quick export (`--fast`, `render.fast_video`/`_compose_fast`) `compose_slideshow`
  (one VFR pass, a few long frames per still).
- **proc.py** / **cancellation.py** — `run_tool`/`run_tool_with_progress` (uniform
  errors, timeout, kill on cancel); the cooperative cancel token (a ContextVar).
- **atomic.py** (`atomic_write_text`), **progress.py** (`RunProgress`, the stable
  `[mm:ss NN%]` console lines), **logging_setup.py**, **env.py** (`getenv`: per-deck `.env`
  reads that never touch `os.environ`),
  **models.py** (`VoiceConfig`/`TTSConfig`/`VideoConfig`/…), **exceptions.py**.
- **review/** — the agent review loop (spec: `dev/DESIGN-review.md`).
  `versions.py` captures a `DeckVersion` (per slide id: pixel hash at 150 dpi,
  page text, narration block); `diff.py` compares two by id (new/deleted/edited/
  moved via LCS); `base.py` stores the base under `.slidesonnet/review/<stem>/`
  (advances only on Clear; refuses final builds); `log.py` is the append-only
  `<deck>.review` (format, flock-locked appends, replay into `Conversation`s;
  one with no slides is deck-wide; the header keeps the id high-water mark and
  the Send count, and Clear scrubs cleared conversations, so a finished review
  is header-only); `ops.py` is the API (comment/reply/accept/
  reopen/send/clear/status/wait, automatic filing, author-edit notes); `cli.py`
  is the `slidesonnet review` group. slideSonnet never edits `.tex`/`.narration`
  during review.
- **server/** — the editor's FastAPI backend: `context` (registry, events, jobs,
  session token; Host/same-origin checks), `revisions` (content hashes), `decks`
  (`DeckService`: per-deck lock, revision-checked atomic writes, debounced orphan
  sweep), `editing` (edits by explicit slide id), `jobs`/`events` (backend jobs,
  SSE), `previews` (immutable preview tracks + manifest), `media`, `snapshots`,
  `schemas` (Pydantic DTOs → OpenAPI → `frontend/src/api/schema.d.ts`), `routes`
  (`/api/v1`), `frontend` (serves the built Vue app from `server/static/`).
  `app.create_app` builds the FastAPI app; `run` serves it on Uvicorn (browser/WSL/
  app-window opening via `launch`, `--dev` reload). `library` (deck discovery +
  `DeckRegistry`: `deck_token` = sha1 of the resolved path, capped downward scan,
  natural sort, neighbours — only registered decks resolve), `queue` (per-clip
  generation queue: dedup, nearest-first priority, preemption), `generation` (one
  queue per deck × engine), `review` / `review_model` (review read model + author
  commands over `review/ops`), `engines` (one synthesis at a time per engine;
  render lock before engine lock), `voicing` (voiced spans in a preview track),
  `openapi` (writes the schema for `make api-types`).
- **frontend/** — the Vue 3 + TypeScript app (Vite, Pinia, Vitest); builds into
  `src/slidesonnet/server/static/`: the library (`/`), the deck editor (`/d/{token}`,
  drafts + autosave + conflicts in `stores/editor.ts`), review, and the browser-owned
  preview player (`features/playback/`).
- **api.py** — typed entry points mirroring the CLI: `sty_text`/`write_sty`,
  `init_sidecar`, `check_deck`, `synthesize_deck`, `export`, `write_subs`, `build_preview`.
  `export_paths` is the one place an export's video/subtitle paths are decided
  (CLI `export --where`, and the editor's export job, which passes no `-o`).
- **cli.py** — Click commands: `sty`, `init`, `check`, `tts`, `export`, `subs`, `edit`,
  `clean`, `pool` (`status`/`migrate`/`prune`), `review` (from `review/cli.py`),
  `doctor`; global `--audio-dir` picks the pool.
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
