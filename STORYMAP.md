# Story Map — slideSonnet v2 (PDF + narration-sidecar editor)

The user's journey runs left to right; under each step, stories are stacked by importance.
**A release is a horizontal slice** — a thin, complete walk across all columns — never one
column polished in isolation.

Primary user: a lecturer turning a Beamer deck into a narrated lecture video, alone, on
their own machine. The same person returns later to revise the deck (the *maintain* column),
and occasionally wants the pipeline scripted (CI/automation stories live at the far right).

Status: ✅ shipped (in 1.0.0a0) · 🔜 Next tier (before 1.0 final) · 🧊 Later/backlog.
Tiers mirror `ROADMAP.md`; this map shows *where in the journey* each item sits, the
roadmap shows *when*. Update both when promoting an item.

## The map

```
get set up → mark the deck → scaffold → write & hear → check → export → maintain
─────────    ────────────    ────────   ────────────   ─────   ──────   ────────
✅ install   ✅ \ssid + sty   ✅ init     ✅ edit GUI     ✅ check ✅ MP4    ✅ merge loop
✅ doctor    ✅ overlays      ✅ --merge  ✅ slide TTS    🔜 --fix ✅ SRT/VTT✅ clean
✅ toml      🧊 Marp/PPTX     🔜 outline  ✅ deck preview          ✅ cache  🔜 --dry-run
             🧊 fingerprint   titles     ✅ live reload           🔜 dialog 🧊 playlists
                                        🔜 shortcuts             🧊 fades  🧊 --json
                                        🔜 watch mode            🧊 engines
                                        🔜 multi-voice
```

The ✅ row is the shipped walking skeleton: a new user can already walk the whole journey
end-to-end. Everything below is depth, not breadth.

## Column detail

### 1. Get set up

- ✅ I install one package and `slidesonnet doctor` tells me which external tools
  (ffmpeg, pdftoppm, latexmk) are missing and how to get them.
- ✅ I set my engine and voices once per deck in `slidesonnet.toml` and stop thinking
  about flags.

### 2. Mark the deck

- ✅ `slidesonnet sty` hands me the `\ssid` macro; the ids are invisible in the PDF and
  survive overlays, so my deck looks untouched.
- 🧊 My slides aren't Beamer — Marp / PPTX / Google Slides adapters stamp the same markers.
- 🧊 My PDF has no ids at all — text-fingerprint fallback reconciles anyway.

> Friction note: this is the steepest step for a new user — they must edit LaTeX source and
> recompile before slideSonnet does anything visible. Onboarding docs and the first
> usability sessions should aim here.

### 3. Scaffold the narration

- ✅ `init` writes a sidecar with one block per slide and refuses to clobber my words.
- ✅ After recompiling with new slides, `init --merge` adds the missing blocks and touches
  nothing else.
- 🔜 Scaffold comments show each page's title (from the PDF outline) so I know which block
  is which without opening the PDF.

### 4. Write & hear it (the core loop)

- ✅ I write narration in any text editor — the sidecar is plain text and git-diffable —
  or in the GUI editor with the slide beside the words.
- ✅ I hear a single slide's narration instantly (per-slide TTS, cached).
- ✅ I preview the whole deck with realistic silences before committing to an export.
- ✅ The editor notices when the PDF or sidecar changes on disk and reloads.
- ✅ I control delivery inline: `:voice`, `:pace`, `[pause N]`.
- 🔜 Keyboard-first editing: ←/→ slide nav, ⌘S, a single-slide preview button, an
  engine/voice picker.
- 🔜 Watch mode: saving the sidecar re-previews automatically.
- 🧊 A voice switch mid-slide (today voice is per-slide).

### 5. Check

- ✅ `check` reconciles sidecar ids against PDF pages: missing narration, orphaned blocks,
  duplicates, out-of-order — warnings don't fail, real breaks do.
- 🔜 `check --fix` re-sorts the sidecar to PDF order and scaffolds missing blocks in one step.

### 6. Export

- ✅ One command renders the MP4; timing comes from real TTS, a wpm estimate, or fixed
  seconds; `--silent` renders without audio.
- ✅ SRT/WebVTT subtitles, per segment or per slide.
- ✅ Synthesis is content-addressed and cached — re-exports don't re-pay (money or time)
  for unchanged lines.
- 🔜 An export dialog in the editor with timing/subtitle options (today: CLI only).
- 🧊 Crossfade/transitions between slides.
- 🧊 More voices: Cartesia/Azure/Google engines; Qwen3 own-voice cloning; Inworld managed.

### 7. Maintain & automate

- ✅ The revision loop: recompile → `check` flags the drift → `init --merge` heals it →
  re-export only re-synthesizes what changed.
- ✅ `clean` frees disk but keeps paid API audio by default.
- 🔜 `clean --dry-run` shows what would go before it goes.
- 🧊 Multi-deck playlists — several PDFs concatenated into one video.
- 🧊 `--json` output so CI can run the pipeline and parse results.

## Keeping this alive

- When `/pm` promotes an item, place it in a column here (with its story phrasing) in the
  same change that adds it to `ROADMAP.md`.
- Before cutting a release, read the map row-wise: is the slice complete across all columns?
- Usability findings (where real users stall in the walk) land in `dev/INBOX.md` first,
  then get pinned to a column here during triage.
