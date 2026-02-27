"""MARP markdown parser: extract slide images and narration directives."""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slidesonnet.exceptions import ParserError
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


@dataclass
class _SayCommand:
    """Parsed data from a single <!-- say --> directive."""

    sub_slide: int  # 1-based sub-slide target
    text: str
    voice: str | None
    pace: str | None


class MarpParser(SlideParser):
    def parse(self, source: Path, build_dir: Path) -> list[SlideNarration]:
        text = source.read_text(encoding="utf-8")
        raw_slides = _split_slides(text)
        slides: list[SlideNarration] = []
        next_index = 1

        for slide_text in raw_slides:
            parsed = _parse_slide(next_index, slide_text, source)
            slides.extend(parsed)
            next_index += len(parsed)

        return slides


def extract_images(source: Path, output_dir: Path) -> list[Path]:
    """Run marp CLI to export HTML, then screenshot each slide state with Playwright.

    Returns list of generated image paths in slide order.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    return _extract_images_via_playwright(source, output_dir)


def _extract_images_via_playwright(source: Path, output_dir: Path) -> list[Path]:
    """Export HTML via marp-cli, then screenshot each slide state with Playwright."""
    html_path = output_dir / f"_{source.stem}_presentation.html"

    # Export HTML
    cmd = [
        "marp",
        "--no-stdin",
        "--html",
        str(source),
        "--output",
        str(html_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise ParserError("'marp' not found. Install with: npm install -g @marp-team/marp-cli")
    except subprocess.CalledProcessError as e:
        raise ParserError(f"marp failed:\n{e.stderr}")

    try:
        images = _screenshot_presentation(html_path, output_dir, source.stem)
    finally:
        if html_path.exists():
            html_path.unlink()

    return images


def _import_sync_playwright() -> Callable[[], Any]:
    """Import and return ``sync_playwright`` from the Playwright package."""
    from playwright.sync_api import sync_playwright

    func: Callable[[], Any] = sync_playwright
    return func


def _ensure_chromium() -> None:
    """Install Chromium browser for Playwright if not already present."""
    sync_playwright = _import_sync_playwright()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            browser.close()
    except Exception:
        logger.info("Installing Chromium for Playwright (first-time setup)...")
        subprocess.run(
            ["playwright", "install", "--with-deps", "chromium"],
            check=True,
            capture_output=True,
            text=True,
        )


def _screenshot_presentation(html_path: Path, output_dir: Path, stem: str) -> list[Path]:
    """Open the Marp HTML presentation in headless Chromium and screenshot each step.

    Navigates through slides and fragment steps using ArrowRight key presses.
    Automatically installs Chromium on first use if needed.
    Returns list of PNG paths in presentation order.
    """
    _ensure_chromium()

    sync_playwright = _import_sync_playwright()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(html_path.as_uri())
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("section[id]")

        # Count total steps: each section is a slide, fragments add extra steps
        total_steps: int = page.evaluate("""() => {
            const sections = document.querySelectorAll('section[id]');
            let steps = 0;
            for (const section of sections) {
                const fragments = parseInt(section.dataset.marpitFragments || '0', 10);
                steps += 1 + fragments;
            }
            return steps;
        }""")

        images: list[Path] = []
        for i in range(total_steps):
            img_path = output_dir / f"{stem}.{i + 1:03d}.png"
            page.screenshot(path=str(img_path))
            images.append(img_path)
            if i < total_steps - 1:
                page.keyboard.press("ArrowRight")
                page.wait_for_timeout(150)

        browser.close()

    return images


def _split_slides(text: str) -> list[str]:
    """Split MARP markdown into individual slides on --- separators.

    The first slide includes any front matter.
    Ignores ``---`` inside fenced code blocks (``` or ~~~).
    """
    # MARP uses --- as slide separator (at start of line, possibly with whitespace)
    # But the first --- pair is YAML front matter
    lines = text.split("\n")
    separator_indices = _find_separator_indices(lines)

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


def _find_separator_indices(lines: list[str]) -> list[int]:
    """Find line indices of ``---`` separators, ignoring those inside code fences."""
    separator_indices: list[int] = []
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

    return separator_indices


def _parse_say_params(params_str: str) -> tuple[int, str | None, str | None]:
    """Parse the optional parenthesized params of a ``<!-- say(...) -->`` directive.

    Supports:
      - ``<!-- say: text -->``                → sub_slide=0 (unset)
      - ``<!-- say(2): text -->``             → sub_slide=2 (bare number)
      - ``<!-- say(slide=2): text -->``       → sub_slide=2 (explicit key)
      - ``<!-- say(2, voice=alice): text -->`` → sub_slide=2, voice=alice

    Returns (sub_slide, voice, pace).  sub_slide=0 means no explicit target.
    """
    sub_slide = 0
    voice: str | None = None
    pace: str | None = None

    if not params_str:
        return sub_slide, voice, pace

    kv_params = dict(_PARAM_RE.findall(params_str))

    # Check for bare number: strip key=value pairs to see if a standalone number remains
    stripped = _PARAM_RE.sub("", params_str).replace(",", "").strip()
    if stripped.isdigit():
        sub_slide = int(stripped)

    if "slide" in kv_params:
        sub_slide = int(kv_params["slide"])
    if "voice" in kv_params:
        voice = kv_params["voice"]
    if "pace" in kv_params:
        pace = kv_params["pace"]

    return sub_slide, voice, pace


def _parse_slide(start_index: int, text: str, source: Path) -> list[SlideNarration]:
    """Parse annotations from a single slide's text.

    Returns one ``SlideNarration`` per sub-slide.  Slides with multiple
    ``<!-- say -->`` directives are expanded into sub-slides; slides with
    zero or one say return a single-element list.
    """
    # Strip fenced code blocks so directives inside them are ignored
    clean_text = _FENCE_RE.sub("", text)

    # Check for <!-- skip --> — takes priority over everything
    if _SKIP_RE.search(clean_text):
        return [SlideNarration(index=start_index, annotation=SlideAnnotation.SKIP)]

    # Check for <!-- silent --> (without any say)
    say_matches = _SAY_RE.findall(clean_text)
    if _SILENT_RE.search(clean_text) and not say_matches:
        return [SlideNarration(index=start_index, annotation=SlideAnnotation.SILENT)]

    if not say_matches:
        # No annotation at all — warn
        logger.warning(
            "%s slide %d: no annotation (use <!-- say: -->, <!-- silent -->, or <!-- skip -->)",
            source,
            start_index,
        )
        return [SlideNarration(index=start_index, annotation=SlideAnnotation.NONE)]

    # --- Expand says into sub-slides ---
    # Check if any say has an explicit slide target
    has_explicit = any(_parse_say_params(p)[0] > 0 for p, _ in say_matches)

    say_commands: list[_SayCommand] = []
    for i, (params_str, narration_text) in enumerate(say_matches, start=1):
        clean_narration = narration_text.strip()
        clean_narration = re.sub(r"\s+", " ", clean_narration)
        sub_slide, voice, pace = _parse_say_params(params_str)

        if not has_explicit:
            sub_slide = i  # positional: 1, 2, 3, ...
        elif sub_slide == 0:
            sub_slide = 1  # explicit mode default

        say_commands.append(
            _SayCommand(sub_slide=sub_slide, text=clean_narration, voice=voice, pace=pace)
        )

    # Determine number of sub-slides
    n_sub = max(cmd.sub_slide for cmd in say_commands)

    # Build results — one SlideNarration per sub-slide
    results: list[SlideNarration] = []
    for sub_idx in range(1, n_sub + 1):
        group = [cmd for cmd in say_commands if cmd.sub_slide == sub_idx]
        slide_index = start_index + sub_idx - 1

        if not group:
            logger.warning(
                "%s slide %d, sub-slide %d: no narration — treating as silent",
                source,
                start_index,
                sub_idx,
            )
            results.append(SlideNarration(index=slide_index, annotation=SlideAnnotation.SILENT))
            continue

        narration_parts = [cmd.text for cmd in group]
        full_narration = " ".join(narration_parts)

        # Use the last specified voice/pace
        group_voice: str | None = None
        group_pace: str | None = None
        for cmd in group:
            if cmd.voice is not None:
                group_voice = cmd.voice
            if cmd.pace is not None:
                group_pace = cmd.pace

        if not full_narration:
            logger.warning(
                "%s slide %d: empty <!-- say: --> — did you mean <!-- silent -->?",
                source,
                start_index,
            )
            results.append(SlideNarration(index=slide_index, annotation=SlideAnnotation.SILENT))
            continue

        results.append(
            SlideNarration(
                index=slide_index,
                annotation=SlideAnnotation.SAY,
                narration_raw=full_narration,
                voice=group_voice,
                pace=group_pace,
            )
        )

    return results
