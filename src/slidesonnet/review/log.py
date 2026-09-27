"""The ``<deck>.review`` log: an append-only record of review conversations.

The editor and the command line (usually an agent) both write this file while
the other is running, so it is never rewritten in place during normal use:
every action is one record *appended* under an exclusive lock, and the current
state is a replay of the log. Only Clear compacts it (:func:`write_records`),
under the same lock.

The format is readable in the style of the ``.narration`` sidecar::

    # slidesonnet-review: 1

    == open c1 2026-09-27T14:02:00 author
      slides: @euler-trick
      text: Too wordy. Split the trick into two steps,
        and keep the formula on screen for both.

    == message c1 2026-09-27T14:10:00 agent
      add-slides: @euler-trick-2
      text: Split into two slides.

    == accept c1 2026-09-27T14:20:00 author

A record is a header line (``== <kind> <conversation|-> <time> <author>``) and
indented fields; ``text:`` continues over lines indented four spaces. Every
record ends with a blank line, so a record cut short by a crash mid-write is
recognizable and skipped.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import logging
import os
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, cast, get_args

logger = logging.getLogger(__name__)

FORMAT_HEADER = "# slidesonnet-review: 1\n"

#: The permanent deck-wide conversation (no slide scope, never closes).
DECK = "deck"

RecordKind = Literal["open", "message", "accept", "reopen", "send"]
Author = Literal["author", "agent", "system"]
Origin = Literal["requested", "unrequested", "author-edits"]
Status = Literal["open", "closed"]
Turn = Literal["author", "agent"]

_KINDS = frozenset(get_args(RecordKind))
_AUTHORS = frozenset(get_args(Author))
_ORIGINS = frozenset(get_args(Origin))
_HEADER_RE = re.compile(r"^== (\S+) (\S+) (\S+) (\S+)\s*$")
_FIELD_RE = re.compile(r"^  ([a-z-]+):(?: (.*))?$")
_TEXT_INDENT = "    "


def now() -> str:
    """Local time to the second, as written in record headers."""
    return datetime.now().astimezone().replace(microsecond=0, tzinfo=None).isoformat()


@dataclass(frozen=True)
class Record:
    """One appended action."""

    kind: RecordKind
    conv: str | None  # None only for ``send``
    at: str
    author: Author
    slides: tuple[str, ...] = ()  # open: the scope; message: slides added to it
    origin: Origin = "requested"  # open only
    text: str = ""


# ---- serialization -----------------------------------------------------------


def serialize_record(rec: Record) -> str:
    lines = [f"== {rec.kind} {rec.conv or '-'} {rec.at} {rec.author}"]
    if rec.slides:
        name = "slides" if rec.kind == "open" else "add-slides"
        lines.append(f"  {name}: " + " ".join(f"@{s}" for s in rec.slides))
    if rec.kind == "open" and rec.origin != "requested":
        lines.append(f"  origin: {rec.origin}")
    if rec.text:
        first, *rest = rec.text.split("\n")
        lines.append(f"  text: {first}")
        lines += [_TEXT_INDENT + line for line in rest]
    return "\n".join(lines) + "\n\n"


def parse_log(text: str) -> tuple[list[Record], list[str]]:
    """Parse log text into records plus human-readable warnings."""
    chunks: list[list[str]] = []
    for line in text.split("\n"):
        if line.startswith("== "):
            chunks.append([line])
        elif chunks:
            chunks[-1].append(line)
    records: list[Record] = []
    warnings: list[str] = []
    for index, chunk in enumerate(chunks):
        last = index == len(chunks) - 1
        # A complete record ends with a blank line: its chunk's tail is ["", ""]
        # (the blank separator plus the split after the final newline) or, when
        # another header follows, at least one trailing "".
        if last and chunk[-2:] != ["", ""]:
            warnings.append(f"skipped an incomplete record at the end: {chunk[0]!r}")
            continue
        rec = _parse_chunk(chunk)
        if rec is None:
            warnings.append(f"skipped a malformed record: {chunk[0]!r}")
        else:
            records.append(rec)
    return records, warnings


def _parse_chunk(chunk: list[str]) -> Record | None:
    match = _HEADER_RE.match(chunk[0])
    if match is None:
        return None
    kind, conv, at, author = match.groups()
    if kind not in _KINDS or author not in _AUTHORS:
        return None
    slides: tuple[str, ...] = ()
    origin = "requested"
    # Text continuation lines are indented four spaces, so they never match the
    # two-space field pattern — a text line that looks like "slides: …" is safe.
    for line in chunk[1:]:
        field_match = _FIELD_RE.match(line)
        if field_match is None:
            continue
        name, value = field_match.group(1), field_match.group(2) or ""
        if name in ("slides", "add-slides"):
            slides = tuple(tok.removeprefix("@") for tok in value.split())
        elif name == "origin" and value in _ORIGINS:
            origin = value
    text = "\n".join(_collect_text(chunk))
    return Record(
        kind=cast(RecordKind, kind),
        conv=None if conv == "-" else conv,
        at=at,
        author=cast(Author, author),
        slides=slides,
        origin=cast(Origin, origin),
        text=text,
    )


def _collect_text(chunk: list[str]) -> list[str]:
    """The ``text:`` field's lines: its first line plus 4-space continuations."""
    out: list[str] = []
    in_text = False
    for line in chunk[1:]:
        if in_text:
            if line.startswith(_TEXT_INDENT):
                out.append(line[len(_TEXT_INDENT) :])
                continue
            break
        if line.startswith("  text:"):
            in_text = True
            out.append(line[len("  text:") :].removeprefix(" "))
    return out


# ---- replay --------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    author: Author
    at: str
    text: str


@dataclass
class Conversation:
    """A conversation's current state, rebuilt from the log."""

    id: str
    slides: list[str] = field(default_factory=list)
    origin: Origin = "requested"
    status: Status = "open"
    messages: list[Message] = field(default_factory=list)

    @property
    def turn(self) -> Turn:
        """Who should act next: the other side of the last author/agent message.

        System notes (automatic filing, "author edited the narration") don't
        pass the turn; with no author/agent message yet it's the author's.
        """
        for msg in reversed(self.messages):
            if msg.author == "author":
                return "agent"
            if msg.author == "agent":
                return "author"
        return "author"

    @property
    def is_deck(self) -> bool:
        return self.id == DECK


@dataclass
class ReviewState:
    conversations: dict[str, Conversation]
    sends: int = 0  # how many ``send`` records — the ``review wait`` cursor

    def next_id(self) -> str:
        numbers = [int(cid[1:]) for cid in self.conversations if re.fullmatch(r"c\d+", cid)]
        return f"c{max(numbers, default=0) + 1}"

    def slide_conversations(self) -> list[Conversation]:
        return [c for c in self.conversations.values() if not c.is_deck]


def replay(records: list[Record]) -> ReviewState:
    state = ReviewState(conversations={DECK: Conversation(id=DECK)})
    for rec in records:
        if rec.kind == "send":
            state.sends += 1
            continue
        if rec.conv is None:
            continue
        conv = state.conversations.get(rec.conv)
        if rec.kind == "open":
            if conv is None:
                conv = Conversation(id=rec.conv, origin=rec.origin)
                state.conversations[rec.conv] = conv
        elif conv is None:
            logger.warning("review log: %s for unknown conversation %s", rec.kind, rec.conv)
            continue
        for sid in rec.slides:
            if sid not in conv.slides and not conv.is_deck:
                conv.slides.append(sid)
        if rec.text:
            conv.messages.append(Message(author=rec.author, at=rec.at, text=rec.text))
        if rec.kind == "accept" and not conv.is_deck:
            conv.status = "closed"
        elif rec.kind == "reopen":
            conv.status = "open"
    return state


# ---- file I/O under a lock -----------------------------------------------------


def default_lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


@contextlib.contextmanager
def locked(lock_path: Path, *, timeout: float = 10.0) -> Iterator[None]:
    """Hold an exclusive lock on *lock_path* (``flock``, or an O_EXCL lockfile).

    ``flock`` isn't supported on every filesystem (WSL's Windows mounts among
    them); there the lock falls back to atomically creating ``<lock>.x``.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as exc:
            if exc.errno not in (errno.ENOLCK, errno.EINVAL, errno.EOPNOTSUPP):
                raise
            with _exclusive_file(lock_path.with_name(lock_path.name + ".x"), timeout):
                yield
            return
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextlib.contextmanager
def _exclusive_file(path: Path, timeout: float) -> Iterator[None]:
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError(f"could not lock {path} (remove it if no writer is running)")
            time.sleep(0.02)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def read_records(path: Path) -> list[Record]:
    if not path.exists():
        return []
    records, warnings = parse_log(path.read_text(encoding="utf-8"))
    for warning in warnings:
        logger.warning("%s: %s", path.name, warning)
    return records


def append(path: Path, *records: Record, lock_path: Path | None = None) -> None:
    """Append *records* in a single write while holding the lock."""
    payload = "".join(serialize_record(r) for r in records)
    with locked(lock_path or default_lock_path(path)):
        new = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8") as fh:
            fh.write((FORMAT_HEADER + "\n" if new else "") + payload)


def write_records(path: Path, records: list[Record], *, lock_path: Path | None = None) -> None:
    """Replace the whole log (compaction) atomically, under the lock."""
    payload = FORMAT_HEADER + "\n" + "".join(serialize_record(r) for r in records)
    with locked(lock_path or default_lock_path(path)):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
