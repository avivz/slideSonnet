"""The append-only ``.review`` log: format round-trip, replay, locking."""

from __future__ import annotations

import errno
import threading
from pathlib import Path

import pytest

from slidesonnet.review import log as log_mod
from slidesonnet.review.log import (
    Record,
    append,
    locked,
    parse_log,
    read_records,
    read_state,
    replay,
    serialize_record,
    write_records,
)


def _rec(kind: str, conv: str | None = "c1", **kw: object) -> Record:
    return Record(kind=kind, conv=conv, at="2026-09-27T14:02:00", author="author", **kw)  # type: ignore[arg-type]


def test_record_round_trip_with_multiline_text() -> None:
    rec = Record(
        kind="open",
        conv="c1",
        at="2026-09-27T14:02:00",
        author="author",
        slides=("euler-trick", "euler-2"),
        text="Too wordy.\n\nSplit it in two,\n  keeping the formula.",
    )
    text = serialize_record(rec)
    assert text.startswith("== open c1 2026-09-27T14:02:00 author\n")
    assert "  slides: @euler-trick @euler-2\n" in text
    (back,), warnings = parse_log(text)
    assert back == rec and warnings == []


def test_text_line_that_looks_like_a_field_stays_text() -> None:
    rec = _rec("message", text="first line\nslides: not a field")
    (back,), _ = parse_log(serialize_record(rec))
    assert back.text == "first line\nslides: not a field"


def test_truncated_final_record_is_ignored_with_warning() -> None:
    good = serialize_record(_rec("open", slides=("a",), text="hi"))
    partial = serialize_record(_rec("message", text="cut off here")).rstrip("\n")[:-4]
    records, warnings = parse_log(good + partial)
    assert len(records) == 1
    assert warnings and "incomplete" in warnings[0]


def test_malformed_header_is_skipped_with_warning() -> None:
    good = serialize_record(_rec("open", slides=("a",), text="hi"))
    records, warnings = parse_log("== bogus\n  text: ?\n\n" + good)
    assert len(records) == 1 and warnings


def test_replay_builds_conversations_turns_and_status() -> None:
    records = [
        _rec("open", slides=("a",), text="shorten"),
        Record("message", "c1", "t", "agent", slides=("b",), text="done, split into a+b"),
        Record("open", "c2", "t", "system", slides=("x",), origin="unrequested", text="changed"),
        _rec("accept"),
    ]
    state = replay(records)
    c1, c2 = state.conversations["c1"], state.conversations["c2"]
    assert c1.slides == ["a", "b"] and c1.status == "closed"
    assert [m.author for m in c1.messages] == ["author", "agent"]
    assert c2.origin == "unrequested" and c2.turn == "author"  # system opens → your turn
    assert state.next_id() == "c3"


def test_turn_follows_last_author_or_agent_message_not_system() -> None:
    state = replay(
        [
            _rec("open", slides=("a",), text="please fix"),
            Record("message", "c1", "t", "system", text="author edited the narration"),
        ]
    )
    assert state.conversations["c1"].turn == "agent"


def test_an_old_deck_conversation_loads_as_an_ordinary_deck_wide_one() -> None:
    """Logs from before deck-wide conversations were ordinary ones have ``message
    deck`` records with no ``open``: they replay as an open conversation with no
    slides, which can be narrowed, accepted, and cleared like any other."""
    assert replay([]).conversations == {}
    state = replay(
        [
            _rec("message", conv="deck", text="publish these"),
            Record("message", "deck", "t", "agent", text="done"),
        ]
    )
    deck = state.conversations["deck"]
    assert (deck.slides, deck.deck_wide, deck.turn, deck.status) == ([], True, "author", "open")
    assert state.slide_conversations() == []
    state = replay([_rec("message", conv="deck", text="x"), _rec("accept", conv="deck")])
    assert state.conversations["deck"].status == "closed"


def test_slides_can_be_added_and_removed() -> None:
    state = replay(
        [
            _rec("open", text="Tighten every intro"),
            Record("message", "c1", "t", "agent", slides=("a", "b"), text="a and b"),
            Record("message", "c1", "t", "agent", removed=("a",), text="only b"),
        ]
    )
    assert state.conversations["c1"].slides == ["b"]
    (back,), _ = parse_log(serialize_record(_rec("message", removed=("a", "b"), text="x")))
    assert back.removed == ("a", "b")


def test_reopen_and_send_cursor() -> None:
    state = replay(
        [
            _rec("open", slides=("a",), text="x"),
            _rec("accept"),
            _rec("reopen"),
            _rec("send", conv=None),
            _rec("send", conv=None),
        ]
    )
    assert state.conversations["c1"].status == "open"
    assert state.sends == 2


def test_append_creates_file_with_header_and_accumulates(tmp_path: Path) -> None:
    path = tmp_path / "deck.review"
    append(path, _rec("open", slides=("a",), text="one"))
    append(path, _rec("message", text="two"))
    assert path.read_text(encoding="utf-8").startswith("# slidesonnet-review: 1\n")
    assert [r.kind for r in read_records(path)] == ["open", "message"]


def test_concurrent_appends_never_interleave(tmp_path: Path) -> None:
    path = tmp_path / "deck.review"
    long_text = "word " * 2000

    def writer(n: int) -> None:
        for i in range(20):
            append(path, _rec("message", text=f"{n}-{i} {long_text}"))

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    records = read_records(path)
    assert len(records) == 80
    assert all(r.text == f"{r.text.split()[0]} {long_text}" for r in records)


def test_write_records_replaces_the_file(tmp_path: Path) -> None:
    path = tmp_path / "deck.review"
    append(path, _rec("open", slides=("a",), text="one"))
    write_records(path, [])
    assert read_records(path) == []


def test_unknown_field_is_ignored(tmp_path: Path) -> None:
    text = "== open c1 2026-09-27T14:02:00 author\n  mood: happy\n  slides: @a\n  text: hi\n\n"
    (rec,), _ = parse_log(text)
    assert rec.slides == ("a",) and rec.text == "hi"


@pytest.mark.parametrize("author", ["author", "agent", "system"])
def test_all_authors_round_trip(author: str) -> None:
    rec = Record("message", "c1", "2026-09-27T14:02:00", author, text="hi")  # type: ignore[arg-type]
    assert parse_log(serialize_record(rec))[0] == [rec]


def test_a_title_round_trips_and_the_latest_one_names_the_conversation() -> None:
    records = [
        _rec("open", slides=("a",), text="Too long.", title="Shorter intro"),
        _rec("message", text="Cut it.", title="Two-line intro"),
        _rec("message", text="Thanks."),  # no title: the name stays
    ]
    text = "".join(serialize_record(r) for r in records)
    assert "  title: Shorter intro\n" in text
    back, warnings = parse_log(text)
    assert back == records and warnings == []
    assert replay(back).conversations["c1"].title == "Two-line intro"
    renamed = replay([*back, _rec("message", title="Intro")]).conversations["c1"]
    assert renamed.title == "Intro" and len(renamed.messages) == 3  # a rename adds no message


def test_append_after_a_torn_record_keeps_the_new_one(tmp_path: Path) -> None:
    path = tmp_path / "deck.review"
    append(path, _rec("open", slides=("a",), text="one"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("== message c1 2026-09-27T14:03:00 author\n  text: cut sh")  # a crash mid-write
    append(path, _rec("message", text="two"))
    assert [r.text for r in read_records(path)][-1] == "two"


def test_compaction_keeps_the_id_high_water_mark_and_the_send_count(tmp_path: Path) -> None:
    path = tmp_path / "deck.review"
    write_records(path, [], last_id=7, sends=4)
    assert (
        path.read_text(encoding="utf-8") == "# slidesonnet-review: 1\n# last-id: c7\n# sends: 4\n\n"
    )
    # an older log's ``send`` record still counts on top of the header
    append(path, _rec("open", conv="c2", slides=("a",), text="x"), _rec("send", conv=None))
    state = read_state(path)
    assert (state.next_id(), state.sends) == ("c8", 5)


class TestFlockFallback:
    """``flock`` fails on some filesystems (WSL's Windows mounts): O_EXCL lockfile."""

    @pytest.fixture(autouse=True)
    def _no_flock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(fd: int, op: int) -> None:
            raise OSError(errno.ENOLCK, "no locks available")

        monkeypatch.setattr(log_mod.fcntl, "flock", refuse)

    def test_lockfile_is_held_then_removed_even_on_error(self, tmp_path: Path) -> None:
        lock = tmp_path / "review.lock"
        marker = tmp_path / "review.lock.x"
        with pytest.raises(RuntimeError), locked(lock):
            assert marker.exists()
            raise RuntimeError("boom")
        assert not marker.exists()

    def test_a_held_lockfile_times_out(self, tmp_path: Path) -> None:
        lock = tmp_path / "review.lock"
        (tmp_path / "review.lock.x").touch()  # another writer holds it
        with pytest.raises(TimeoutError, match="could not lock"), locked(lock, timeout=0):
            pass
        assert (tmp_path / "review.lock.x").exists()  # someone else's: left alone

    def test_appends_still_work(self, tmp_path: Path) -> None:
        path = tmp_path / "deck.review"
        append(path, _rec("open", slides=("a",), text="one"))
        assert [r.text for r in read_records(path)] == ["one"]
