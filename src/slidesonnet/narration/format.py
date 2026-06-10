"""Parse and serialize the narration sidecar grammar.

The sidecar is a flat, line-oriented, git-diffable text file:

    # a comment (line-leading '#', or a trailing ' #...' on a content line)
    @slide-id            block header
    :voice narrator      optional per-block directive
    :pace slow           optional per-block directive
    Spoken text. [pause 1.5] More spoken text.   narration body

``[pause <seconds>]`` is the single timing primitive (mid-pause, end-hold, or a
silent slide whose only content is a pause). Body lines within a block are
joined with single spaces; the parse <-> serialize round-trip is stable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from slidesonnet.narration.model import Pace, PageNarration, Segment

_HEADER_RE = re.compile(r"^@(?P<id>\S+)\s*$")
_DIRECTIVE_RE = re.compile(r"^:(?P<key>voice|pace)\s+(?P<value>.+?)\s*$")
_PAUSE_RE = re.compile(r"\[pause\s+(?P<sec>[0-9]*\.?[0-9]+)\]")
_WS_RE = re.compile(r"\s+")
_VALID_PACES: frozenset[str] = frozenset({"slow", "normal", "fast"})


class SidecarError(ValueError):
    """The sidecar text is malformed."""


def _strip_comment(line: str) -> str:
    """Remove a comment from *line*.

    A line whose first non-space char is ``#`` is entirely a comment. Otherwise
    an inline comment beginning at a whitespace-preceded ``#`` is removed.
    """
    if line.lstrip().startswith("#"):
        return ""
    m = re.search(r"\s#", line)
    if m:
        return line[: m.start()]
    return line


def _format_seconds(seconds: float) -> str:
    """Render *seconds* without trailing zeros (3.0 -> '3', 1.50 -> '1.5')."""
    if seconds == int(seconds):
        return str(int(seconds))
    return f"{seconds:g}"


def parse_segments(body: str) -> list[Segment]:
    """Split a block *body* string into ordered speech/pause segments."""
    segments: list[Segment] = []
    pos = 0
    for m in _PAUSE_RE.finditer(body):
        speech = body[pos : m.start()].strip()
        if speech:
            segments.append(Segment.speech(_WS_RE.sub(" ", speech)))
        segments.append(Segment.pause(float(m.group("sec"))))
        pos = m.end()
    tail = body[pos:].strip()
    if tail:
        segments.append(Segment.speech(_WS_RE.sub(" ", tail)))
    return segments


def parse_sidecar(text: str) -> list[PageNarration]:
    """Parse sidecar *text* into a list of blocks in file order.

    Raises :class:`SidecarError` on a directive or body appearing before the
    first ``@`` header.
    """
    blocks: list[PageNarration] = []
    current: PageNarration | None = None
    body_lines: list[str] = []

    def _flush() -> None:
        nonlocal current
        if current is not None:
            current.segments = parse_segments(" ".join(body_lines))
            blocks.append(current)
        body_lines.clear()

    for raw_lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue

        header = _HEADER_RE.match(line)
        if header:
            _flush()
            current = PageNarration(slide_id=header.group("id"))
            continue

        directive = _DIRECTIVE_RE.match(line)
        if directive:
            if current is None:
                raise SidecarError(
                    f"line {raw_lineno}: directive '{line.strip()}' before any @slide-id header"
                )
            key, value = directive.group("key"), directive.group("value").strip()
            if key == "voice":
                current.voice = value
            else:  # pace
                if value not in _VALID_PACES:
                    raise SidecarError(
                        f"line {raw_lineno}: invalid pace '{value}' "
                        f"(expected one of {sorted(_VALID_PACES)})"
                    )
                current.pace = value  # type: ignore[assignment]
            continue

        if current is None:
            raise SidecarError(
                f"line {raw_lineno}: narration text '{line.strip()}' before any @slide-id header"
            )
        body_lines.append(line.strip())

    _flush()
    return blocks


def serialize_block(block: PageNarration) -> str:
    """Serialize a single block to canonical sidecar text (no trailing newline)."""
    lines: list[str] = [f"@{block.slide_id}"]
    if block.voice:
        lines.append(f":voice {block.voice}")
    if block.pace:
        lines.append(f":pace {block.pace}")

    parts: list[str] = []
    for seg in block.segments:
        if seg.is_pause:
            parts.append(f"[pause {_format_seconds(seg.seconds)}]")
        elif seg.text.strip():
            parts.append(seg.text.strip())
    body = " ".join(parts)
    if body:
        lines.append(body)
    return "\n".join(lines)


def serialize_sidecar(
    blocks: Iterable[PageNarration],
    *,
    header: str | None = None,
) -> str:
    """Serialize blocks to a sidecar document (trailing newline included)."""
    chunks: list[str] = []
    if header:
        chunks.append("\n".join(f"# {ln}" if ln else "#" for ln in header.splitlines()))
    for block in blocks:
        chunks.append(serialize_block(block))
    return "\n\n".join(chunks) + "\n"


def pace_to_speed(pace: Pace | None) -> float:
    """Map a pace directive to a TTS speed multiplier (1.0 = normal)."""
    return {"slow": 0.85, "normal": 1.0, "fast": 1.15}.get(pace or "normal", 1.0)
