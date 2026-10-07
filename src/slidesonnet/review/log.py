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
      title: Split the Euler trick
      text: Split into two slides.

    == open c2 2026-09-27T14:12:00 author
      text: British spelling everywhere, please.

    == accept c1 2026-09-27T14:20:00 author

A record is a header line (``== <kind> <conversation|-> <time> <author>``) and
indented fields; ``text:`` continues over lines indented four spaces. Every
record ends with a blank line, so a record cut short by a crash mid-write is
recognizable and skipped. An ``open`` or ``message`` may carry a ``title:``; the
latest one names the conversation (a message with a title and no text renames it).
A conversation with no slides (``c2`` above) is about the whole deck; a message's
``add-slides:`` / ``remove-slides:`` narrow or widen it.

Compaction drops cleared conversations, so it keeps their highest id in a
``# last-id: cN`` comment below the format header: ids are never reused.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import logging
import os
import re
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, cast, get_args

logger = logging.getLogger(__name__)

FORMAT_HEADER = "# slidesonnet-review: 1\n"

#: The id of the permanent deck-wide conversation older logs have (``== message
#: deck …`` with no ``open``); it replays as an ordinary deck-wide conversation.
LEGACY_DECK = "deck"

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
_LAST_ID_RE = re.compile(r"^# last-id: c(\d+)\s*$", re.MULTILINE)
_ID_RE = re.compile(r"c(\d+)")


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
    removed: tuple[str, ...] = ()  # message: slides taken out of the scope
    origin: Origin = "requested"  # open only
    text: str = ""
    title: str = ""  # open/message: names the conversation from here on


# ---- serialization -----------------------------------------------------------


def serialize_record(rec: Record) -> str:
    lines = [f"== {rec.kind} {rec.conv or '-'} {rec.at} {rec.author}"]
    if rec.slides:
        name = "slides" if rec.kind == "open" else "add-slides"
        lines.append(f"  {name}: " + " ".join(f"@{s}" for s in rec.slides))
    if rec.removed:
        lines.append("  remove-slides: " + " ".join(f"@{s}" for s in rec.removed))
    if rec.kind == "open" and rec.origin != "requested":
        lines.append(f"  origin: {rec.origin}")
    if rec.title:
        lines.append(f"  title: {' '.join(rec.title.split())}")  # one line
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
    removed: tuple[str, ...] = ()
    origin = "requested"
    title = ""
    # Text continuation lines are indented four spaces, so they never match the
    # two-space field pattern — a text line that looks like "slides: …" is safe.
    for line in chunk[1:]:
        field_match = _FIELD_RE.match(line)
        if field_match is None:
            continue
        name, value = field_match.group(1), field_match.group(2) or ""
        if name in ("slides", "add-slides"):
            slides = tuple(tok.removeprefix("@") for tok in value.split())
        elif name == "remove-slides":
            removed = tuple(tok.removeprefix("@") for tok in value.split())
        elif name == "origin" and value in _ORIGINS:
            origin = value
        elif name == "title":
            title = value.strip()
    text = "\n".join(_collect_text(chunk))
    return Record(
        kind=cast(RecordKind, kind),
        conv=None if conv == "-" else conv,
        at=at,
        author=cast(Author, author),
        slides=slides,
        removed=removed,
        origin=cast(Origin, origin),
        text=text,
        title=title,
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
    title: str = ""  # optional name (the id stays the identifier)

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
    def deck_wide(self) -> bool:
        """About the whole deck rather than particular slides."""
        return not self.slides


@dataclass
class ReviewState:
    conversations: dict[str, Conversation]
    sends: int = 0  # how many ``send`` records — the ``review wait`` cursor
    retired: set[str] = field(default_factory=set)  # emptied unrequested conversations
    last_id: int = 0  # highest id ever handed out, including compacted-away ones

    def max_id(self) -> int:
        ids = [*self.conversations, *self.retired]
        numbers = [int(m.group(1)) for cid in ids if (m := _ID_RE.fullmatch(cid))]
        return max([self.last_id, *numbers])

    def next_id(self) -> str:
        return f"c{self.max_id() + 1}"

    def slide_conversations(self) -> list[Conversation]:
        """Conversations about particular slides (deck-wide ones left out)."""
        return [c for c in self.conversations.values() if not c.deck_wide]


def _untouched_unrequested(conv: Conversation) -> bool:
    """Filed automatically and still only system notes — nobody has taken it up."""
    return (
        conv.origin == "unrequested"
        and conv.status == "open"
        and all(m.author == "system" for m in conv.messages)
    )


def _claim(state: ReviewState, claimer: Conversation, slide_id: str) -> None:
    """*slide_id* joined *claimer*: take it out of untouched unrequested conversations.

    The agent may recompile before declaring a slide, and the editor files the
    change as unrequested in between; declaring it afterwards should land in
    the same place as declaring it first.
    """
    for conv in list(state.conversations.values()):
        if conv is claimer or slide_id not in conv.slides or not _untouched_unrequested(conv):
            continue
        conv.slides.remove(slide_id)
        if not conv.slides:
            del state.conversations[conv.id]
            state.retired.add(conv.id)


def replay(records: list[Record]) -> ReviewState:
    state = ReviewState(conversations={})
    for rec in records:
        if rec.kind == "send":
            state.sends += 1
            continue
        if rec.conv is None:
            continue
        conv = state.conversations.get(rec.conv)
        if rec.kind == "open" or (conv is None and rec.conv == LEGACY_DECK):
            if conv is None:
                conv = Conversation(id=rec.conv, origin=rec.origin)
                state.conversations[rec.conv] = conv
        elif conv is None:
            logger.warning("review log: %s for unknown conversation %s", rec.kind, rec.conv)
            continue
        for sid in rec.slides:
            if sid not in conv.slides:
                conv.slides.append(sid)
            if conv.origin != "unrequested":
                _claim(state, conv, sid)
        conv.slides = [sid for sid in conv.slides if sid not in rec.removed]
        if rec.title:
            conv.title = rec.title
        if rec.text:
            conv.messages.append(Message(author=rec.author, at=rec.at, text=rec.text))
        if rec.kind == "accept":
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


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _parse_logged(path: Path, text: str) -> list[Record]:
    records, warnings = parse_log(text)
    for warning in warnings:
        logger.warning("%s: %s", path.name, warning)
    return records


def read_records(path: Path) -> list[Record]:
    return _parse_logged(path, _read_text(path))


def read_state(path: Path) -> ReviewState:
    """Replay the log at *path*, including the id high-water mark compaction kept."""
    text = _read_text(path)
    state = replay(_parse_logged(path, text))
    state.last_id = max((int(n) for n in _LAST_ID_RE.findall(text)), default=0)
    return state


def append_unlocked(path: Path, *records: Record) -> None:
    """Append *records* in a single write; the caller holds the lock.

    A record torn by a crash (no closing blank line) is closed off first, so it
    can't swallow the records appended after it.
    """
    payload = "".join(serialize_record(r) for r in records)
    size = path.stat().st_size if path.exists() else 0
    if size == 0:
        prefix = FORMAT_HEADER + "\n"
    else:
        with path.open("rb") as fh:
            fh.seek(max(0, size - 2))
            tail = fh.read()
        prefix = "" if tail == b"\n\n" else "\n" if tail.endswith(b"\n") else "\n\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(prefix + payload)


def append(path: Path, *records: Record, lock_path: Path | None = None) -> None:
    """Append *records* in a single write while holding the lock."""
    with locked(lock_path or default_lock_path(path)):
        append_unlocked(path, *records)


def ensure_file(path: Path, *, lock_path: Path | None = None) -> None:
    """Create an empty log (just the format header) if *path* doesn't exist."""
    with locked(lock_path or default_lock_path(path)):
        if not path.exists():
            path.write_text(FORMAT_HEADER + "\n", encoding="utf-8")


def write_records_unlocked(path: Path, records: list[Record], *, last_id: int = 0) -> None:
    """Replace the whole log (compaction) atomically; the caller holds the lock."""
    mark = f"# last-id: c{last_id}\n" if last_id else ""
    payload = FORMAT_HEADER + mark + "\n" + "".join(serialize_record(r) for r in records)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_records(
    path: Path, records: list[Record], *, lock_path: Path | None = None, last_id: int = 0
) -> None:
    """Replace the whole log (compaction) atomically, under the lock."""
    with locked(lock_path or default_lock_path(path)):
        write_records_unlocked(path, records, last_id=last_id)
