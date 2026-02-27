---
title: My Presentation
tts:
  backend: piper
  piper:
    model: en_US-lessac-medium
  // To use ElevenLabs, uncomment below and set backend to elevenlabs:
  // elevenlabs:
  //   api_key_env: ELEVENLABS_API_KEY
  //   voice_id: your_voice_id_here
  //   model_id: eleven_multilingual_v2
voices:
  default: en_US-lessac-medium
  // alice: en_US-amy-medium
pronunciation:
  - pronunciation/terms.md
video:
  resolution: 1920x1080
  pad_seconds: 1.5
  pre_silence: 1.0
  silence_duration: 3.0
  crossfade: 0.5
---

# My Presentation

// Add your modules below. Each line links to a slide deck or video file.
// Type is auto-detected: .md = MARP, .tex = Beamer, .mp4 = video
// Lines starting with // are comments and ignored by the build.

1. [Introduction](01-intro/slides.md)
