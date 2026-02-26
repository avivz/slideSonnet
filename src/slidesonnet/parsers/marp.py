"""MARP markdown parser: extract slide images and narration directives."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from slidesonnet.models import SlideAnnotation, SlideNarration
from slidesonnet.parsers.base import SlideParser

logger = logging.getLogger(__name__)

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

# Match fenced code blocks (``` or ~~~, with optional info string)
_FENCE_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[^\n]*\n"  # opening fence + info string
    r".*?"  # content (non-greedy)
    r"^(?P=fence)\s*$",  # matching closing fence
    re.MULTILINE | re.DOTALL,
)

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

    # marp --output treats the path as a file prefix, so we use
    # output_dir/source_stem to get files like output_dir/slides.001, etc.
    output_prefix = output_dir / source.stem

    cmd = [
        "marp",
        "--no-stdin",
        str(source),
        "--images",
        "png",
        "--output",
        str(output_prefix),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        logger.error("'marp' not found. Install with: npm install -g @marp-team/marp-cli")
        raise SystemExit(1)
    except subprocess.CalledProcessError as e:
        logger.error("marp failed:\n%s", e.stderr)
        raise SystemExit(1)

    # marp --images png produces files like: slides.001.png, slides.002.png
    # or extensionless: slides.001, slides.002 (newer marp versions)
    stem = source.stem
    images = sorted(output_dir.glob(f"{stem}.[0-9][0-9][0-9].png"))
    if not images:
        images = sorted(output_dir.glob(f"{stem}.[0-9][0-9][0-9]"))
    return images


def _split_slides(text: str) -> list[str]:
    """Split MARP markdown into individual slides on --- separators.

    The first slide includes any front matter.
    Ignores ``---`` inside fenced code blocks (``` or ~~~).
    """
    # MARP uses --- as slide separator (at start of line, possibly with whitespace)
    # But the first --- pair is YAML front matter
    lines = text.split("\n")
    separator_indices = []
    in_fence = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Detect fenced code block boundaries (``` or ~~~, with optional info string)
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_char = stripped[:3]
            if in_fence:
                # Closing fence: must be only fence chars (no info string)
                if stripped.rstrip(fence_char[0]) == "":
                    in_fence = False
            else:
                in_fence = True
            continue
        if not in_fence and stripped == "---":
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
    # Strip fenced code blocks so directives inside them are ignored
    text = _FENCE_RE.sub("", text)

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
            logger.warning(
                "%s slide %d: empty <!-- say: --> — did you mean <!-- silent -->?",
                source, index,
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
    logger.warning(
        "%s slide %d: no annotation (use <!-- say: -->, <!-- silent -->, or <!-- skip -->)",
        source, index,
    )
    return SlideNarration(index=index, annotation=SlideAnnotation.NONE)
