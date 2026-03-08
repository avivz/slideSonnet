---
marp: true
math: katex
---

# slideSonnet

**Text in, video out.**

Compile slide decks into narrated videos --- entirely from text.

<!-- say(voice=alex): [inquisitive] So Sam, what's the deal with slideSonnet? Tell me about it! -->
<!-- say: [excited] Oh you're gonna LOVE this! It takes your plain-text slides and turns them into fully narrated VIDEOS. You just write slides, throw in some comments for narration, and SHAZZAM — you get an MP4! -->

---

# The Problem With Recording Narrations

<!-- say(voice=alex): [skeptical] OK but WHY? ... Can't I just record myself talking over slides? -->
* Recording narrated lectures is tedious
<!-- say: [dry humor] Sure, if you ENJOY sitting in a quiet room with a mic, talking through EVERY ... SINGLE ... slide till you get it right... -->
* One edit means re-recording everything
<!-- say: [sarcastic] And the BEST part — change one slide and you get to re-record it. EVERY... SINGLE... TIME. -->
* **Narration should live in the source**
<!-- say: [enthusiastic] With slideSonnet, your narration is just text sitting next to the code for your slides! Edit a line, hit rebuild, DONE! No mic, no re-recording, no pain! -->

---

# How It Works

<!-- say(voice=alex): [intrigued] Alright, you've got my attention. How does it ACTUALLY work? -->
1) Write slides in **Markdown** (Rendered with MARP) or **LaTeX** (using Beamer)
<!-- say: [confidently] Step one: write your slides. In Markdown or in LaTeX, whatever floats your boat! -->
2) Add `say` comments for narration
<!-- say: Step two: drop in "say" comments. Just text ... with the words you want spoken. That's LITERALLY it! -->
3) Run `slidesonnet build`
<!-- say: [enthusiastic] Step three: run slidesonnet build. It does the speech synthesis, renders your slides, and stitches it ALL together. ONE command and you're done! -->

---

# Quick Start

Install and build your first video in three commands:

```bash
pip install slidesonnet

slidesonnet init         # scaffold a MARP project

slidesonnet build        # compile to MP4
```

<!-- say(voice=alex): [eager] OK I want to try it! What do I do? -->
<!-- say: [confidently] Literally THREE commands. pip install, INIT to set up a project template, and BUILD to make the video. That's IT! [proudly] You'll have a narrated MP4 before your coffee gets cold! -->

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

<!-- say(voice=alex): [surprised] Hold on — the narration is LITERALLY JUST a comment in the Markdown? -->
<!-- say: [proudly] YEP! An HTML comment that starts with say colon. The text inside becomes audio. [excitement building] And here's the FUN part — what you're hearing RIGHT now? [enthusiastic] Written EXACTLY this way! -->

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

<!-- say(voice=alex): [curious] So where does all the CONFIG STUFF go? Voices, text-to-speech settings? -->
<!-- say: [enthusiastic] The playlist file is slide sonnet dot yaml. It's got your text-to-speech backend, your voice mappings, pronunciation dictionaries — the WHOLE deal! [proudly] And slideSonnet finds it AUTOMATICALLY, so you hit build, and everything else JUST WORKS! -->

---

# Multiple Voices

Switch voices on any slide with `voice=`:

```markdown
<!-- say: The default voice narrates. -->
<!-- say(voice=alex): Alex chimes in. -->
<!-- say(voice=alex, pace=slow): Slower delivery. -->
```

Voices are defined in the playlist. Beamer uses `\say[voice=alex]{text}`.

<!-- say(voice=alex): [awe] Wait a SECOND! [in wonder] THIS is how we're using different voices RIGHT NOW? -->
<!-- say: [playfully] YUP! You're alex, and I AM the default voice. You just STICK a voice parameter in the say comment and slideSonnet handles the rest! [proudly] Pretty SLICK, right? -->

---

# Fragment Animation

Bullet points reveal one at a time, each with its own narration:

<!-- say(voice=alex): [curious] Can you do that thing where bullets pop in one at a time? -->
* Use `*` bullets instead of `-` dashes
<!-- say: [confidently] Oh YEAH! Just use star bullets instead of dashes and each one becomes a fragment! -->
* Each fragment gets its own narration
<!-- say: [enthusiastic] Every fragment gets its own sub-slide and narration. EASY! -->
* Just like a live presentation
<!-- say: [enthusiastic] It ends up feeling JUST like a REAL talk — ideas building one by one! -->

---

# Silent and Skipped Slides

Two special annotations:

```markdown
<!-- nonarration -->   pause with no speech
<!-- skip -->          excluded from video
```

Great for title cards, pauses, or draft slides you want to keep in the source.

<!-- say(voice=alex): [wondering] What if I've got a slide that doesn't need any talking? -->
<!-- say: [casually] Easy. Nonarration gives you a quiet pause — nice for title cards. And skip just HIDES the slide from the video completely. Great for drafts. [conspiratorial] Oh, and FUN fact — there's a skipped slide lurking at the END of this slide deck too! -->

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

<!-- say(voice=alex): [curious] What about the FANCY stuff — math? code? images? -->
<!-- say: [confidently] MARP has you COVERED. [excited] Math, syntax-highlighted code, images — all standard Markdown, no plugins. And we've got pronunciation dictionaries too, so names like Dijkstra and Euler ACTUALLY come out right! -->

---

# Iterate Fast

```bash
slidesonnet build --tts piper    # free local TTS
slidesonnet build --preview      # quick low-res render
slidesonnet build --dry-run      # estimate API cost
```

Only changed slides are re-synthesized --- everything else is cached.

<!-- say(voice=alex): [concerned] Doesn't cloud TTS get EXPENSIVE when you're still tweaking things? -->
<!-- say: [reassuringly] NAH, you don't need cloud for drafting. Use Piper — it's FREE! runs locally. Throw in the preview flag for a quick rough cut. [enthusiastic] And the BEST part? slideSonnet caches EVERYTHING! Change one slide, only THAT slide rebuilds. Fast and cheap! -->

---

# Get Started

```bash
pip install slidesonnet
```

Write slides. Add narration. Build great presentations.

**Text in, video out.**

<!-- say(voice=alex): OK I'm SOLD. [excited] Let's DO this! -->
<!-- say: [warmly] THAT'S what I like to hear! pip install slidesonnet, write some slides, add your say comments, and hit build. [enthusiastic] Now go and make SOMETHING AWESOME! -->

---

# This Slide Is Skipped

If you see this slide in the video, something went wrong!

<!-- skip -->
