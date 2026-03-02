"""MARP markdown parser: extract slide images and narration directives."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from slidesonnet.exceptions import ParserError
from slidesonnet.models import SlideAnnotation, SlideNarration
from slidesonnet.parsers.base import SlideParser
from slidesonnet.parsers.expansion import (
    SayCommand,
    expand_sub_slides,
    parse_say_params,
    parse_silence_duration,
)

logger = logging.getLogger(__name__)

# Match <!-- say: text --> or <!-- say(voice=alice, pace=slow): text -->
_SAY_RE = re.compile(
    r"<!--\s*say"
    r"(?:\(([^)]*)\))?"  # optional (params)
    r"\s*:\s*"
    r"(.*?)"  # narration text (non-greedy)
    r"-->",
    re.DOTALL,
)

# Match <!-- nonarration --> or <!-- nonarration(duration) -->
_SILENT_RE = re.compile(r"<!--\s*nonarration\s*(?:\(([^)]*)\))?\s*-->", re.IGNORECASE)

# Match <!-- skip -->
_SKIP_RE = re.compile(r"<!--\s*skip\s*-->", re.IGNORECASE)


# Fragment list markers (Marp animated items)
_FRAGMENT_UL_RE = re.compile(r"^\s*\*\s", re.MULTILINE)
_FRAGMENT_OL_RE = re.compile(r"^\s*\d+\)\s", re.MULTILINE)


class MarpParser(SlideParser):
    def parse(self, source: Path, build_dir: Path) -> list[SlideNarration]:
        text = source.read_text(encoding="utf-8")
        raw_slides = _split_slides(text)
        slides: list[SlideNarration] = []
        next_index = 1
        next_image_index = 1

        for slide_text in raw_slides:
            parsed, n_visual_states = _parse_slide(next_index, slide_text, source, next_image_index)
            slides.extend(parsed)
            next_index += len(parsed)
            next_image_index += n_visual_states

        return slides


def extract_images(source: Path, output_dir: Path) -> list[Path]:
    """Run marp CLI to export HTML, then screenshot each slide state with Playwright.

    Returns list of generated image paths in slide order.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    return _extract_images_via_playwright(source, output_dir)


def export_pdf(source: Path, output_path: Path) -> None:
    """Run marp CLI to export a PDF of the presentation."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["marp", "--no-stdin", "--html", "--pdf", str(source), "--output", str(output_path)]
    css_files = sorted(source.parent.glob("*.css"))
    if css_files:
        cmd.extend(["--theme-set"] + [str(f) for f in css_files])
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise ParserError("'marp' not found. Install with: npm install -g @marp-team/marp-cli")
    except subprocess.CalledProcessError as e:
        raise ParserError(f"marp --pdf failed:\n{e.stderr}")


def _extract_images_via_playwright(source: Path, output_dir: Path) -> list[Path]:
    """Export HTML via marp-cli, then screenshot each slide state with Playwright."""
    html_path = output_dir / f"_{source.stem}_presentation.html"

    # Export HTML (source file must come before --theme-set to avoid yargs
    # array option swallowing the positional argument)
    cmd = ["marp", "--no-stdin", "--html", str(source), "--output", str(html_path)]
    css_files = sorted(source.parent.glob("*.css"))
    if css_files:
        cmd.extend(["--theme-set"] + [str(f) for f in css_files])
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
            [sys.executable, "-m", "playwright", "install", "chromium"],
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
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(html_path.as_uri())
            page.wait_for_load_state("networkidle")
            page.wait_for_selector("section[id]")

            # Hide Marp's bespoke.js navigation toolbar (osc) so it doesn't appear in screenshots.
            page.evaluate("""() => {
                const style = document.createElement('style');
                style.textContent = 'bespoke-marp-osc, [data-bespoke-marp-osc],'
                    + ' .bespoke-marp-osc { display: none !important; }';
                document.head.appendChild(style);
            }""")

            # Detect slides whose content overflows the viewport (clipped in PNG).
            overflow_info: list[dict[str, int]] = page.evaluate("""() => {
                const sections = document.querySelectorAll('section[id]');
                const results = [];
                for (let i = 0; i < sections.length; i++) {
                    const s = sections[i];
                    if (s.scrollHeight > s.clientHeight) {
                        results.push({
                            slide: i + 1,
                            content: s.scrollHeight,
                            viewport: s.clientHeight
                        });
                    }
                }
                return results;
            }""")
            for info in overflow_info:
                logger.warning(
                    "%s slide %d: content overflows by %dpx (%dpx > %dpx viewport)",
                    stem,
                    info["slide"],
                    info["content"] - info["viewport"],
                    info["content"],
                    info["viewport"],
                )

            # Count total steps: each section is a slide, fragments add extra steps.
            # A section with N fragments produces N+1 visual states (bare + N reveals).
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
        finally:
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
    fence_char: str | None = None
    fence_len: int = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            char = stripped[0]
            length = len(stripped) - len(stripped.lstrip(char))
            if fence_char is not None:
                # Inside fence: close only with same char, >= length, no trailing content
                if char == fence_char and length >= fence_len and stripped.rstrip(char) == "":
                    fence_char = None
            else:
                fence_char = char
                fence_len = length
            continue
        if fence_char is None and stripped == "---":
            separator_indices.append(i)

    return separator_indices


def _strip_fences(text: str) -> str:
    """Remove fenced code blocks from text, respecting CommonMark rules."""
    lines = text.split("\n")
    result: list[str] = []
    fence_char: str | None = None
    fence_len: int = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            char = stripped[0]
            length = len(stripped) - len(stripped.lstrip(char))
            if fence_char is not None:
                if char == fence_char and length >= fence_len and stripped.rstrip(char) == "":
                    fence_char = None
                continue
            else:
                fence_char = char
                fence_len = length
                continue
        if fence_char is None:
            result.append(line)

    return "\n".join(result)


def _count_fragments(text: str) -> int:
    """Count fragment list items (``*`` and ``N)``) outside fenced code blocks."""
    clean = _strip_fences(text)
    return len(_FRAGMENT_UL_RE.findall(clean)) + len(_FRAGMENT_OL_RE.findall(clean))


def _parse_slide(
    start_index: int, text: str, source: Path, start_image_index: int = 1
) -> tuple[list[SlideNarration], int]:
    """Parse annotations from a single slide's text.

    Returns a tuple of (slides, n_visual_states).  ``n_visual_states`` is
    the number of images the extractor produces for this visual slide
    (``1 + n_fragments``), used to advance the image index counter.

    Slides with multiple ``<!-- say -->`` directives are expanded into
    sub-slides; slides with zero or one say return a single-element list.

    For slides with fragment items (``*`` / ``N)``), the sub-slide count is
    at least ``1 + n_fragments`` to match the visual states produced by
    Playwright (bare slide + each fragment reveal).
    """
    # Strip fenced code blocks so directives inside them are ignored
    clean_text = _strip_fences(text)

    # Compute visual states early — needed for image_index on all paths
    n_fragments = _count_fragments(text)
    n_visual_states = 1 + n_fragments

    # Check for <!-- skip --> — takes priority over everything
    if _SKIP_RE.search(clean_text):
        return (
            [
                SlideNarration(
                    index=start_index,
                    image_index=start_image_index,
                    annotation=SlideAnnotation.SKIP,
                )
            ],
            n_visual_states,
        )

    # Check for <!-- nonarration --> (without any say)
    say_matches = _SAY_RE.findall(clean_text)
    silent_match = _SILENT_RE.search(clean_text)
    if silent_match and not say_matches:
        silence_override = parse_silence_duration(
            silent_match.group(1), source, start_index, label="slide"
        )
        return (
            [
                SlideNarration(
                    index=start_index,
                    image_index=start_image_index,
                    annotation=SlideAnnotation.SILENT,
                    silence_override=silence_override,
                )
            ],
            n_visual_states,
        )

    if not say_matches:
        # No annotation at all — warn
        logger.warning(
            "%s slide %d: no annotation (use <!-- say: -->, <!-- nonarration -->, or <!-- skip -->)",
            source,
            start_index,
        )
        return (
            [
                SlideNarration(
                    index=start_index,
                    image_index=start_image_index,
                    annotation=SlideAnnotation.NONE,
                )
            ],
            n_visual_states,
        )

    # --- Expand says into sub-slides ---
    # Check if any say has an explicit slide target
    has_explicit = any(parse_say_params(p)[0] > 0 for p, _ in say_matches)

    say_commands: list[SayCommand] = []
    for i, (params_str, narration_text) in enumerate(say_matches, start=1):
        clean_narration = narration_text.strip()
        clean_narration = re.sub(r"\s+", " ", clean_narration)
        sub_slide, voice, pace = parse_say_params(params_str)

        if not has_explicit:
            sub_slide = i  # positional: 1, 2, 3, ...
        elif sub_slide == 0:
            sub_slide = 1  # explicit mode default

        say_commands.append(
            SayCommand(sub_slide=sub_slide, text=clean_narration, voice=voice, pace=pace)
        )

    results = expand_sub_slides(
        say_commands,
        n_visual_states,
        start_index,
        start_image_index,
        source,
        label="slide",
        say_syntax="<!-- say: -->",
        nonarration_syntax="<!-- nonarration -->",
    )
    return results, n_visual_states
