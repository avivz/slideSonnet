r"""Beamer LaTeX parser: extract \say{} narration and slide images."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from slidesonnet.models import SlideAnnotation, SlideNarration
from slidesonnet.parsers.base import SlideParser

# Match \say{text} or \say[params]{text}
# Handles nested braces via a non-regex approach for the body
_SAY_START_RE = re.compile(r"\\say\s*(?:\[([^\]]*)\])?\s*\{")

# Match \silent
_SILENT_RE = re.compile(r"\\silent\b")

# Match \skip or \slidesonnetskip
_SKIP_RE = re.compile(r"\\(?:slidesonnetskip|skip)\b")

# Match \begin{frame} ... \end{frame}
_FRAME_BEGIN_RE = re.compile(r"\\begin\{frame\}")
_FRAME_END_RE = re.compile(r"\\end\{frame\}")

# Parse key=value from optional args
_PARAM_RE = re.compile(r"(\w+)\s*=\s*(\w+)")

# Strip common LaTeX markup from narration text
_LATEX_CMD_RE = re.compile(r"\\(?:textbf|textit|emph|underline|text)\{([^}]*)\}")
_LATEX_SIMPLE_RE = re.compile(r"\\[a-zA-Z]+\b\s*")


class BeamerParser(SlideParser):
    def parse(self, source: Path, build_dir: Path) -> list[SlideNarration]:
        text = source.read_text(encoding="utf-8")
        frames = _extract_frames(text)
        slides = []

        for i, frame_text in enumerate(frames, start=1):
            slide = _parse_frame(i, frame_text, source)
            slides.append(slide)

        return slides


def extract_images(source: Path, output_dir: Path) -> list[Path]:
    """Compile Beamer to PDF, then extract slide images with pdftoppm.

    Returns list of PNG paths in slide order.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Compile with pdflatex
    pdf_path = output_dir / f"{source.stem}.pdf"
    cmd_latex = [
        "pdflatex",
        "-interaction=nonstopmode",
        f"-output-directory={output_dir}",
        str(source),
    ]
    try:
        subprocess.run(cmd_latex, check=True, capture_output=True, text=True, cwd=source.parent)
    except FileNotFoundError:
        print("ERROR: 'pdflatex' not found. Install TeX Live.", file=sys.stderr)
        raise SystemExit(1)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: pdflatex failed:\n{e.stdout[-500:]}", file=sys.stderr)
        raise SystemExit(1)

    # Extract images with pdftoppm
    prefix = str(output_dir / "slide")
    cmd_ppm = ["pdftoppm", "-png", "-r", "300", str(pdf_path), prefix]
    try:
        subprocess.run(cmd_ppm, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        print(
            "ERROR: 'pdftoppm' not found. Install poppler-utils.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: pdftoppm failed:\n{e.stderr}", file=sys.stderr)
        raise SystemExit(1)

    images = sorted(output_dir.glob("slide-*.png"))
    return images


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


def _parse_frame(index: int, text: str, source: Path) -> SlideNarration:
    """Parse narration annotations from a single frame."""

    # Check for \skip
    if _SKIP_RE.search(text):
        return SlideNarration(index=index, annotation=SlideAnnotation.SKIP)

    # Check for \silent
    if _SILENT_RE.search(text):
        return SlideNarration(index=index, annotation=SlideAnnotation.SILENT)

    # Check for \say{...}
    say_matches = _find_say_commands(text)
    if say_matches:
        narration_parts = []
        voice = None
        pace = None

        for params_str, body_text in say_matches:
            clean_text = _strip_latex(body_text).strip()
            clean_text = re.sub(r"\s+", " ", clean_text)
            narration_parts.append(clean_text)

            if params_str:
                params = dict(_PARAM_RE.findall(params_str))
                if "voice" in params:
                    voice = params["voice"]
                if "pace" in params:
                    pace = params["pace"]

        full_narration = " ".join(narration_parts)

        if not full_narration:
            print(
                f"WARNING: {source} frame {index}: empty \\say{{}} "
                f"— did you mean \\silent?",
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

    # No annotation
    print(
        f"WARNING: {source} frame {index}: no annotation "
        f"(use \\say{{}}, \\silent, or \\skip)",
        file=sys.stderr,
    )
    return SlideNarration(index=index, annotation=SlideAnnotation.NONE)


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
    """
    if start >= len(text) or text[start] != "{":
        return None, start

    depth = 0
    i = start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1

    return None, start


def _strip_latex(text: str) -> str:
    """Strip common LaTeX formatting commands from text for TTS."""
    # Replace \textbf{word} → word, etc.
    result = _LATEX_CMD_RE.sub(r"\1", text)
    # Remove remaining simple commands like \item, \newline, etc.
    result = _LATEX_SIMPLE_RE.sub(" ", result)
    # Clean up
    result = result.replace("~", " ").replace("\\\\", " ")
    return result
