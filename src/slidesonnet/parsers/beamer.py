r"""Beamer LaTeX parser: extract \say{} narration and slide images."""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from pathlib import Path

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

# Match \say{text}, \say[params]{text}, \say<overlay>{text}, \say<overlay>[params]{text}.
# Mirrors beamer's \cmd<overlay>[opts]{arg} grammar. Handles nested braces in the
# body via a non-regex approach (see _extract_braced).
_SAY_START_RE = re.compile(r"\\say\s*(?:<([^>]*)>)?\s*(?:\[([^\]]*)\])?\s*\{")

# First integer inside an overlay spec like <2>, <2->, <2-5>, <-3> → the anchor step.
_OVERLAY_INT_RE = re.compile(r"\d+")

# Match \nonarration or \nonarration[duration] on its own line (with optional trailing % comment)
_SILENT_RE = re.compile(r"^\s*\\nonarration\s*(?:\[([^\]]*)\])?\s*(?:%.*)?$", re.MULTILINE)

# Match \slidesonnetskip
_SKIP_RE = re.compile(r"\\slidesonnetskip\b")


def strip_annotations(text: str) -> str:
    r"""Remove slideSonnet annotations (\say, \nonarration, \slidesonnetskip) from Beamer source."""
    # Strip \say[...]{...} using brace-counting
    result = text
    while True:
        match = _SAY_START_RE.search(result)
        if not match:
            break
        brace_start = match.end() - 1
        _, end_pos = _extract_braced(result, brace_start)
        if end_pos == brace_start:
            # Failed to find matching brace; stop to avoid infinite loop
            break
        result = result[: match.start()] + result[end_pos:]
    # Strip \nonarration[...] and \slidesonnetskip
    result = _SILENT_RE.sub("", result)
    result = _SKIP_RE.sub("", result)
    return result


def visual_hash(source_text: str) -> str:
    r"""Return a short hash of Beamer source with annotations stripped.

    Two sources that differ only in \say{} text produce the same hash.
    """
    stripped = strip_annotations(source_text)
    return hashlib.sha256(stripped.encode()).hexdigest()[:16]


# Match \begin{frame} ... \end{frame}
_FRAME_BEGIN_RE = re.compile(r"\\begin\{frame\}")
_FRAME_END_RE = re.compile(r"\\end\{frame\}")

# Match \pause command
_PAUSE_RE = re.compile(r"\\pause\b")

# Strip common LaTeX markup from narration text
_LATEX_CMD_WITH_ARG_RE = re.compile(r"\\(?:textbf|textit|emph|underline|text)\s*\{")
_LATEX_SIMPLE_RE = re.compile(r"\\[a-zA-Z]+\b\s*")


class BeamerParser(SlideParser):
    def prepare(self, source: Path, build_dir: Path) -> None:
        """Compile the deck (latexmk) so ``parse`` can read page counts from ``.nav``.

        Called before :meth:`parse` by the pipeline. latexmk is incremental, so
        this is a fast no-op when the source is unchanged.
        """
        compile_pdf(source, build_dir)

    def parse(self, source: Path, build_dir: Path) -> list[SlideNarration]:
        text = source.read_text(encoding="utf-8")
        frames = _extract_frames(text)

        # Beamer's .nav (written by prepare()'s compile) gives the exact number of
        # overlay pages per frame — counting \pause, \onslide<>, \item<>, etc.
        nav_path = build_dir / f"{source.stem}.nav"
        frame_pages = read_frame_pages(nav_path)
        if frame_pages and len(frame_pages) != len(frames):
            logger.warning(
                "%s: .nav lists %d frames but source has %d \\begin{frame} blocks; "
                "falling back to \\pause counting where they disagree",
                source,
                len(frame_pages),
                len(frames),
            )

        slides: list[SlideNarration] = []
        next_index = 1
        next_image_index = 1

        for i, frame_text in enumerate(frames):
            if i < len(frame_pages):
                first_page, last_page = frame_pages[i]
                n_visual_states = last_page - first_page + 1
                start_image_index = first_page
            else:
                # No .nav (uncompiled) or mismatch: fall back to counting \pause.
                n_visual_states = _count_pauses(frame_text) + 1
                start_image_index = next_image_index

            frame_slides, used_states = _parse_frame(
                next_index, frame_text, source, start_image_index, n_visual_states
            )
            slides.extend(frame_slides)
            next_index += len(frame_slides)
            next_image_index = start_image_index + used_states

        return slides


def compile_pdf(source: Path, output_dir: Path) -> Path:
    r"""Compile Beamer source to PDF with latexmk.

    latexmk runs the LaTeX engine as many times as needed for cross-references,
    the table of contents, and — crucially for slideSonnet — the ``.nav`` file
    to converge, so the per-frame page counts we read back from ``.nav`` always
    match the final PDF. ``-outdir``/``-auxdir`` force the PDF *and* all aux
    files (including ``.nav``) into *output_dir*, overriding any ``$out_dir`` /
    ``$aux_dir`` set by a deck's own ``.latexmkrc`` (which latexmk still reads,
    so author build customizations like shell-escape or biber keep working).

    Returns the path to the compiled PDF.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = output_dir / f"{source.stem}.pdf"
    cmd = [
        "latexmk",
        "-pdf",
        "-interaction=nonstopmode",
        f"-outdir={output_dir}",
        f"-auxdir={output_dir}",
        str(source),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=source.parent)
    except FileNotFoundError:
        raise ParserError("'latexmk' not found. Install TeX Live (it bundles latexmk).")

    if result.returncode != 0:
        # latexmk returns non-zero for genuine failures; surface the log tail.
        if not pdf_path.exists():
            log_tail = (result.stdout or "")[-2000:] + (result.stderr or "")[-2000:]
            raise ParserError(f"latexmk failed and no PDF was produced.\n{log_tail}")
        logger.warning(
            "latexmk exited with code %d (continuing, PDF exists):\n%s",
            result.returncode,
            (result.stderr or "")[-2000:],
        )

    return pdf_path


# Match \beamer@framepages{first}{last} entries in beamer's .nav file.
_FRAMEPAGES_RE = re.compile(r"\\beamer@framepages\s*\{(\d+)\}\s*\{(\d+)\}")


def read_frame_pages(nav_path: Path) -> list[tuple[int, int]]:
    r"""Read beamer's per-frame page ranges from a ``.nav`` file.

    Beamer writes one ``\beamer@framepages{first}{last}`` per frame, in frame
    order, giving the global PDF page range that frame's overlays expand to.
    This is beamer's *own* overlay arithmetic, so it accounts for ``\pause``,
    ``\onslide<...>``, ``\item<...>``, ``+``/``.`` specs — everything.

    Returns a list of ``(first_page, last_page)`` tuples, or an empty list if
    the file is absent (e.g. the deck hasn't been compiled yet).
    """
    if not nav_path.exists():
        return []
    text = nav_path.read_text(encoding="utf-8")
    return [(int(first), int(last)) for first, last in _FRAMEPAGES_RE.findall(text)]


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


def _count_pauses(text: str) -> int:
    """Count \\pause commands in frame text."""
    return len(_PAUSE_RE.findall(text))


def _parse_frame(
    start_index: int,
    text: str,
    source: Path,
    start_image_index: int = 1,
    n_visual_states: int | None = None,
) -> tuple[list[SlideNarration], int]:
    r"""Parse narration annotations from a single frame.

    Returns a tuple of (slides, n_visual_states).  ``n_visual_states`` is the
    number of PDF pages this frame produces. It is normally supplied by the
    caller from beamer's ``.nav`` (which accounts for every overlay mechanism);
    when omitted it falls back to counting ``\pause`` commands (``1 + n_pauses``).
    """
    if n_visual_states is None:
        n_visual_states = _count_pauses(text) + 1
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
        silence_override = parse_silence_duration(
            silent_match.group(1), source, start_index, label="frame"
        )
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

    # Parse all \say commands with their overlay-step targets
    say_commands: list[SayCommand] = []
    for overlay, params_str, body_text in say_matches:
        clean_text = _strip_latex(body_text).strip()
        clean_text = re.sub(r"\s+", " ", clean_text)
        sub_slide, voice, pace = _resolve_say_step(overlay, params_str, source, start_index)
        say_commands.append(
            SayCommand(sub_slide=sub_slide, text=clean_text, voice=voice, pace=pace)
        )

    # Warn if any \say targets beyond the frame's overlay-step count
    max_target = max(cmd.sub_slide for cmd in say_commands)
    if max_target > n_sub:
        logger.warning(
            "%s frame %d: \\say targets step %d but frame has only %d overlay step(s); "
            "extending to %d",
            source,
            start_index,
            max_target,
            n_sub,
            max_target,
        )

    results = expand_sub_slides(
        say_commands,
        n_visual_states,
        start_index,
        start_image_index,
        source,
        label="frame",
        say_syntax="\\say{}",
        nonarration_syntax="\\nonarration",
    )
    return results, n_visual_states


def _find_say_commands(text: str) -> list[tuple[str | None, str, str]]:
    r"""Find all \\say commands and extract their overlay spec, params, and body.

    Uses brace counting to handle nested braces in the body.
    Returns a list of ``(overlay_spec, params_string, body_text)`` tuples, where
    ``overlay_spec`` is the text between ``<`` and ``>`` (``None`` if absent).
    """
    results: list[tuple[str | None, str, str]] = []
    pos = 0
    while True:
        match = _SAY_START_RE.search(text, pos)
        if not match:
            break

        overlay = match.group(1)  # None if no <...> present
        params = match.group(2) or ""
        # Now find the matching closing brace
        brace_start = match.end() - 1  # position of the opening {
        body, end_pos = _extract_braced(text, brace_start)
        if body is not None:
            results.append((overlay, params, body))
            pos = end_pos
        else:
            pos = match.end()

    return results


def _resolve_say_step(
    overlay: str | None,
    params_str: str,
    source: Path,
    frame_index: int,
) -> tuple[int, str | None, str | None]:
    r"""Resolve the overlay step a \\say targets, plus its voice/pace.

    The step comes solely from the beamer-style overlay spec ``\say<N>`` (the
    first integer in the spec). Bracket options carry only ``voice``/``pace``;
    a step number in brackets (``\say[N]`` / ``\say[slide=N]``) is rejected, as
    is a \\say with no overlay step — every \\say must be written ``\say<N>{}``.
    """
    bracket_step, voice, pace = parse_say_params(params_str, default_sub_slide=0)

    if bracket_step:
        raise ParserError(
            f"{source} frame {frame_index}: a \\say step number goes in <>, not [] — "
            f"write \\say<{bracket_step}>[options]{{...}}, not \\say[{bracket_step}]{{...}}."
        )

    if overlay is None:
        raise ParserError(
            f"{source} frame {frame_index}: \\say needs an overlay step — write "
            f"\\say<N>{{...}} (e.g. \\say<1>{{...}}). A bare \\say{{...}} is not allowed."
        )

    int_match = _OVERLAY_INT_RE.search(overlay)
    if int_match is None:
        raise ParserError(
            f"{source} frame {frame_index}: unsupported \\say overlay spec "
            f"'<{overlay}>' — use a number, e.g. \\say<2>{{...}}"
        )

    return int(int_match.group()), voice, pace


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
