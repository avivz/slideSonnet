# Frontend design brief

- Date: 2026-09-28
- Applies to: the Vue screens of the migration (`docs/frontend-migration.md`,
  *Layout redesign*). Each screen is built to an approved layout; this brief is
  the shared ground they start from.
- Reference screenshots: `dev/frontend-baseline/` (Phase 0, untracked).

## Goals

1. **The slide and its words come first.** The current slide image and the
   utterance text are the two things the author looks at; everything else is a
   tool around them and gets less visual weight.
2. **Controls live where the work is.** Playback sits next to the slide it
   plays, not under a scrolling list. Deck-wide actions (engine, generate,
   export) live in one predictable place instead of the bottom of a mostly
   empty panel.
3. **State is readable at a glance.** Slide status (ready / warning / error /
   empty / audio missing) is legible at filmstrip size, in words or shapes, not
   only as tiny colored dots.
4. **Narrow windows degrade on purpose.** Panes collapse into overlays with a
   visible way back, footers never wrap into several lines, and every control
   keeps a home.
5. **Keyboard first, as today.** ←/→ and ↑/↓ step slides, Ctrl+K switches
   decks, Alt+←/→ steps decks, Ctrl+S saves; nothing new needs a mouse.

Behavior parity is the rule (`docs/frontend-parity.md`); the look and the
arrangement may change. Dropping a control needs the maintainer's approval.

## Tokens

One small set, defined once in `frontend/src/styles/tokens.css` and derived
from today's `gui/static/editor.css` so the product stays recognizably itself.

| Group | Tokens |
|---|---|
| Surfaces | `--bg #0e1116`, `--surface #151a22`, `--raised #1e2531`, `--line #2b3442` |
| Text | `--text #e8ecf3`, `--dim #8a94a6` |
| Accent | `--accent #5db3f0`, `--accent-deep #2f7fc4` |
| Status | `--ok #7ee08a`, `--warn #ffc857`, `--err #ff6b6b` (each with a 12 % tint for fills) |
| Type | Plex Sans for prose, Plex Mono for ids/paths/numbers, Bricolage Grotesque for the wordmark only; sizes 11 / 12 / 13 / 15 / 19 px |
| Space | 4 / 8 / 12 / 16 / 24 / 32 px |
| Radius | 6 (fields) / 10 (cards) / 14 (dialogs) / pill |
| Motion | 120 ms for hover/focus, 200 ms for panes; none when `prefers-reduced-motion` |

Fonts are bundled with the build (`@fontsource/*`); the page makes no CDN
requests at runtime.

Dark is the default and only theme for now; the tokens are the seam a light
theme would use later.

## Shared components

Built once in `frontend/src/components/` and reused by every screen:
buttons (primary, quiet, icon), text field, select, status chip, progress
bar, card, dialog (focus-trapped, Esc closes, focus restored), pane
(resizable, collapsible), toast/flash line, empty state, notice.

No component framework: plain SFCs over the tokens, semantic HTML, visible
focus rings, accessible names on icon buttons.

## Screen: library (`/`) — Phase 2

Problems in the current screen:

- Decks are a plain list; the only status is a one-line text summary.
- The top-level folder is repeated as a section heading over a single deck.
- PDFs inside build folders (`*/cache/slides/*.pdf`) appear as phantom
  "no narration yet" decks.
- The scan root is shown as an absolute path chip that truncates.

Layout (built in Phase 2):

- **Header:** wordmark · scan-root folder name · a search field (focus with
  `/` or Ctrl+K; Enter opens the highlighted deck; ↑/↓ move the highlight) ·
  rescan · deck count.
- **Body:** a plain list of decks, one row each: the deck name, the part of
  its path the heading doesn't already say, and its size (*N slides*). The
  library is for picking a deck, so it shows no progress or status (a
  progress bar and a *complete* chip were tried and read as unexplained).
  Rows are links: the whole row opens the deck, and middle-click opens it in
  a new tab.
- **Sections:** folders that hold two or more decks get a heading with a
  count; single-deck folders are gathered into one untitled group at the top
  instead of each getting a heading of its own.
- **Without narration:** PDFs with no sidecar are listed last, collapsed by
  default, with the one command that starts a narration file for them.
  PDFs inside build-output folders are not listed.
- **Empty and truncated states** keep their current wording.

## Later screens

- **Editor (Phase 4):** 2–3 clickable directions before the port. Starting
  points from the Phase 0 observations: transport attached to the stage;
  deck-wide actions in the header or a compact toolbar; transition-in and
  edge silences as a compact strip above and below the utterance list, with
  utterance text visually dominant; status on thumbnails as a labelled badge.
- **Review (Phase 5):** mockup before the port.
