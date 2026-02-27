"""MARP markdown parser: extract slide images and narration directives."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

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

# Fragment list markers (Marp animated items)
_FRAGMENT_UL_RE = re.compile(r"^\s*\*\s", re.MULTILINE)
_FRAGMENT_OL_RE = re.compile(r"^\s*\d+\)\s", re.MULTILINE)


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
    """Run marp CLI to extract slide images as PNGs.

    Expands fragmented slides (those with multiple say directives) into
    separate sub-slides before rendering, so each sub-slide gets its own image.

    Returns list of generated image paths in slide order.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Expand fragmented slides for image extraction
    text = source.read_text(encoding="utf-8")
    expanded = _expand_for_images(text)

    # Use expanded file if expansion changed anything
    if expanded != text:
        expanded_source = output_dir / f"_{source.stem}_expanded.md"
        expanded_source.write_text(expanded, encoding="utf-8")
        effective_source = expanded_source
    else:
        effective_source = source

    # marp --output treats the path as a file prefix, so we use
    # output_dir/source_stem to get files like output_dir/slides.001, etc.
    output_prefix = output_dir / source.stem

    cmd = [
        "marp",
        "--no-stdin",
        str(effective_source),
        "--images",
        "png",
        "--output",
        str(output_prefix),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise ParserError("'marp' not found. Install with: npm install -g @marp-team/marp-cli")
    except subprocess.CalledProcessError as e:
        raise ParserError(f"marp failed:\n{e.stderr}")

    # Clean up temp file
    if expanded != text and expanded_source.exists():
        expanded_source.unlink()

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


def _count_says(text: str) -> int:
    """Count ``<!-- say -->`` directives outside fenced code blocks."""
    clean = _FENCE_RE.sub("", text)
    return len(_SAY_RE.findall(clean))


def _count_fragments(text: str) -> int:
    """Count fragment list items (``*`` and ``N)``) outside fenced code blocks."""
    clean = _FENCE_RE.sub("", text)
    return len(_FRAGMENT_UL_RE.findall(clean)) + len(_FRAGMENT_OL_RE.findall(clean))


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


# ---- Image expansion for fragment animation ----


def _split_with_frontmatter(text: str) -> tuple[str, list[str]]:
    """Split MARP markdown into front matter string and list of slide texts.

    Returns (front_matter_text, [slide_text, ...]).
    """
    lines = text.split("\n")
    separator_indices = _find_separator_indices(lines)

    if len(separator_indices) < 2:
        return text, []

    fm_close = separator_indices[1]
    front_matter = "\n".join(lines[: fm_close + 1])
    slide_separators = separator_indices[2:]
    slides: list[str] = []

    if not slide_separators:
        content = "\n".join(lines[fm_close + 1 :])
        if content.strip():
            slides.append(content)
        return front_matter, slides

    # First slide
    slides.append("\n".join(lines[fm_close + 1 : slide_separators[0]]))

    # Middle slides
    for j in range(len(slide_separators) - 1):
        start = slide_separators[j] + 1
        end = slide_separators[j + 1]
        slides.append("\n".join(lines[start:end]))

    # Last slide
    last_content = "\n".join(lines[slide_separators[-1] + 1 :])
    if last_content.strip():
        slides.append(last_content)

    return front_matter, slides


def _convert_fragment_marker(line: str, *, visible: bool = True) -> str:
    """Convert a fragment list marker to a regular marker.

    ``* item`` → ``- item``, ``N) item`` → ``N. item``

    When *visible* is False, the item text is wrapped in a hidden ``<span>``
    so it occupies space but is invisible — this prevents MARP's vertical
    centering from shifting the list as items are revealed.
    """
    converted = re.sub(r"^(\s*)\*(\s)", r"\1-\2", line)
    converted = re.sub(r"^(\s*)(\d+)\)(\s)", r"\1\2.\3", converted)
    if not visible:
        # Wrap the text portion (everything after "- " or "N. ") in a hidden span.
        converted = re.sub(
            r"^(\s*(?:-|\d+\.)\s+)(.*)",
            r'\1<span style="visibility:hidden">\2</span>',
            converted,
        )
    return converted


def _expand_slide(raw_text: str, n_sub: int) -> list[str]:
    """Produce *n_sub* copies of a slide with progressive fragment reveal.

    Fragment items (``*`` / ``N)``) are revealed incrementally: sub-slide k
    shows items 1..min(k, total_fragments) with markers converted to ``-``/``N.``.
    Hidden items are rendered as invisible placeholders to preserve vertical
    spacing.  ``<!-- say -->`` directives are stripped.  Non-fragment content
    appears on every sub-slide.
    """
    # Remove say directives (they span the full match, possibly multi-line)
    clean_text = _SAY_RE.sub("", raw_text)

    lines = clean_text.split("\n")
    in_fence = False
    fragment_line_map: dict[int, int] = {}  # line_index -> fragment_number
    frag_count = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_char = stripped[:3]
            if in_fence:
                if stripped.rstrip(fence_char[0]) == "":
                    in_fence = False
            else:
                in_fence = True
            continue
        if in_fence:
            continue
        if re.match(r"\s*\*\s", line) or re.match(r"\s*\d+\)\s", line):
            frag_count += 1
            fragment_line_map[i] = frag_count

    n_fragments = frag_count

    sub_slides: list[str] = []
    for k in range(1, n_sub + 1):
        visible_up_to = min(k, n_fragments)
        sub_lines: list[str] = []
        for i, line in enumerate(lines):
            if i in fragment_line_map:
                is_visible = fragment_line_map[i] <= visible_up_to
                sub_lines.append(_convert_fragment_marker(line, visible=is_visible))
            else:
                sub_lines.append(line)
        sub_slides.append("\n".join(sub_lines))

    return sub_slides


def _expand_for_images(text: str) -> str:
    """Expand fragmented slides (multiple says) into separate sub-slides.

    Returns the full markdown with front matter preserved and fragmented
    slides replaced by their expanded sub-slide copies.
    """
    front_matter, slide_texts = _split_with_frontmatter(text)

    if not slide_texts:
        return text

    expanded_slides: list[str] = []
    any_expanded = False
    for slide_text in slide_texts:
        n_says = _count_says(slide_text)
        if n_says > 1:
            sub_slides = _expand_slide(slide_text, n_says)
            expanded_slides.extend(sub_slides)
            any_expanded = True
        else:
            expanded_slides.append(slide_text)

    if not any_expanded:
        return text

    # Reassemble: front matter + first slide, then remaining slides with --- separators
    # Slide texts already start with their original leading whitespace (e.g. "\n# Title")
    parts = [front_matter, expanded_slides[0]]
    for slide in expanded_slides[1:]:
        parts.append("\n---" + slide)

    return "".join(parts)
