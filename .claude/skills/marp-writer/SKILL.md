---
name: marp-writer
description: Write MARP Markdown presentations for slideSonnet narrated video lectures. Use when the user asks to "write a lecture", "create slides", "write a presentation", "make a marp file", "add a marp module", or wants help authoring .md slide content for slideSonnet.
argument-hint: [topic or instructions]
---

# MARP Presentation Writer for slideSonnet

Write MARP Markdown slides that slideSonnet compiles into narrated MP4 videos.

## MARP Essentials

MARP (Markdown Presentation Ecosystem) turns Markdown files into slide decks. Key structure:

```markdown
---
marp: true
math: katex
style: |
  section { font-family: 'Georgia', serif; }
  h1 { color: #1a1a2e; }
---

# First Slide

Content here.

---

# Second Slide

More content.
```

- **`marp: true`** in YAML front matter is required
- **`---`** on its own line separates slides (the first `---` pair is YAML front matter)
- **`math: katex`** enables math: inline `$x^2$`, display `$$\sum_{n=1}^{\infty}$$`
- Standard Markdown: headings, bullets (`-`), bold/italic, code blocks, images
- **`![alt](path)`** for images
- **`style:`** in front matter for custom CSS (targets `section`, `h1`, etc.)
- **`<!-- _class: name -->`** for per-slide CSS class
- **`theme:`**, **`paginate:`**, **`footer:`**, **`header:`** for deck-wide settings

## slideSonnet Narration Commands

### `<!-- say: text -->` — narrate the slide

```markdown
# Topic

Slide content here.

<!-- say: Narration text spoken during this slide. -->
```

- Place the comment anywhere on the slide (outside code fences)
- Multi-line is fine — whitespace is normalized to single spaces:
  ```markdown
  <!-- say: This is a long narration
       that spans multiple lines
       in the source file. -->
  ```
- Multiple `<!-- say: -->` on the same slide concatenate (or target sub-slides — see fragments below)
- Directives inside fenced code blocks (`` ``` ``) are ignored

### `<!-- say(params): text -->` — voice/pace override and sub-slide targeting

```markdown
<!-- say(voice=narrator): Different voice for this slide. -->
<!-- say(voice=bob, pace=slow): Bob speaks slowly here. -->
```

Voice names reference presets defined in the playlist YAML `voices:` section. On conflict, last say wins.

### `<!-- nonarration -->` / `<!-- nonarration(duration) -->` — silent slide

Show the slide for `video.silence_duration` seconds (default 3s) with no narration. With an explicit duration (in seconds), the per-slide value overrides the global config. Use for title cards, visual pauses, or end slides.

### `<!-- skip -->` — exclude from video

Omit the slide from the video entirely. Takes priority over all other directives.

### Fragment animation (progressive bullet reveal)

Use `*` for unordered or `N)` for ordered fragment items. Each fragment creates a sub-slide with its own narration.

```markdown
# Key Concepts

<!-- say: Let me walk you through some key concepts. -->
* First concept
<!-- say: Let's start with the first concept. -->
* Second concept
<!-- say: Now here's the second concept. -->
* Third concept
<!-- say: And finally the third. -->
```

This produces 4 sub-slides (1 bare state + 3 reveals):

| Sub-slide | Visible | Narration |
|-----------|---------|-----------|
| 1 | *(bare — no bullets)* | "Let me walk you through..." |
| 2 | First concept | "Let's start with..." |
| 3 | First, Second | "Now here's the second..." |
| 4 | All three | "And finally the third." |

Fragment rules:
- `*` bullets and `N)` ordered items are fragment markers — they reveal progressively
- Regular `-` bullets are **not** fragments — they're always visible
- Sub-slide count = 1 + number of fragment items
- Sub-slide 1 is the bare state (no fragments visible)
- Narration targeting is positional by default (first say → sub-slide 1, second → sub-slide 2, etc.)
- Explicit targeting: `<!-- say(2): text -->` or `<!-- say(slide=2): text -->`
- Sub-slides with no say become silent (warning emitted)
- Multiple says targeting the same sub-slide concatenate

### Explicit sub-slide targeting

```markdown
<!-- say: text -->                        sub-slide 1 (positional)
<!-- say(2): text -->                     sub-slide 2 (bare number)
<!-- say(slide=2): text -->               sub-slide 2 (explicit key)
<!-- say(2, voice=alice): text -->        sub-slide 2 + voice
<!-- say(slide=3, pace=slow): text -->    sub-slide 3 + pace
```

## The Playlist File (Main Lecture File)

The playlist is a YAML file that defines the lecture structure. It is the entry point for `slidesonnet build`.

### Format

```yaml
title: Lecture Title
tts:
  backend: piper                     # or: elevenlabs
  piper:
    model: en_US-lessac-medium
voices:
  default:
    piper: en_US-lessac-medium
    elevenlabs: nPczCjzI2devNBz1zQrb
  narrator:
    piper: en_US-amy-medium
    elevenlabs: 21m00Tcm4TlvDq8ikWAM
pronunciation:
  shared:
    - pronunciation/general.md
  # piper:
  #   - pronunciation/piper-hacks.md
  # elevenlabs:
  #   - pronunciation/elevenlabs-hacks.md
video:
  resolution: 1920x1080
  fps: 24
  crf: 23
  pad_seconds: 1.5
  silence_duration: 3.0
  crossfade: 0.5
modules:
  - chapter1.md
  - chapter2.md
  - video/interlude.mp4
  - chapter3.md
```

### Key rules

- **Modules** are listed under the `modules:` key as plain strings
- **File extension determines type**: `.md` → MARP, `.tex` → Beamer, `.mp4`/`.mkv`/`.webm`/`.mov` → video passthrough
- Paths are relative to the playlist file
- Lines starting with `//` are comments (filtered before YAML parsing)
- The `voices:` section maps voice names to per-backend voice IDs — these are the names used in `<!-- say(voice=NAME): -->`
- The `pronunciation:` section points to markdown files with `**word**: replacement` entries for TTS substitution. Can be a flat list (treated as shared) or a dict with `shared`, `piper`, `elevenlabs` keys for per-backend dictionaries
- Build command: `slidesonnet build` (or `slidesonnet build --tts piper`)

## Writing Guidelines

When writing MARP slides for slideSonnet:

1. **Every slide needs an annotation** — use `<!-- say: -->`, `<!-- nonarration -->`, or `<!-- skip -->`. Unannotated slides produce warnings.
2. **Write narration as natural speech** — avoid reading slide text verbatim. Explain, elaborate, connect ideas. The narration should complement the visual content, not duplicate it.
3. **Use `<!-- nonarration -->` for title/end slides** — not every slide needs speech.
4. **Keep narration per slide to 2-4 sentences** — roughly 10-30 seconds of audio. Longer narrations work but consider splitting across slides.
5. **Use fragment animation for progressive reveal** — `*` bullets with per-fragment narration are more engaging than dumping all points at once.
6. **Keep slides visually clean** — one idea per slide. Use headings, short bullets, and display math. Avoid walls of text.
7. **Math goes in KaTeX** — enable with `math: katex` in front matter. Use `$...$` inline and `$$...$$` for display.
8. **Narration outside code fences** — directives inside `` ``` `` blocks are ignored.

## Typical File Structure

```
lecture/
├── slidesonnet.yaml        # Playlist (main file)
├── chapter1.md             # MARP module
├── chapter2.md             # MARP module
├── images/                 # Shared images
│   └── diagram.png
├── pronunciation/          # TTS pronunciation dictionaries
│   └── general.md
└── cache/                  # Build artifacts (gitignored)
    └── ...
```

## Example: Complete MARP Module

```markdown
---
marp: true
math: katex
style: |
  section { font-family: 'Georgia', serif; }
  h1 { color: #1a1a2e; }
---

# Graph Theory Basics

### An introduction to vertices and edges

<!-- nonarration -->

---

# What is a Graph?

A graph $G = (V, E)$ consists of:

<!-- say: A graph is a mathematical structure with two components. -->
* A set of **vertices** $V$
<!-- say: First, a set of vertices, which represent objects. -->
* A set of **edges** $E \subseteq V \times V$
<!-- say: And second, a set of edges, which represent
     connections between those objects. -->

---

# Degree of a Vertex

The degree of vertex $v$ is the number of edges incident to $v$:

$$\deg(v) = |\{e \in E : v \in e\}|$$

<!-- say: The degree of a vertex counts how many edges touch it. -->

---

# Handshaking Lemma

$$\sum_{v \in V} \deg(v) = 2|E|$$

<!-- say: The handshaking lemma tells us that the sum of all
     vertex degrees equals twice the number of edges. This is
     because each edge contributes exactly one to the degree
     of each of its two endpoints. -->

---

# Thank You

<!-- nonarration -->
```

$ARGUMENTS
