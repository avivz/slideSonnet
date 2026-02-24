"""Project scaffolding for `slidesonnet init`."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from slidesonnet.playlist import _split_front_matter

GITIGNORE_CONTENT = """\
# slideSonnet build artifacts
.build/

# API keys and secrets
.env

# OS
.DS_Store
"""

ENV_TEMPLATE = """\
# ElevenLabs API key (get from https://elevenlabs.io)
ELEVENLABS_API_KEY=your_api_key_here
"""

BLANK_PLAYLIST = """\
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
  pad_seconds: 0.5
  silence_duration: 3.0
---

# My Presentation

// Add your modules below. Each line links to a slide deck or video file.
// Type is auto-detected: .md = MARP, .tex = Beamer, .mp4 = video
// Lines starting with // are comments and ignored by the build.

1. [Introduction](01-intro/slides.md)
"""

BLANK_SLIDES = """\
---
marp: true
---

# Welcome

<!-- say: Welcome to this presentation. -->

---

# Main Content

<!-- say: Here is the main content of the talk. -->

---

# Summary

<!-- say: That concludes this presentation. Thank you for watching. -->
"""

BLANK_PRONUNCIATION = """\
# Pronunciation Guide

// Add pronunciation overrides below.
// Format: **Word**: phonetic-spelling
// These are applied before text-to-speech synthesis.

// ## Example
//
// **Dijkstra**: DYKE-struh
// **Euler**: OY-ler
"""

EXAMPLE_PLAYLIST = """\
---
title: Graph Theory - Lecture 1
tts:
  backend: piper
  piper:
    model: en_US-lessac-medium
voices:
  default: en_US-lessac-medium
pronunciation:
  - pronunciation/cs-terms.md
video:
  resolution: 1920x1080
  pad_seconds: 0.5
  silence_duration: 3.0
---

# Graph Theory - Lecture 1

// This is an example slideSonnet project.
// Build with: slidesonnet build lecture01.md
// Preview with: slidesonnet preview lecture01.md

1. [Introduction](01-intro/slides.md)
2. [Definitions](02-definitions/slides.md)
"""

EXAMPLE_SLIDES_INTRO = """\
---
marp: true
---

# Introduction to Graph Theory

<!-- say: Welcome to the first lecture on graph theory. Today we will cover the basic definitions and some fundamental properties of graphs. -->

---

# Why Study Graphs?

- Model relationships and connections
- Used in computer science, biology, social networks

<!-- say: Graphs are one of the most versatile tools in mathematics and computer science. They let us model any kind of relationship or connection between objects. -->

---

# Course Overview

<!-- silent -->
"""

EXAMPLE_SLIDES_DEFS = """\
---
marp: true
---

# What is a Graph?

- A set of **vertices** (nodes)
- Connected by **edges**

<!-- say: A graph is a mathematical structure consisting of a set of vertices, sometimes called nodes, connected by edges. Think of it like a social network where people are vertices and friendships are edges. -->

---

# Euler's Theorem

$$\\sum_{v \\in V} \\deg(v) = 2|E|$$

<!-- say: Euler's handshaking theorem tells us that the sum of all vertex degrees equals twice the number of edges. This is because each edge contributes exactly two to the total degree count. -->

---

# Dijkstra's Algorithm

- Finds shortest paths in weighted graphs
- Greedy approach

<!-- say: Dijkstra's algorithm is a fundamental algorithm for finding the shortest path between nodes in a weighted graph. It uses a greedy approach, always expanding the closest unvisited node. -->
"""

EXAMPLE_PRONUNCIATION = """\
# CS Pronunciation Guide

## People

**Dijkstra**: DYKE-struh
**Euler**: OY-ler
**Knuth**: kuh-NOOTH

## Terms

**adjacency**: uh-JAY-suhn-see
**isomorphism**: eye-so-MOR-fizm
"""


def init_blank(target_dir: Path) -> None:
    """Create a blank project scaffold with documented config."""
    target_dir.mkdir(parents=True, exist_ok=True)

    _write(target_dir / "lecture01.md", BLANK_PLAYLIST)
    _write(target_dir / ".gitignore", GITIGNORE_CONTENT)
    _write(target_dir / ".env", ENV_TEMPLATE)

    pron_dir = target_dir / "pronunciation"
    pron_dir.mkdir(exist_ok=True)
    _write(pron_dir / "terms.md", BLANK_PRONUNCIATION)

    slides_dir = target_dir / "01-intro"
    slides_dir.mkdir(exist_ok=True)
    _write(slides_dir / "slides.md", BLANK_SLIDES)


def init_from(target_dir: Path, source_playlist: Path) -> None:
    """Copy config from an existing project."""
    target_dir.mkdir(parents=True, exist_ok=True)

    # Read and copy front matter
    text = source_playlist.read_text(encoding="utf-8")
    config_dict, _ = _split_front_matter(text)

    # Create playlist with copied config but empty module list
    yaml_text = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
    playlist_content = (
        f"---\n{yaml_text}---\n\n# My Presentation\n\n1. [Introduction](01-intro/slides.md)\n"
    )
    _write(target_dir / "lecture01.md", playlist_content)

    # Copy pronunciation files
    source_dir = source_playlist.parent
    pron_paths = config_dict.get("pronunciation", [])
    for pron_rel in pron_paths:
        src = source_dir / pron_rel
        dst = target_dir / pron_rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # Create .env with blanked values
    source_env = source_dir / ".env"
    if source_env.exists():
        blanked = []
        for line in source_env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key = line.split("=", 1)[0]
                blanked.append(f"{key}=your_value_here")
            else:
                blanked.append(line)
        _write(target_dir / ".env", "\n".join(blanked) + "\n")
    else:
        _write(target_dir / ".env", ENV_TEMPLATE)

    _write(target_dir / ".gitignore", GITIGNORE_CONTENT)

    # Create starter slides
    slides_dir = target_dir / "01-intro"
    slides_dir.mkdir(exist_ok=True)
    _write(slides_dir / "slides.md", BLANK_SLIDES)


def init_example(target_dir: Path) -> None:
    """Create a full working example project."""
    target_dir.mkdir(parents=True, exist_ok=True)

    _write(target_dir / "lecture01.md", EXAMPLE_PLAYLIST)
    _write(target_dir / ".gitignore", GITIGNORE_CONTENT)
    _write(target_dir / ".env", ENV_TEMPLATE)

    pron_dir = target_dir / "pronunciation"
    pron_dir.mkdir(exist_ok=True)
    _write(pron_dir / "cs-terms.md", EXAMPLE_PRONUNCIATION)

    intro_dir = target_dir / "01-intro"
    intro_dir.mkdir(exist_ok=True)
    _write(intro_dir / "slides.md", EXAMPLE_SLIDES_INTRO)

    defs_dir = target_dir / "02-definitions"
    defs_dir.mkdir(exist_ok=True)
    _write(defs_dir / "slides.md", EXAMPLE_SLIDES_DEFS)


def _write(path: Path, content: str) -> None:
    """Write file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
