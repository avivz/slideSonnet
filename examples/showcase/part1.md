---
marp: true
math: katex
---

# slideSonnet

Compile slide decks into narrated videos

<!-- say: Welcome to slideSonnet. This tool compiles slide presentations into narrated videos, entirely from text source files. -->

---

# The Problem

<!-- say: Let's look at some common problems with recording narrated lectures. -->
* Recording narrated lectures is tedious
<!-- say: First, recording is tedious. You need a quiet room, a microphone, and the patience to talk through every single slide. -->
* A single edit means re-recording the whole thing
<!-- say: And when you change even one slide, you often have to re-record the entire section to keep everything in sync. -->
* Keeping slides and audio in sync is error-prone
<!-- say: Over time, keeping slides and audio aligned becomes increasingly error-prone, especially as presentations evolve. -->
* **What if narration was just part of the source?**
<!-- say: But what if the narration was simply part of the slide source, so it could be regenerated automatically? That is exactly what slideSonnet does. -->

---

# How slideSonnet Works

<!-- say: Here's how slideSonnet works, in three simple steps. -->
1) Write slides in **Markdown** (MARP) or **LaTeX** (Beamer)
<!-- say: First, you write your slides in Markdown using MARP, or in LaTeX using Beamer. Both formats are fully supported. -->
2) Add narration annotations to each slide
<!-- say: Then you add narration annotations directly in the slide source. These are simple comments containing the text you want spoken aloud. -->
3) Run `slidesonnet build` to generate a video
<!-- say: Finally, you run slidesonnet build. slideSonnet synthesizes speech, composites each slide with its audio, and assembles the final MP4. -->

---

# What Is MARP?

**MARP** = Markdown Presentation Ecosystem

- Slides are separated by `---`
- Rendered to images by `marp-cli`
- Standard Markdown: headings, bullets, code, images, math

```markdown
# First Slide
Content here.
---
# Second Slide
More content.
```

<!-- say: MARP stands for Markdown Presentation Ecosystem. Slides are written in standard Markdown and separated by triple dashes. MARP renders them to images using marp-cli. -->

---

# The Playlist File

A playlist ties modules together with shared config:

```yaml
---
tts:
  backend: piper
voices:
  default: en_US-lessac-medium
  narrator: en_US-amy-medium
video:
  resolution: 1920x1080
---
1. [Introduction](part1.md)
2. [Deep Dive](part2.tex)
3. [Transition](clip.mp4)
```

<!-- say: The playlist file is the entry point for a build. It contains YAML front matter with TTS, voice, pronunciation, and video settings. Below that, a numbered list references each module. Modules can be MARP markdown, Beamer LaTeX, or MP4 video files. -->

---

# Basic Narration

Add narration to any MARP slide with a say comment:

```markdown
# My Slide

Slide content here.

<!-- say: This text will be spoken aloud. -->
```

The text inside the comment is sent to the TTS engine and paired with the slide image.

<!-- say: To narrate a MARP slide, add an HTML comment that starts with say colon. The text inside is synthesized into speech and paired with the slide image. -->

---

# Voice and Pace

Override the voice or pace on any slide:

```markdown
<!-- say(voice=narrator): Spoken with the narrator voice. -->

<!-- say(voice=expert, pace=slow): Spoken slowly
with the expert voice. -->
```

Voices are defined in the playlist. Pace adjusts speech speed.

<!-- say(voice=narrator): This slide is narrated with the narrator voice to demonstrate voice overrides. You can also set the pace to slow or fast for individual slides. -->

---

# Silent and Skip

Two special annotations control slide behavior:

```markdown
<!-- silent -->
```
A silent slide appears in the video with a configurable pause but no speech.

```markdown
<!-- skip -->
```
A skipped slide is excluded from the video entirely. Useful for backup or draft slides.

<!-- say: There are two more annotations. Silent produces a slide with a pause but no speech. Skip excludes the slide from the video entirely, which is useful for backup or work-in-progress slides. -->

---

# Fragment Animation

Bullet points can reveal incrementally, each with its own narration:

<!-- say: You have already seen fragment animation in action on earlier slides. It reveals bullet points one at a time, each with its own narration. -->
* First, we introduce the concept
<!-- say: Each fragment gets its own narration, so the viewer hears an explanation timed to each point as it appears. -->
* Then, we add supporting detail
<!-- say: Adding more detail with each new bullet keeps the presentation flowing naturally, just like a live talk. -->
* Finally, we wrap up
<!-- say: In MARP, just use star bullets instead of dashes to create fragments. slideSonnet expands each step into a separate sub-slide with progressive reveal. -->

---

# This Slide Is Skipped

If you see this slide in the video, something went wrong!

<!-- skip -->
