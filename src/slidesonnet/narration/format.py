"""Parse and serialize the narration sidecar grammar.

The sidecar is an indented, line-oriented, git-diffable text file. Each slide
is a block of attributed utterances and pauses, optionally bracketed by
transitions:

    # a comment (line-leading '#', or a trailing ' #...' on a content line)
    @slide-id
      transition-in: crossfade 0.5     # optional; default is a cut
      utterance:
        voice: narrator                # optional per-utterance directives
        pace: slow
        direct: warm, unhurried
        text: The spoken words.
      pause: 1.5                       # an explicit silence, in seconds
      utterance:
        text: A second utterance, in the default voice.
      transition-out: cut              # optional; default is a cut

Indentation is cosmetic — lines are classified by their leading ``key:`` token
(``utterance:``, ``pause:``, ``transition-in:``, ``transition-out:``, and the
utterance attributes ``voice:``/``pace:``/``direct:``/``text:``). After a
``text:`` line, any line that isn't a known directive continues the text — so
hand-wrapped narration parses (a wrapped line that *starts* with a known
directive word + colon would be read as that directive; start such a line
mid-word instead).

The round-trip is byte-preserving for untouched content: each parsed block
remembers its raw text, and serialization re-emits it verbatim unless the
block's content changed (then that block — and only that block — is rewritten
canonically; comments above it and at end-of-file still survive).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from slidesonnet.narration.model import (
    Pace,
    PageNarration,
    Segment,
    Transition,
    TransitionKind,
)
from slidesonnet.narration.transitions import TRANSITION_NAMES

logger = logging.getLogger(__name__)

# The sidecar grammar version this slidesonnet reads and writes. Declared in
# files as a plain comment (`# slidesonnet-format: N`) so older versions skip
# it harmlessly; a parser seeing a greater N warns that directives introduced
# later may be misread (a future directive after `text:` would otherwise be
# swallowed as a text continuation — and spoken aloud).
FORMAT_VERSION = 1
_FORMAT_RE = re.compile(r"^#\s*slidesonnet-format:\s*(?P<version>\d+)\s*$")

_HEADER_RE = re.compile(r"^@(?P<id>\S+)\s*$")
_KV_RE = re.compile(r"^(?P<key>[a-z][a-z-]*)\s*:\s*(?P<value>.*?)\s*$")
_PAUSE_RE = re.compile(r"\[pause\s+(?P<sec>[0-9]*\.?[0-9]+)\]")
_WS_RE = re.compile(r"\s+")
_VALID_PACES: frozenset[str] = frozenset({"slow", "normal", "fast"})
_VALID_TRANSITIONS: frozenset[str] = TRANSITION_NAMES

_UTTERANCE_ATTRS: frozenset[str] = frozenset({"voice", "pace", "direct", "text"})
_KNOWN_KEYS: frozenset[str] = (
    frozenset({"utterance", "pause", "transition-in", "transition-out"}) | _UTTERANCE_ATTRS
)


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


def _parse_transition(value: str, lineno: int) -> Transition:
    parts = value.split()
    if not parts or parts[0] not in _VALID_TRANSITIONS:
        name = parts[0] if parts else value
        raise SidecarError(
            f"line {lineno}: invalid transition '{name}' "
            f"(use cut, fade, dissolve, wipe/slide/cover/reveal + a direction, "
            f"or circleopen/circleclose)"
        )
    kind: TransitionKind = parts[0]
    seconds = 0.0
    if len(parts) > 1:
        try:
            seconds = float(parts[1])
        except ValueError:
            raise SidecarError(
                f"line {lineno}: transition '{value}' has a non-numeric duration"
            ) from None
        if seconds < 0:
            raise SidecarError(f"line {lineno}: transition duration must be non-negative")
    return Transition(kind=kind, seconds=seconds)


class _UtteranceDraft:
    """Mutable accumulator for one ``utterance:`` block while parsing."""

    def __init__(self) -> None:
        self.text: str = ""
        self.text_seen: bool = False  # gates continuation lines (wrapped text)
        self.voice: str | None = None
        self.pace: Pace | None = None
        self.direction: str | None = None

    def to_segment(self) -> Segment:
        return Segment.speech(
            _WS_RE.sub(" ", self.text).strip(),
            voice=self.voice,
            pace=self.pace,
            direction=self.direction,
        )


def parse_segments(body: str) -> list[Segment]:
    """Split a plain *body* string into ordered speech/pause segments.

    A convenience for free-text editing: speech runs separated by inline
    ``[pause N]`` markers, with no per-utterance attributes. The structured
    block grammar (:func:`parse_sidecar`) is the on-disk form.
    """
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


def parse_sidecar(text: str) -> list[PageNarration]:  # noqa: C901
    """Parse sidecar *text* into a list of blocks in file order.

    Raises :class:`SidecarError` on content appearing before the first ``@``
    header, or on a malformed directive.
    """
    blocks: list[PageNarration] = []
    current: PageNarration | None = None
    draft: _UtteranceDraft | None = None
    raw_lines: list[str] = []  # the current block's raw text, header included
    pending: list[str] = []  # comment/blank lines not yet owned by a block

    def _flush_utterance() -> None:
        nonlocal draft
        if draft is not None and current is not None:
            current.segments.append(draft.to_segment())
        draft = None

    def _finish_source() -> None:
        if current is not None:
            current.source = "\n".join(raw_lines)

    def _require_block(lineno: int, what: str) -> PageNarration:
        if current is None:
            raise SidecarError(f"line {lineno}: {what} before any @slide-id header")
        return current

    for lineno, raw in enumerate(text.splitlines(), start=1):
        fmt = _FORMAT_RE.match(raw.strip())
        if fmt and int(fmt.group("version")) > FORMAT_VERSION:
            logger.warning(
                "sidecar declares slidesonnet-format %s but this version understands %s — "
                "newer directives may be misread; upgrade slidesonnet",
                fmt.group("version"),
                FORMAT_VERSION,
            )
        line = _strip_comment(raw).strip()
        if not line:
            pending.append(raw)
            continue

        header = _HEADER_RE.match(line)
        if header:
            _flush_utterance()
            _finish_source()
            current = PageNarration(
                slide_id=header.group("id"),
                lead="".join(f"{ln}\n" for ln in pending),
            )
            blocks.append(current)
            pending.clear()
            raw_lines = [raw]
            continue

        kv = _KV_RE.match(line)
        if kv is None or kv.group("key") not in _KNOWN_KEYS:
            if draft is not None and draft.text_seen:
                draft.text += f" {line}"  # a hand-wrapped continuation of text:
            elif kv is not None:
                raise SidecarError(f"line {lineno}: unknown directive '{kv.group('key')}:'")
            else:
                raise SidecarError(f"line {lineno}: cannot parse '{line}' (expected 'key: value')")
        else:
            key, value = kv.group("key"), kv.group("value")
            if key == "utterance":
                _require_block(lineno, "'utterance:'")
                _flush_utterance()
                draft = _UtteranceDraft()
            elif key == "pause":
                block = _require_block(lineno, "'pause:'")
                _flush_utterance()
                try:
                    seconds = float(value)
                except ValueError:
                    raise SidecarError(f"line {lineno}: pause '{value}' is not a number") from None
                block.segments.append(Segment.pause(seconds))
            elif key in {"transition-in", "transition-out"}:
                block = _require_block(lineno, f"'{key}:'")
                transition = _parse_transition(value, lineno)
                if key == "transition-in":
                    block.transition_in = transition
                else:
                    block.transition_out = transition
            else:  # an utterance attribute
                if draft is None:
                    raise SidecarError(f"line {lineno}: '{key}:' outside an 'utterance:' block")
                if key == "text":
                    draft.text = value
                    draft.text_seen = True
                elif key == "voice":
                    draft.voice = value or None
                elif key == "direct":
                    draft.direction = value or None
                else:  # pace
                    if value not in _VALID_PACES:
                        raise SidecarError(
                            f"line {lineno}: invalid pace '{value}' "
                            f"(expected one of {sorted(_VALID_PACES)})"
                        )
                    draft.pace = value  # type: ignore[assignment]

        # a content line: claim it (and any comments above it) for this block
        raw_lines.extend(pending)
        pending.clear()
        raw_lines.append(raw)

    _flush_utterance()
    # trailing end-of-file comments stay with the last block (blanks dropped)
    while pending and not pending[-1].strip():
        pending.pop()
    if current is not None and pending:
        current.tail = "".join(f"{ln}\n" for ln in pending)
    _finish_source()
    for block in blocks:
        block.canon = serialize_block(block)
    return blocks


def _serialize_transition(label: str, transition: Transition) -> list[str]:
    if transition.kind == "cut" and transition.seconds == 0:
        return []  # the default; omit for clean files
    if transition.is_animated and transition.seconds > 0:
        return [f"  {label}: {transition.kind} {_format_seconds(transition.seconds)}"]
    return [f"  {label}: {transition.kind}"]


def _serialize_utterance(seg: Segment) -> list[str]:
    lines = ["  utterance:"]
    if seg.voice:
        lines.append(f"    voice: {seg.voice}")
    if seg.pace:
        lines.append(f"    pace: {seg.pace}")
    if seg.direction:
        lines.append(f"    direct: {seg.direction}")
    lines.append(f"    text: {seg.text.strip()}")
    return lines


def serialize_block(block: PageNarration) -> str:
    """Serialize a single block to canonical sidecar text (no trailing newline)."""
    lines: list[str] = [f"@{block.slide_id}"]
    lines += _serialize_transition("transition-in", block.transition_in)
    for seg in block.segments:
        if seg.is_pause:
            lines.append(f"  pause: {_format_seconds(seg.seconds)}")
        else:
            lines += _serialize_utterance(seg)
    lines += _serialize_transition("transition-out", block.transition_out)
    return "\n".join(lines)


def serialize_body(block: PageNarration) -> str:
    """Serialize just a block's body as free text (speech + ``[pause N]``).

    Lossy convenience for the plain-text editing path: per-utterance voice,
    pace, and director's notes are dropped. Inverse of :func:`parse_segments`.
    """
    parts: list[str] = []
    for seg in block.segments:
        if seg.is_pause:
            parts.append(f"[pause {_format_seconds(seg.seconds)}]")
        elif seg.text.strip():
            parts.append(seg.text.strip())
    return " ".join(parts)


def serialize_sidecar(
    blocks: Iterable[PageNarration],
    *,
    header: str | None = None,
) -> str:
    """Serialize blocks to a sidecar document (trailing newline included).

    A block parsed from a file whose content is unchanged (its canonical form
    still matches the one captured at parse time) is re-emitted verbatim —
    comments, blank lines, and hand wrapping intact. Changed and fresh blocks
    are written canonically; a parsed block's ``lead``/``tail`` comments are
    kept either way.
    """
    out: list[str] = []
    if header:
        out.append("\n".join(f"# {ln}" if ln else "#" for ln in header.splitlines()) + "\n")
    for block in blocks:
        canonical = serialize_block(block)
        if block.lead is not None:
            out.append(block.lead)
        elif out:
            out.append("\n")  # canonical blank-line separator
        body = block.source if block.source is not None and block.canon == canonical else canonical
        out.append(body + "\n")
        if block.tail:
            out.append(block.tail)
    return "".join(out) if out else "\n"


def pace_to_speed(pace: Pace | None) -> float:
    """Map a pace directive to a TTS speed multiplier (1.0 = normal)."""
    return {"slow": 0.85, "normal": 1.0, "fast": 1.15}.get(pace or "normal", 1.0)
