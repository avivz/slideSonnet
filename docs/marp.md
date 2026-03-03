# MARP Markdown Slides

slideSonnet parses [MARP](https://marp.app/) Markdown presentations and generates narrated video from them. This document covers the MARP-specific syntax and features.

## Setup

A MARP file is standard Markdown with YAML front matter containing `marp: true` and slides separated by `---`:

```markdown
---
marp: true
---

# First Slide

Content here.

---

# Second Slide

More content.
```

The first `---` pair is the YAML front matter boundary. Subsequent `---` lines separate slides. Lines inside fenced code blocks (`` ``` `` or `~~~`) are never treated as separators.

## Narration directives

### `<!-- say: text -->`

Narrate the slide with the given text:

```markdown
# Introduction

<!-- say: Welcome to this lecture on graph theory. -->
```

### `<!-- say(params): text -->`

Optional parenthesized parameters control voice and pace:

```markdown
<!-- say(voice=alice): Alice narrates this slide. -->
<!-- say(voice=bob, pace=slow): Bob speaks slowly here. -->
```

Voice names reference presets defined in the playlist YAML `voices:` section.

### Multi-line narration

Say directives can span multiple lines. Whitespace is normalized to single spaces:

```markdown
<!-- say: This is a long narration
     that spans multiple lines
     in the source file. -->
```

### `<!-- nonarration -->` / `<!-- nonarration(duration) -->`

Show the slide with silence (no narration). Without a duration, the slide appears for the configured `video.silence_duration` (default: 3 seconds). With an explicit duration (in seconds), the per-slide value overrides the global config:

```markdown
# Title Card

<!-- nonarration -->

---

# Complex Diagram

<!-- nonarration(10) -->

---

# Quick Transition

<!-- nonarration(1.5) -->
```

> **Tip:** Always specify an explicit duration — e.g. `<!-- nonarration(5) -->` — rather than relying on the global `silence_duration` default. Explicit durations make the pacing of your presentation self-documenting and independent of project-level configuration changes.

### `<!-- skip -->`

Omit the slide from the video entirely:

```markdown
# Draft Notes

<!-- skip -->
```

## Fragment animation

MARP uses `*` (unordered) and `N)` (ordered) as fragment list markers — items that reveal incrementally in HTML presentations. slideSonnet supports this for video: a slide with N fragment items produces **1 + N sub-slides** — a bare state (no bullets visible) followed by progressive reveals.

### Basic example

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

This produces 4 sub-slides in the video:

| Sub-slide | Visible items | Narration |
|---|---|---|
| 1 | *(none — bare state)* | "Let me walk you through some key concepts." |
| 2 | First concept | "Let's start with the first concept." |
| 3 | First concept, Second concept | "Now here's the second concept." |
| 4 | First concept, Second concept, Third concept | "And finally the third." |

Sub-slide 1 is the **bare state** — the slide heading and non-fragment content are visible, but no fragment items have appeared yet. This lets you introduce the slide before the first bullet reveals.

### Positional vs explicit targeting

By default, says are **positional** — the first say targets sub-slide 1 (bare state), the second targets sub-slide 2 (first reveal), and so on:

```markdown
<!-- say: Here are two points. -->
* Point A
<!-- say: First point. -->
* Point B
<!-- say: Both points. -->
```

Sub-slide 1 is bare with "Here are two points." Sub-slide 2 shows Point A with "First point." Sub-slide 3 shows both with "Both points."

If you don't need narration on the bare state, you can leave it unaddressed — any sub-slide without a matching say becomes silent:

```markdown
* Point A
<!-- say: First point. -->
* Point B
<!-- say: Both points. -->
```

Here there are 2 fragments → 3 sub-slides, but only 2 says. Sub-slide 1 (bare) is silent, sub-slide 2 gets "First point.", sub-slide 3 gets "Both points."

You can also **explicitly target** sub-slides using `slide=N` or a bare number:

```markdown
* Point A
* Point B
* Point C
<!-- say(slide=1): Before any bullets appear. -->
<!-- say(slide=4): Now all three points are visible. -->
```

This creates 4 sub-slides (1 bare + 3 reveals). Sub-slides 2 and 3 have no say targeting them, so they become silent (with a warning).

### Syntax

```markdown
<!-- say: text -->                        sub-slide 1 (positional)
<!-- say(2): text -->                     sub-slide 2 (bare number)
<!-- say(slide=2): text -->               sub-slide 2 (explicit key)
<!-- say(2, voice=alice): text -->        sub-slide 2 + voice
<!-- say(slide=3, pace=slow): text -->    sub-slide 3 + pace
```

### Ordered fragments

Ordered fragment lists use `N)` syntax:

```markdown
<!-- say: Two steps to follow. -->
1) First step
<!-- say: Start here. -->
2) Second step
<!-- say: Then do this. -->
```

These produce 3 sub-slides (1 bare + 2 reveals). Rendered items use `1.`, `2.` notation in the video images.

### Multiple fragment lists

A slide can have multiple fragment lists separated by non-fragment content. All fragment items across the slide are numbered sequentially top-to-bottom. Non-fragment content (text, images, regular `-` lists) is always visible.

```markdown
# Two Lists

<!-- say: Here are two groups of items. -->

* A
* B

This text is always visible.

* C
* D

<!-- say: Introducing A. -->
<!-- say: Now A and B. -->
<!-- say: Moving to the second list — here's C. -->
<!-- say: And finally D. -->
```

| Sub-slide | First list | Middle text | Second list |
|---|---|---|---|
| 1 | *(empty)* | always visible | *(empty)* |
| 2 | A | always visible | *(empty)* |
| 3 | A, B | always visible | *(empty)* |
| 4 | A, B | always visible | C |
| 5 | A, B | always visible | C, D |

### Rules

- **Sub-slide count**: a fragment slide with N fragment items produces 1 + N sub-slides (1 bare + N reveals)
- **Bare state**: sub-slide 1 shows all non-fragment content but no fragment items
- **Fragment count**: `*` and `N)` items outside code blocks, numbered top-to-bottom
- **Progressive reveal**: sub-slide k (for k ≥ 2) shows fragment items 1 through k−1
- **Non-fragment content**: always visible on every sub-slide
- **No fragments**: if a multi-say slide has no `*` / `N)` items, each sub-slide gets an identical image (useful for slides where the visual doesn't change but narration is split)
- **Single say**: slides with one or zero says are never expanded (backward compatible)
- **`<!-- skip -->` takes priority**: a skipped slide is never expanded, regardless of say count
- **Multiple says targeting the same sub-slide**: narration text is concatenated
- **Unaddressed sub-slides**: any sub-slide without a matching say becomes silent (with a warning)

## Code blocks

Directives inside fenced code blocks are ignored:

````markdown
# Example

```html
<!-- say: This is example code, not narration. -->
```

<!-- say: Real narration outside the fence. -->
````

Only the second `<!-- say -->` is parsed. The same applies to `<!-- nonarration -->`, `<!-- skip -->`, and fragment markers (`*`, `N)`).

## Image extraction

slideSonnet renders slides to PNG images using [marp-cli](https://github.com/marp-team/marp-cli) and [Playwright](https://playwright.dev/python/) (headless Chromium):

```bash
npm install -g @marp-team/marp-cli
```

Playwright is installed automatically as a dependency. On first use, slideSonnet will auto-install the Chromium browser binary if it's not already present.

The extraction pipeline:

1. **marp-cli** exports the presentation to a single HTML file (`marp --output <file>.html`)
2. **Playwright** opens the HTML in headless Chromium, navigates through each slide and fragment step using keyboard events, and takes a screenshot at each state
3. The temporary HTML file is cleaned up after extraction

Marp's HTML output natively handles fragment reveals via `data-marpit-fragments` attributes, so each fragment step is captured accurately including CSS animations and transitions.
