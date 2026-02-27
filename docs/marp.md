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

Voice names reference presets defined in the playlist YAML front matter.

### Multi-line narration

Say directives can span multiple lines. Whitespace is normalized to single spaces:

```markdown
<!-- say: This is a long narration
     that spans multiple lines
     in the source file. -->
```

### `<!-- silent -->`

Show the slide with silence (no narration):

```markdown
# Title Card

<!-- silent -->
```

### `<!-- skip -->`

Omit the slide from the video entirely:

```markdown
# Draft Notes

<!-- skip -->
```

## Fragment animation

MARP uses `*` (unordered) and `N)` (ordered) as fragment list markers — items that reveal incrementally in HTML presentations. slideSonnet supports this for video: a slide with **multiple `<!-- say -->` directives** is expanded into sub-slides, each showing one more fragment item than the last.

### Basic example

```markdown
# Key Concepts

* First concept
<!-- say: Let's start with the first concept. -->
* Second concept
<!-- say: Now here's the second concept. -->
* Third concept
<!-- say: And finally the third. -->
```

This produces 3 sub-slides in the video:

| Sub-slide | Visible items | Narration |
|---|---|---|
| 1 | First concept | "Let's start with the first concept." |
| 2 | First concept, Second concept | "Now here's the second concept." |
| 3 | First concept, Second concept, Third concept | "And finally the third." |

Fragment markers (`*` / `N)`) are converted to regular markers (`-` / `N.`) in the rendered images.

### Positional vs explicit targeting

By default, says are **positional** — the first say targets sub-slide 1, the second targets sub-slide 2, and so on:

```markdown
* Point A
* Point B
<!-- say: First point. -->
<!-- say: Both points. -->
```

Sub-slide 1 shows only Point A with "First point." Sub-slide 2 shows both points with "Both points."

You can also **explicitly target** sub-slides using `slide=N` or a bare number:

```markdown
* Point A
* Point B
* Point C
<!-- say(slide=1): Here's point A. -->
<!-- say(slide=3): Now all three points are visible. -->
```

This creates 3 sub-slides. Sub-slide 2 has no say targeting it, so it becomes silent (with a warning).

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
1) First step
<!-- say: Start here. -->
2) Second step
<!-- say: Then do this. -->
```

These are rendered as `1.`, `2.` in the video images.

### Multiple fragment lists

A slide can have multiple fragment lists separated by non-fragment content. All fragment items across the slide are numbered sequentially top-to-bottom. Non-fragment content (text, images, regular `-` lists) is always visible.

```markdown
# Two Lists

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
| 1 | A | always visible | *(empty)* |
| 2 | A, B | always visible | *(empty)* |
| 3 | A, B | always visible | C |
| 4 | A, B | always visible | C, D |

### Rules

- **Trigger**: a slide with multiple `<!-- say -->` directives expands into sub-slides
- **Fragment count**: `*` and `N)` items outside code blocks, numbered top-to-bottom
- **Progressive reveal**: sub-slide k shows fragment items 1 through min(k, total fragments)
- **Hidden items**: fragment items not yet revealed are removed entirely from the sub-slide
- **Non-fragment content**: always visible on every sub-slide
- **No fragments**: if a multi-say slide has no `*` / `N)` items, each sub-slide gets an identical image (useful for slides where the visual doesn't change but narration is split)
- **Single say**: slides with one or zero says are never expanded (backward compatible)
- **`<!-- skip -->` takes priority**: a skipped slide is never expanded, regardless of say count
- **Multiple says targeting the same sub-slide**: narration text is concatenated

## Code blocks

Directives inside fenced code blocks are ignored:

````markdown
# Example

```html
<!-- say: This is example code, not narration. -->
```

<!-- say: Real narration outside the fence. -->
````

Only the second `<!-- say -->` is parsed. The same applies to `<!-- silent -->`, `<!-- skip -->`, and fragment markers (`*`, `N)`).

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
