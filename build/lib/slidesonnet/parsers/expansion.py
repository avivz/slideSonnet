"""Shared sub-slide expansion logic for MARP and Beamer parsers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from slidesonnet.exceptions import ParserError
from slidesonnet.models import SlideAnnotation, SlideNarration

logger = logging.getLogger(__name__)

# Parse key=value pairs from say(...) / say[...] params
_PARAM_RE = re.compile(r"(\w+)\s*=\s*([\w.\-]+)")


@dataclass
class SayCommand:
    """Parsed data from a single say directive."""

    sub_slide: int  # 1-based sub-slide target
    text: str
    voice: str | None
    pace: str | None


def parse_say_params(
    params_str: str, *, default_sub_slide: int = 0
) -> tuple[int, str | None, str | None]:
    """Parse optional params from a say directive.

    Supports bare numbers, ``slide=N``, ``voice=NAME``, and ``pace=VALUE``.
    MARP calls with ``default_sub_slide=0`` (unset), Beamer with ``1``.

    Returns (sub_slide, voice, pace).
    """
    sub_slide = default_sub_slide
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


def parse_silence_duration(
    raw: str | None, source: Path, index: int, *, label: str = "slide"
) -> float | None:
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
            f"{source} {label} {index}: invalid nonarration duration '{raw}' "
            f"(expected a non-negative number)"
        )
    if value < 0:
        raise ParserError(
            f"{source} {label} {index}: nonarration duration must be non-negative, got {value}"
        )
    return value


def expand_sub_slides(
    say_commands: list[SayCommand],
    n_visual_states: int,
    start_index: int,
    start_image_index: int,
    source: Path,
    *,
    label: str,
    say_syntax: str,
    nonarration_syntax: str,
) -> list[SlideNarration]:
    """Expand say commands into sub-slide narrations.

    Groups *say_commands* by their sub-slide target, creates one
    ``SlideNarration`` per sub-slide, and returns the list.
    """
    max_target = max(cmd.sub_slide for cmd in say_commands)
    n_sub = max(max_target, n_visual_states)

    results: list[SlideNarration] = []
    for sub_idx in range(1, n_sub + 1):
        group = [cmd for cmd in say_commands if cmd.sub_slide == sub_idx]
        slide_index = start_index + sub_idx - 1
        img_idx = start_image_index + min(sub_idx - 1, n_visual_states - 1)

        if not group:
            if n_sub > 1:
                logger.warning(
                    "%s %s %d, sub-slide %d: no narration — treating as silent",
                    source,
                    label,
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
                "%s %s %d: empty %s — did you mean %s?",
                source,
                label,
                start_index,
                say_syntax,
                nonarration_syntax,
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

    return results
