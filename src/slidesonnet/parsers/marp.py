"""MARP markdown parser: extract slide images and narration directives."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from slidesonnet.models import SlideAnnotation, SlideNarration
from slidesonnet.parsers.base import SlideParser

# Match <!-- say: text --> or <!-- say(voice=alice, pace=slow): text -->
_SAY_RE = re.compile(
    r"<!--\s*say"
    r"(?:\(([^)]*)\))?"  # optional (params)
    r"\s*:\s*"
    r"(.*?)"  # narration text (non-greedy)
    r"\s*-->",
    re.DOTALL,
)

# Match <!-- silent -->
_SILENT_RE = re.compile(r"<!--\s*silent\s*-->", re.IGNORECASE)

# Match <!-- skip -->
_SKIP_RE = re.compile(r"<!--\s*skip\s*-->", re.IGNORECASE)

# Parse key=value pairs from say(...) params
_PARAM_RE = re.compile(r"(\w+)\s*=\s*(\w+)")


class MarpParser(SlideParser):
    def parse(self, source: Path, build_dir: Path) -> list[SlideNarration]:
        text = source.read_text(encoding="utf-8")
        raw_slides = _split_slides(text)
        slides = []

        for i, slide_text in enumerate(raw_slides, start=1):
            slide = _parse_slide(i, slide_text, source)
            slides.append(slide)

        return slides


def extract_images(source: Path, output_dir: Path) -> list[Path]:
    """Run marp CLI to extract slide images as PNGs.

    Returns list of generated image paths in slide order.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "marp",
        str(source),
        "--images",
        "png",
        "--output",
        str(output_dir),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        print(
            "ERROR: 'marp' not found. Install with: npm install -g @marp-team/marp-cli",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: marp failed:\n{e.stderr}", file=sys.stderr)
        raise SystemExit(1)

    # marp --images png produces files like: source.001.png, source.002.png, ...
    images = sorted(output_dir.glob(f"{source.stem}.*.png"))
    if not images:
        # Also try plain numbered pattern
        images = sorted(output_dir.glob("*.png"))
    return images


def _split_slides(text: str) -> list[str]:
    """Split MARP markdown into individual slides on --- separators.

    The first slide includes any front matter.
    """
    # MARP uses --- as slide separator (at start of line, possibly with whitespace)
    # But the first --- pair is YAML front matter
    lines = text.split("\n")
    separator_indices = []

    for i, line in enumerate(lines):
        if line.strip() == "---":
            separator_indices.append(i)

    if len(separator_indices) < 2:
        # No slides or just front matter
        return [text] if text.strip() else []

    # First two --- are front matter boundaries
    # Slides are separated by subsequent ---
    slides = []
    # First slide: everything from after front matter close to next ---
    fm_close = separator_indices[1]
    slide_separators = separator_indices[2:]

    if not slide_separators:
        # Only one slide after front matter
        content = "\n".join(lines[fm_close + 1 :])
        if content.strip():
            slides.append(content)
        return slides

    # First slide: from fm_close+1 to first separator
    slides.append("\n".join(lines[fm_close + 1 : slide_separators[0]]))

    # Middle slides
    for j in range(len(slide_separators) - 1):
        start = slide_separators[j] + 1
        end = slide_separators[j + 1]
        slides.append("\n".join(lines[start:end]))

    # Last slide: from last separator to end
    last_content = "\n".join(lines[slide_separators[-1] + 1 :])
    if last_content.strip():
        slides.append(last_content)

    return slides


def _parse_slide(index: int, text: str, source: Path) -> SlideNarration:
    """Parse annotations from a single slide's text."""

    # Check for <!-- skip -->
    if _SKIP_RE.search(text):
        return SlideNarration(index=index, annotation=SlideAnnotation.SKIP)

    # Check for <!-- silent -->
    if _SILENT_RE.search(text):
        return SlideNarration(index=index, annotation=SlideAnnotation.SILENT)

    # Check for <!-- say: ... -->
    say_matches = _SAY_RE.findall(text)
    if say_matches:
        # Concatenate all say blocks for this slide
        narration_parts = []
        voice = None
        pace = None

        for params_str, narration_text in say_matches:
            narration_text = narration_text.strip()
            # Normalize whitespace (multi-line comments)
            narration_text = re.sub(r"\s+", " ", narration_text)
            narration_parts.append(narration_text)

            if params_str:
                params = dict(_PARAM_RE.findall(params_str))
                if "voice" in params:
                    voice = params["voice"]
                if "pace" in params:
                    pace = params["pace"]

        full_narration = " ".join(narration_parts)

        if not full_narration:
            print(
                f"WARNING: {source} slide {index}: empty <!-- say: --> "
                f"— did you mean <!-- silent -->?",
                file=sys.stderr,
            )
            return SlideNarration(index=index, annotation=SlideAnnotation.SILENT)

        return SlideNarration(
            index=index,
            annotation=SlideAnnotation.SAY,
            narration_raw=full_narration,
            voice=voice,
            pace=pace,
        )

    # No annotation at all — warn
    print(
        f"WARNING: {source} slide {index}: no annotation "
        f"(use <!-- say: -->, <!-- silent -->, or <!-- skip -->)",
        file=sys.stderr,
    )
    return SlideNarration(index=index, annotation=SlideAnnotation.NONE)
