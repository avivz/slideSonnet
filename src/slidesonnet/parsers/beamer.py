r"""Beamer LaTeX parser: extract \say{} narration and slide images."""

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

# Match \say{text} or \say[params]{text}
# Handles nested braces via a non-regex approach for the body
_SAY_START_RE = re.compile(r"\\say\s*(?:\[([^\]]*)\])?\s*\{")

# Match \nonarration or \nonarration[duration] on its own line (with optional trailing % comment)
_SILENT_RE = re.compile(r"^\s*\\nonarration\s*(?:\[([^\]]*)\])?\s*(?:%.*)?$", re.MULTILINE)

# Match \slidesonnetskip
_SKIP_RE = re.compile(r"\\slidesonnetskip\b")

# Match \begin{frame} ... \end{frame}
_FRAME_BEGIN_RE = re.compile(r"\\begin\{frame\}")
_FRAME_END_RE = re.compile(r"\\end\{frame\}")

# Match \pause command
_PAUSE_RE = re.compile(r"\\pause\b")

# Parse key=value from optional args
_PARAM_RE = re.compile(r"(\w+)\s*=\s*([\w.\-]+)")

# Strip common LaTeX markup from narration text
_LATEX_CMD_WITH_ARG_RE = re.compile(r"\\(?:textbf|textit|emph|underline|text)\s*\{")
_LATEX_SIMPLE_RE = re.compile(r"\\[a-zA-Z]+\b\s*")


class BeamerParser(SlideParser):
    def parse(self, source: Path, build_dir: Path) -> list[SlideNarration]:
        text = source.read_text(encoding="utf-8")
        frames = _extract_frames(text)
        slides: list[SlideNarration] = []
        next_index = 1
        next_image_index = 1

        for frame_text in frames:
            frame_slides, n_visual_states = _parse_frame(
                next_index, frame_text, source, next_image_index
            )
            slides.extend(frame_slides)
            next_index += len(frame_slides)
            next_image_index += n_visual_states

        return slides


def compile_pdf(source: Path, output_dir: Path) -> Path:
    """Compile Beamer source to PDF with pdflatex.

    Returns the path to the compiled PDF.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = output_dir / f"{source.stem}.pdf"
    cmd_latex = [
        "pdflatex",
        "-interaction=nonstopmode",
        f"-output-directory={output_dir}",
        str(source),
    ]
    # Run pdflatex twice so cross-references, TOC, and bibliography resolve.
    for pass_num in range(1, 3):
        try:
            subprocess.run(cmd_latex, check=True, capture_output=True, text=True, cwd=source.parent)
        except FileNotFoundError:
            raise ParserError("'pdflatex' not found. Install TeX Live.")
        except subprocess.CalledProcessError as e:
            # pdflatex often returns non-zero for warnings; check if PDF was produced
            if not pdf_path.exists():
                raise ParserError(f"pdflatex failed and no PDF was produced.\n{e.stderr}")
            logger.warning(
                "pdflatex pass %d exited with errors (continuing):\n%s", pass_num, e.stderr
            )

    return pdf_path


def extract_images_from_pdf(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Extract slide images from a PDF with pdftoppm.

    Returns list of PNG paths in slide order.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    prefix = str(output_dir / "slide")
    cmd_ppm = ["pdftoppm", "-png", "-r", "300", str(pdf_path), prefix]
    try:
        subprocess.run(cmd_ppm, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise ParserError("'pdftoppm' not found. Install poppler-utils.")
    except subprocess.CalledProcessError as e:
        raise ParserError(f"pdftoppm failed:\n{e.stderr}")

    images = sorted(output_dir.glob("slide-*.png"))
    return images


def extract_images(source: Path, output_dir: Path) -> list[Path]:
    """Compile Beamer to PDF, then extract slide images with pdftoppm.

    Returns list of PNG paths in slide order.
    """
    pdf_path = compile_pdf(source, output_dir)
    return extract_images_from_pdf(pdf_path, output_dir)


def _extract_frames(text: str) -> list[str]:
    """Extract the content of each \\begin{frame}...\\end{frame} block."""
    frames = []
    pos = 0
    while True:
        begin = _FRAME_BEGIN_RE.search(text, pos)
        if not begin:
            break
        end = _FRAME_END_RE.search(text, begin.end())
        if not end:
            break
        frames.append(text[begin.end() : end.start()])
        pos = end.end()
    return frames


@dataclass
class _SayCommand:
    """Parsed data from a single \\say command."""

    sub_slide: int  # 1-based sub-slide target
    text: str
    voice: str | None
    pace: str | None


def _parse_say_params(params_str: str) -> tuple[int, str | None, str | None]:
    """Parse the optional bracket params of a \\say command.

    Supports:
      - ``\\say{text}``          → sub_slide=1
      - ``\\say[2]{text}``       → sub_slide=2 (bare number)
      - ``\\say[slide=2]{text}`` → sub_slide=2 (explicit key)
      - ``\\say[2, voice=alice]{text}`` → sub_slide=2, voice=alice

    Returns (sub_slide, voice, pace).
    """
    sub_slide = 1
    voice: str | None = None
    pace: str | None = None

    if not params_str:
        return sub_slide, voice, pace

    kv_params = dict(_PARAM_RE.findall(params_str))

    # Check for bare number: strip key=value pairs to see if a standalone number remains
    stripped = _PARAM_RE.sub("", params_str)
    # Remove commas and whitespace
    stripped = stripped.replace(",", "").strip()
    if stripped.isdigit():
        sub_slide = int(stripped)

    if "slide" in kv_params:
        sub_slide = int(kv_params["slide"])
    if "voice" in kv_params:
        voice = kv_params["voice"]
    if "pace" in kv_params:
        pace = kv_params["pace"]

    return sub_slide, voice, pace


def _count_pauses(text: str) -> int:
    """Count \\pause commands in frame text."""
    return len(_PAUSE_RE.findall(text))


def _parse_silence_duration(raw: str | None, source: Path, index: int) -> float | None:
    """Parse an optional silence duration string into a float.

    Returns None if *raw* is None or empty (no override).
    Raises ParserError for invalid or negative values.
    """
    if raw is None or raw.strip() == "":
        return None
    raw = raw.strip()
    try:
        value = float(raw)
    except ValueError:
        raise ParserError(
            f"{source} frame {index}: invalid nonarration duration '{raw}' "
            f"(expected a non-negative number)"
        )
    if value < 0:
        raise ParserError(
            f"{source} frame {index}: nonarration duration must be non-negative, got {value}"
        )
    return value


def _parse_frame(
    start_index: int, text: str, source: Path, start_image_index: int = 1
) -> tuple[list[SlideNarration], int]:
    """Parse narration annotations from a single frame.

    Returns a tuple of (slides, n_visual_states).  ``n_visual_states`` is
    the number of PDF pages this frame produces (``1 + n_pauses``), used
    to advance the image index counter.

    Frames with ``\\pause`` produce multiple sub-slides.
    """
    n_pauses = _count_pauses(text)
    n_visual_states = n_pauses + 1
    n_sub = n_visual_states

    # Check for \slidesonnetskip — applies to all sub-slides
    if _SKIP_RE.search(text):
        return (
            [
                SlideNarration(
                    index=start_index + i,
                    image_index=start_image_index + i,
                    annotation=SlideAnnotation.SKIP,
                )
                for i in range(n_sub)
            ],
            n_visual_states,
        )

    # Check for \nonarration (without any \say) — applies to all sub-slides
    say_matches = _find_say_commands(text)
    silent_match = _SILENT_RE.search(text)
    if silent_match and not say_matches:
        silence_override = _parse_silence_duration(silent_match.group(1), source, start_index)
        return (
            [
                SlideNarration(
                    index=start_index + i,
                    image_index=start_image_index + i,
                    annotation=SlideAnnotation.SILENT,
                    silence_override=silence_override,
                )
                for i in range(n_sub)
            ],
            n_visual_states,
        )

    if not say_matches:
        # No annotation at all
        logger.warning(
            "%s frame %d: no annotation (use \\say{}, \\nonarration, or \\slidesonnetskip)",
            source,
            start_index,
        )
        return (
            [
                SlideNarration(
                    index=start_index + i,
                    image_index=start_image_index + i,
                    annotation=SlideAnnotation.NONE,
                )
                for i in range(n_sub)
            ],
            n_visual_states,
        )

    # Parse all \say commands with their sub-slide targets
    say_commands: list[_SayCommand] = []
    for params_str, body_text in say_matches:
        clean_text = _strip_latex(body_text).strip()
        clean_text = re.sub(r"\s+", " ", clean_text)
        sub_slide, voice, pace = _parse_say_params(params_str)
        say_commands.append(
            _SayCommand(sub_slide=sub_slide, text=clean_text, voice=voice, pace=pace)
        )

    # Extend n_sub if any \say targets beyond pause count
    max_target = max(cmd.sub_slide for cmd in say_commands)
    if max_target > n_sub:
        logger.warning(
            "%s frame %d: \\say targets sub-slide %d but frame has only %d sub-slides "
            "(%d \\pause commands); extending to %d",
            source,
            start_index,
            max_target,
            n_sub,
            n_pauses,
            max_target,
        )
        n_sub = max_target

    # Group \say commands by target sub-slide
    results: list[SlideNarration] = []
    for sub_idx in range(1, n_sub + 1):
        group = [cmd for cmd in say_commands if cmd.sub_slide == sub_idx]
        slide_index = start_index + sub_idx - 1
        img_idx = start_image_index + min(sub_idx - 1, n_visual_states - 1)

        if not group:
            # No narration for this sub-slide
            if n_sub > 1:
                logger.warning(
                    "%s frame %d, sub-slide %d: no narration — treating as silent",
                    source,
                    start_index,
                    sub_idx,
                )
            results.append(
                SlideNarration(
                    index=slide_index, image_index=img_idx, annotation=SlideAnnotation.SILENT
                )
            )
            continue

        narration_parts = [cmd.text for cmd in group]
        full_narration = " ".join(narration_parts)

        # Use the last specified voice/pace (matching original behavior for multiple \say)
        group_voice: str | None = None
        group_pace: str | None = None
        for cmd in group:
            if cmd.voice is not None:
                group_voice = cmd.voice
            if cmd.pace is not None:
                group_pace = cmd.pace

        if not full_narration:
            logger.warning(
                "%s frame %d: empty \\say{} — did you mean \\nonarration?",
                source,
                start_index,
            )
            results.append(
                SlideNarration(
                    index=slide_index, image_index=img_idx, annotation=SlideAnnotation.SILENT
                )
            )
            continue

        results.append(
            SlideNarration(
                index=slide_index,
                image_index=img_idx,
                annotation=SlideAnnotation.SAY,
                narration_raw=full_narration,
                narration_parts=narration_parts,
                voice=group_voice,
                pace=group_pace,
            )
        )

    return results, n_visual_states


def _find_say_commands(text: str) -> list[tuple[str, str]]:
    """Find all \\say commands and extract their optional params and body.

    Uses brace counting to handle nested braces in the body.
    Returns list of (params_string, body_text) tuples.
    """
    results = []
    pos = 0
    while True:
        match = _SAY_START_RE.search(text, pos)
        if not match:
            break

        params = match.group(1) or ""
        # Now find the matching closing brace
        brace_start = match.end() - 1  # position of the opening {
        body, end_pos = _extract_braced(text, brace_start)
        if body is not None:
            results.append((params, body))
            pos = end_pos
        else:
            pos = match.end()

    return results


def _extract_braced(text: str, start: int) -> tuple[str | None, int]:
    """Extract content between matched braces starting at text[start] == '{'.

    Returns (content, position_after_closing_brace) or (None, start) on failure.
    Escaped braces (``\\{`` and ``\\}``) are ignored by the brace counter.
    LaTeX ``%`` line comments are skipped so that braces inside comments
    do not affect the depth count (``\\%`` is treated as a literal percent).
    """
    if start >= len(text) or text[start] != "{":
        return None, start

    depth = 0
    i = start
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            i += 2  # skip escaped character
            continue
        if text[i] == "%":
            newline = text.find("\n", i)
            i = newline if newline != -1 else len(text)
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1

    return None, start


def _strip_latex(text: str) -> str:
    """Strip common LaTeX formatting commands from text for TTS.

    Handles nested commands like ``\\textbf{This has \\emph{nested} markup}``
    by using brace-counting instead of a flat regex.
    """
    result = text
    # Iteratively replace \textbf{...}, \emph{...}, etc. with their content,
    # handling arbitrary nesting depth.
    changed = True
    while changed:
        changed = False
        match = _LATEX_CMD_WITH_ARG_RE.search(result)
        if match:
            brace_start = match.end() - 1  # position of the opening {
            body, end_pos = _extract_braced(result, brace_start)
            if body is not None:
                result = result[: match.start()] + body + result[end_pos:]
                changed = True
    # Remove remaining simple commands like \item, \newline, etc.
    result = _LATEX_SIMPLE_RE.sub(" ", result)
    # Clean up
    result = result.replace("~", " ").replace("\\\\", " ")
    return result
