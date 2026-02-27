---
title: slideSonnet Feature Showcase
tts:
  backend: piper
  piper:
    model: en_US-lessac-medium
  // To use ElevenLabs instead, set backend to elevenlabs and uncomment:
  // elevenlabs:
  //   api_key_env: ELEVENLABS_API_KEY
  //   voice_id: your_voice_id_here
  //   model_id: eleven_multilingual_v2
  //   stability: 0.5
  //   similarity_boost: 0.75
voices:
  default: en_US-lessac-medium
  narrator: en_US-amy-medium
  expert: en_US-joe-medium
pronunciation:
  - pronunciation/general.md
  - pronunciation/names.md
video:
  resolution: 1920x1080
  fps: 24
  crf: 23
  pad_seconds: 1.5
  silence_duration: 3.0
  crossfade: 0.5
---

# slideSonnet Feature Showcase

// Build with: slidesonnet build lecture.md

1. [Introduction](part1.md)
2. [Pipeline and Beamer](part2.tex)
3. [Transition](animations/transition.mp4)
4. [Rich Content](part3.md)
