---
marp: true
math: katex
---

# slideSonnet

**Text in, video out.**

Compile slide decks into narrated videos --- entirely from text.

<!-- say(voice=alex): So Sam, what's the deal with slideSonnet? Tell me about it. -->
<!-- say: Oh you're gonna *love* this. It takes your plain-text slides and turns them into narrated videos. You just write slides, throw in some comments for narration, and vwalla! you get an MP4. -->

---

# The Problem

<!-- say(voice=alex): OK but why? Can't I just record myself talking over slides? -->
* Recording narrated lectures is tedious
<!-- say: Sure, if you enjoy sitting in a quiet room with a mic, talking through *every* single slide till you get it right... -->
* One edit means re-recording everything
<!-- say: And the best part — change one slide and you get to re-record it. Every. Single. Time. -->
* **Narration should live in the source**
<!-- say: With slideSonnet, your narration is just text that's sitting next to the code for your slides. Edit a line, hit rebuild, done. No mic, no re-recording, no pain. -->

---

# How It Works

<!-- say(voice=alex): Alright, you've got my attention. How does it actually work? -->
1) Write slides in **Markdown** (Rendered with MARP) or **LaTeX** (using Beamer)
<!-- say: Step one — write your slides. In Markdown or Beamer LaTeX, whatever floats your boat. -->
2) Add `say` comments for narration
<!-- say: Step two — drop in say comments. Just text with the words you want spoken. That's literally it. -->
3) Run `slidesonnet build`
<!-- say: Step three — run slidesonnet build. It does the speech synthesis, renders your slides, stitches it all together into a video. One command and you're done. -->

---

# Quick Start

Install and build your first video in three commands:

```bash
pip install slidesonnet

slidesonnet init         # scaffold a MARP project

slidesonnet build        # compile to MP4
```

<!-- say(voice=alex): OK I want to try it. What do I do? -->
<!-- say: Literally three commands. pip install, init to set up a project template, build to make the video. That's it — you'll have a narrated MP4 before your coffee gets cold. -->

---

# Slides and Narration

MARP slides are plain Markdown separated by `---`. Narration is an HTML comment:

```markdown
---
marp: true
---

# My Slide

Some visible content.

<!-- say: This text will be spoken aloud. -->

---

# Next Slide
...
```

<!-- say(voice=alex): Hold on — the narration is literally just a comment in the Markdown? -->
<!-- say: Yep! An HTML comment that starts with say colon. The text inside becomes audio. And here's the fun part — what you're hearing right now? Written *exactly* this way! -->

---

# The Playlist

`slidesonnet.yaml` ties everything together:

```yaml
tts:
  backend: elevenlabs
voices:
  default:
    elevenlabs: 21m00Tcm4TlvDq8ikWAM
  alex:
    elevenlabs: nPczCjzI2devNBz1zQrb
pronunciation:
  shared:
    - pronunciation/general.md
modules:
  - slides.md
```

<!-- say(voice=alex): So where does all the config stuff go? Voices, text-to-speech settings? -->
<!-- say: The playlist file — slidesonnet dot yaml. It's got your text-to-speech backend, voice mappings, pronunciation dictionaries, the whole deal. And slideSonnet finds it automatically, so you just run build and everything just works. -->

---

# Multiple Voices

Switch voices on any slide with `voice=`:

```markdown
<!-- say: The default voice narrates. -->
<!-- say(voice=alex): Alex chimes in. -->
<!-- say(voice=alex, pace=slow): Slower delivery. -->
```

Voices are defined in the playlist. Beamer uses `\say[voice=alex]{text}`.

<!-- say(voice=alex): Wait a second — this is how we're using different voices right now? -->
<!-- say: Yup! You're alex, and I'm the default voice. You just stick a voice parameter in the say comment and slide sonnet handles the rest. Pretty slick, right? -->

---

# Fragment Animation

Bullet points reveal one at a time, each with its own narration:

<!-- say(voice=alex): Can you do that thing where bullets pop in one at a time? -->
* Use `*` bullets instead of `-` dashes
<!-- say: Oh yeah. Just use star bullets instead of dashes and each one becomes a fragment. -->
* Each fragment gets its own narration
<!-- say: Every fragment gets its own sub-slide and narration. Easy! -->
* Just like a live presentation
<!-- say: It ends up feeling just like a real talk. Ideas building one by one. -->

---

# Silent and Skipped Slides

Two special annotations:

```markdown
<!-- nonarration -->   pause with no speech
<!-- skip -->          excluded from video
```

Great for title cards, pauses, or draft slides you want to keep in the source.

<!-- say(voice=alex): What if I've got a slide that doesn't need any talking? -->
<!-- say: Easy. Nonarration gives you a quiet pause — nice for title cards. And skip just hides the slide from the video completely. Great for drafts. Oh, and fun fact — there's a skipped slide lurking at the end of this slide deck too! -->

---

# Rich Content

MARP handles math, code, and images --- no plugins needed.

**Math** (KaTeX): $\quad e^{i\pi} + 1 = 0$

**Code:**
```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

![w:280 The Great Wave](images/great-wave.jpg)

<!-- say(voice=alex): What about the fancy stuff — math, code, images? -->
<!-- say: MARP has you covered. Math, syntax-highlighted code, images — all standard Markdown, no plugins. And we've got pronunciation dictionaries too, so names like Dijkstra and Euler actually come out right. -->

---

# Iterate Fast

```bash
slidesonnet build --tts piper    # free local TTS
slidesonnet build --preview      # quick low-res render
slidesonnet build --dry-run      # estimate API cost
```

Only changed slides are re-synthesized --- everything else is cached.

<!-- say(voice=alex): Doesn't cloud TTS get expensive when you're still tweaking things? -->
<!-- say: Nah, you don't need cloud for drafting. Use Piper — it's free, runs locally. Throw in the preview flag for a quick rough cut. And the best part? slideSonnet caches everything. Change one slide, only that slide rebuilds. Fast and cheap! -->

---

# Get Started

```bash
pip install slidesonnet
```

Write slides. Add narration. Build great presentations.

**Text in, video out.**

<!-- say(voice=alex): OK I'm sold. Let's do this. -->
<!-- say: That's what I like to hear! pip install slidesonnet, write some slides, add your say comments, and hit build. Go make something awesome! -->

---

# This Slide Is Skipped

If you see this slide in the video, something went wrong!

<!-- skip -->
