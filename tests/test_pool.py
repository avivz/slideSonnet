"""Shared speech-clip pool: advisory index, reachability prune, quarantine."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.hashing import audio_filename
from slidesonnet.narration.format import serialize_sidecar
from slidesonnet.narration.model import PageNarration, Segment
from slidesonnet.pool import (
    INDEX_FILENAME,
    TRASH_DIRNAME,
    IndexRecord,
    append_index,
    apply_prune,
    empty_trash,
    load_index,
    plan_prune,
    pool_status,
)

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"

HELLO = "Hello world."
SHARED = "This sentence opens every lecture."
ONLY_B = "Only the second deck says this."


def _deck(directory: Path, name: str, lines: list[str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    pdf = directory / f"{name}.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    blocks = [
        PageNarration("intro-title", [Segment.speech(lines[0]), Segment.pause(1.0)]),
        PageNarration("euler-setup", [Segment.speech(t) for t in lines[1:]]),
    ]
    (directory / f"{name}.narration").write_text(serialize_sidecar(blocks), encoding="utf-8")
    return pdf


def _put(pool: Path, name: str, data: bytes = b"x") -> Path:
    pool.mkdir(parents=True, exist_ok=True)
    p = pool / name
    p.write_bytes(data)
    return p


# ---- index ------------------------------------------------------------------


def test_index_round_trips_and_merges_decks_per_file(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    rec = IndexRecord("h.kokoro.c.wav", "Hello world.", None, "kokoro", "/a/deck.pdf", "2026-09-16")
    append_index(pool, [rec])
    append_index(
        pool,
        [
            IndexRecord(
                "h.kokoro.c.wav", "Hello world.", None, "kokoro", "/b/deck.pdf", "2026-09-17"
            )
        ],
    )
    idx = load_index(pool)
    entry = idx["h.kokoro.c.wav"]
    assert entry.text == "Hello world."
    assert entry.decks == ["/a/deck.pdf", "/b/deck.pdf"]
    assert entry.last_used == "2026-09-17"


def test_index_skips_malformed_lines(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    append_index(pool, [IndexRecord("f", "t", None, "kokoro", "/d.pdf", "2026-01-01")])
    with (pool / INDEX_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    assert list(load_index(pool)) == ["f"]


def test_missing_index_loads_empty(tmp_path: Path) -> None:
    assert load_index(tmp_path / "nowhere") == {}


# ---- prune: reachability across every deck, not ownership ------------------


def test_plan_keeps_a_clip_any_deck_still_uses(tmp_path: Path) -> None:
    a = _deck(tmp_path / "a", "a", [HELLO, SHARED])
    b = _deck(tmp_path / "b", "b", [SHARED, ONLY_B])
    pool = tmp_path / "pool"
    shared = _put(pool, audio_filename(SHARED, "inworld", "k"))
    only_b = _put(pool, audio_filename(ONLY_B, "kokoro", "k"))
    orphan_paid = _put(pool, audio_filename("Gone.", "inworld", "k"), b"paid")
    orphan_local = _put(pool, audio_filename("Gone.", "kokoro", "k"))
    weird = _put(pool, "notes.txt")

    plan = plan_prune(pool, [a, b], keep="current")
    assert set(plan.kept) == {shared, only_b}
    assert plan.quarantine == [orphan_paid]  # money: parked, not unlinked
    assert plan.delete == [orphan_local]  # cheap to regenerate
    assert plan.unknown == [weird]  # never touched


def test_plan_exact_uses_each_decks_own_engine_config(tmp_path: Path) -> None:
    a = _deck(tmp_path / "a", "a", [HELLO])
    (tmp_path / "a" / "slidesonnet.toml").write_text(
        '[tts]\nbackend = "kokoro"\n[tts.kokoro]\nvoice = "af_heart"\n', encoding="utf-8"
    )
    pool = tmp_path / "pool"
    from slidesonnet.tts.kokoro import KokoroTTS  # cache key of the configured engine

    live = _put(pool, audio_filename(HELLO, "kokoro", KokoroTTS(voice="af_heart").cache_key()))
    other_cfg = _put(pool, audio_filename(HELLO, "kokoro", "kokoro:some-other-voice"))
    plan = plan_prune(pool, [a], keep="exact")
    assert plan.kept == [live]
    assert plan.delete == [other_cfg]


def test_plan_api_keeps_paid_clips_without_needing_decks(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    paid = _put(pool, audio_filename("x", "inworld", "k"))
    local = _put(pool, audio_filename("x", "kokoro", "k"))
    plan = plan_prune(pool, [], keep="api")
    assert plan.kept == [paid]
    assert plan.delete == [local]
    assert plan.quarantine == []


def test_plan_refuses_when_a_deck_fails_to_load(tmp_path: Path) -> None:
    """A deck that can't be read contributes no roots, so everything it uses
    would look orphaned — abort rather than plan around it."""
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    (tmp_path / "bad.narration").write_text("", encoding="utf-8")
    (tmp_path / "pool").mkdir()
    with pytest.raises(SlideSonnetError, match="bad.pdf"):
        plan_prune(tmp_path / "pool", [bad], keep="current")


def test_plan_on_a_missing_pool_is_empty(tmp_path: Path) -> None:
    plan = plan_prune(tmp_path / "nope", [], keep="api")
    assert plan.kept == plan.delete == plan.quarantine == []


# ---- apply ---------------------------------------------------------------------


def test_apply_quarantines_paid_and_deletes_local(tmp_path: Path) -> None:
    a = _deck(tmp_path / "a", "a", [HELLO])
    pool = tmp_path / "pool"
    paid_name = audio_filename("Gone.", "inworld", "k")
    _put(pool, paid_name, b"paid!")
    local = _put(pool, audio_filename("Gone.", "kokoro", "k"), b"loc")
    kept = _put(pool, audio_filename(HELLO, "kokoro", "k"))
    append_index(pool, [IndexRecord(paid_name, "Gone.", None, "inworld", str(a), "2026-01-01")])

    result = apply_prune(plan_prune(pool, [a], keep="current"))
    assert result.quarantined_files == 1 and result.quarantined_bytes == 5
    assert result.deleted_files == 1 and result.deleted_bytes == 3
    assert (pool / TRASH_DIRNAME / paid_name).read_bytes() == b"paid!"
    assert not (pool / paid_name).exists()
    assert not local.exists()
    assert kept.exists()
    # The index forgets the deleted clip but remembers the quarantined one, so
    # the trash listing can still say what each parked clip was.
    assert set(load_index(pool)) == {paid_name}


def test_empty_trash_removes_parked_clips(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    _put(pool / TRASH_DIRNAME, "a.inworld.b.mp3", b"12345")
    files, size = empty_trash(pool)
    assert (files, size) == (1, 5)
    assert not (pool / TRASH_DIRNAME).exists()
    assert empty_trash(pool) == (0, 0)


# ---- status ------------------------------------------------------------------


def test_status_counts_by_backend_and_trash(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    _put(pool, "a.inworld.b.mp3", b"12")
    _put(pool, "c.inworld.d.mp3", b"345")
    _put(pool, "e.kokoro.f.wav", b"6")
    _put(pool, "stray.txt", b"789")
    _put(pool / TRASH_DIRNAME, "g.inworld.h.mp3", b"0")
    st = pool_status(pool)
    assert st.by_backend == {"inworld": (2, 5), "kokoro": (1, 1)}
    assert st.unknown == (1, 3)
    assert st.trash == (1, 1)
    assert st.exists
    assert not pool_status(tmp_path / "nope").exists
