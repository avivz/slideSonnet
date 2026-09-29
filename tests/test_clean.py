"""Tests for cache cleanup preservation levels."""

from __future__ import annotations

from pathlib import Path

import pytest

from slidesonnet.cache import audio_dir, cache_root, render_dir
from slidesonnet.clean import (
    CleanResult,
    KeepLevel,
    clean,
    prune_local_orphans,
    retire_legacy_audio,
)
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.hashing import audio_filename, text_hash
from slidesonnet.models import VoiceConfig
from slidesonnet.narration.format import serialize_sidecar
from slidesonnet.narration.model import PageNarration, Segment

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def _seed(tmp_path: Path) -> Path:
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    # valid 3-part names: {text_hash}.{backend}.{config_hash}.{ext}
    (ad / "aaaa.kokoro.bbbb.wav").write_bytes(b"x")
    (ad / "cccc.inworld.dddd.mp3").write_bytes(b"y")
    rd = render_dir(pdf)
    rd.mkdir(parents=True)
    (rd / "page-0001.png").write_bytes(b"img")
    return pdf


def test_clean_removes_run_log(tmp_path: Path) -> None:
    pdf = _seed(tmp_path)
    log = cache_root(pdf) / "slidesonnet.log"
    log.write_text("run log", encoding="utf-8")
    (cache_root(pdf) / "slidesonnet.log.1").write_text("rotated", encoding="utf-8")
    clean(pdf, keep="api")  # the log is a disposable artifact, gone on any clean
    assert not log.exists()
    assert not (cache_root(pdf) / "slidesonnet.log.1").exists()


def test_keep_api_drops_kokoro_keeps_cloud(tmp_path: Path) -> None:
    pdf = _seed(tmp_path)
    clean(pdf, keep="api")
    ad = audio_dir(pdf)
    assert not (ad / "aaaa.kokoro.bbbb.wav").exists()
    assert (ad / "cccc.inworld.dddd.mp3").exists()
    assert not render_dir(pdf).exists()  # renders always removed


def test_keep_nothing_removes_all_but_parks_paid_clips_in_trash(tmp_path: Path) -> None:
    pdf = _seed(tmp_path)
    result = clean(pdf, keep="nothing")
    assert [p.name for p in cache_root(pdf).rglob("*") if p.is_file()] == ["cccc.inworld.dddd.mp3"]
    assert result.trash_dir == audio_dir(pdf) / "trash"
    assert (result.removed_files, result.trashed_files) == (2, 1)


def test_no_clean_touches_the_review(tmp_path: Path) -> None:
    """The review base is the author's record of what was already seen, not a cache:
    even ``--keep nothing`` leaves it, or every change since would vanish unseen."""
    pdf = _seed(tmp_path)
    review = cache_root(pdf) / "review" / "deck"
    (review / "pages").mkdir(parents=True)
    (review / "base.json").write_text("{}", encoding="utf-8")
    (review / "pages" / "ab12.png").write_bytes(b"img")
    levels: tuple[KeepLevel, ...] = ("api", "nothing")
    for keep in levels:
        clean(pdf, keep=keep)
        assert (review / "base.json").exists() and (review / "pages" / "ab12.png").exists()
    assert not (audio_dir(pdf) / "aaaa.kokoro.bbbb.wav").exists()  # everything else still goes


def test_removed_mb_converts_bytes() -> None:
    assert CleanResult(removed_bytes=3 * 1024 * 1024).removed_mb == 3.0
    assert CleanResult().removed_mb == 0.0


def test_clean_reports_counts_and_bytes(tmp_path: Path) -> None:
    pdf = _seed(tmp_path)
    result = clean(pdf, keep="api")
    # kokoro clip (1 byte) + render png (3 bytes) removed; inworld clip kept
    assert result.removed_files == 2
    assert result.removed_bytes == 4
    assert result.kept_files == 1


def test_keep_api_leaves_unrecognized_files_and_subdirs(tmp_path: Path) -> None:
    pdf = _seed(tmp_path)
    ad = audio_dir(pdf)
    (ad / "oldformat.wav").write_bytes(b"old")  # not a clip name: not ours to judge
    sub = ad / "nested"
    sub.mkdir()
    (sub / "stray.wav").write_bytes(b"s")
    clean(pdf, keep="api")
    assert (ad / "oldformat.wav").exists()
    assert (sub / "stray.wav").exists()  # directories are skipped, not unlinked
    assert (ad / "cccc.inworld.dddd.mp3").exists()


# --- keep="current" / keep="exact" need a real deck (PDF + sidecar + optional config) ---

HELLO = "Hello world."
SECOND = "Second slide."


def _seed_deck(tmp_path: Path, *, with_voices: bool = False) -> Path:
    """Copy the marked fixture PDF and write a sidecar (+ optional voice config)."""
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    blocks = [
        PageNarration("intro-title", [Segment.speech(HELLO), Segment.pause(1.0)]),
        PageNarration("euler-setup", [Segment.speech(SECOND, voice="narrator")]),
    ]
    (tmp_path / "marked.narration").write_text(serialize_sidecar(blocks), encoding="utf-8")
    if with_voices:
        (tmp_path / "slidesonnet.toml").write_text(
            '[voices.narrator]\nkokoro = "af_bella"\n', encoding="utf-8"
        )
    return pdf


def test_keep_current_keeps_text_matches_any_engine(tmp_path: Path) -> None:
    pdf = _seed_deck(tmp_path)
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    current_kokoro = audio_filename(HELLO, "kokoro", "kokoro:am_echo")
    current_inworld = audio_filename(HELLO, "inworld", "inworld:v:m:0.5:0.75")
    stale = audio_filename("Old deleted text.", "kokoro", "kokoro:am_echo")
    for name in (current_kokoro, current_inworld, stale):
        (ad / name).write_bytes(b"a")
    (ad / "oldformat.wav").write_bytes(b"old")

    result = clean(pdf, keep="current")
    assert (ad / current_kokoro).exists()  # current text, local engine
    assert (ad / current_inworld).exists()  # current text, cloud engine — engine-agnostic
    assert not (ad / stale).exists()  # orphaned utterance
    assert (ad / "oldformat.wav").exists()  # unparseable name: left alone
    assert result.kept_files == 2


def test_keep_current_includes_preset_voice_variants(tmp_path: Path) -> None:
    pdf = _seed_deck(tmp_path, with_voices=True)
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    voiced = f"{text_hash(SECOND, 'af_bella')}.kokoro.12345678.wav"
    voiceless = f"{text_hash(SECOND)}.kokoro.12345678.wav"
    other_voice = f"{text_hash(SECOND, 'af_nova')}.kokoro.12345678.wav"
    for name in (voiced, voiceless, other_voice):
        (ad / name).write_bytes(b"a")

    clean(pdf, keep="current")
    assert (ad / voiced).exists()  # preset's mapped voice id
    assert (ad / voiceless).exists()  # default-voice variant always kept
    assert not (ad / other_voice).exists()  # voice not in the preset


def _seed_deck_preamble_voices(tmp_path: Path) -> Path:
    """A deck whose voices live in the sidecar *preamble* (like the basel demo):
    ``config.voices`` is empty, and a default-voiced utterance falls back to a
    named preset that resolves to a concrete per-backend id (Inworld ``Tyler``,
    Kokoro ``am_michael``)."""
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    blocks = [PageNarration("intro-title", [Segment.speech(HELLO)])]  # no per-seg voice
    lecturer = VoiceConfig(
        name="lecturer", backend_voices={"inworld": "Tyler", "kokoro": "am_michael"}
    )
    (tmp_path / "marked.narration").write_text(
        serialize_sidecar(blocks, voices={"lecturer": lecturer}, default_voice="lecturer"),
        encoding="utf-8",
    )
    return pdf


def test_keep_current_keeps_preamble_default_voice_any_engine(tmp_path: Path) -> None:
    """Regression: a default-voiced utterance whose voice lives in the deck
    preamble resolves to a concrete per-backend id. ``--keep current`` must
    recognize those clips (esp. paid Inworld) instead of deleting them as
    orphans. Content is garbage; only the cache *name* matters."""
    pdf = _seed_deck_preamble_voices(tmp_path)
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    # Names synthesis actually writes for the default (lecturer) voice:
    inworld_clip = f"{text_hash(HELLO, 'Tyler')}.inworld.aaaaaaaa.mp3"
    kokoro_clip = f"{text_hash(HELLO, 'am_michael')}.kokoro.bbbbbbbb.wav"
    voiceless = f"{text_hash(HELLO)}.kokoro.bbbbbbbb.wav"  # default variant, also kept
    wrong_voice = f"{text_hash(HELLO, 'af_nope')}.kokoro.bbbbbbbb.wav"  # not a current voice
    stale = f"{text_hash('Old gone text.', 'Tyler')}.inworld.aaaaaaaa.mp3"  # orphaned text
    for name in (inworld_clip, kokoro_clip, voiceless, wrong_voice, stale):
        (ad / name).write_bytes(b"garbage")

    clean(pdf, keep="current")
    assert (ad / inworld_clip).exists()  # paid clip for the preamble default voice — KEPT
    assert (ad / kokoro_clip).exists()  # local clip for the preamble default voice
    assert (ad / voiceless).exists()  # bare default-voice variant
    assert not (ad / wrong_voice).exists()  # voice not mapped by the preset
    assert not (ad / stale).exists()  # text no longer in the deck


def test_keep_exact_resolves_preamble_default_voice(tmp_path: Path) -> None:
    """Regression for ``--keep exact``: the active engine's expected filename must
    use the preamble default voice (``lecturer`` -> ``am_michael`` on Kokoro), not
    the voiceless name — otherwise it deletes the clip synthesis really wrote."""
    pdf = _seed_deck_preamble_voices(tmp_path)
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    # active engine: kokoro defaults -> cache_key "kokoro:am_echo"; default voice -> am_michael
    exact = audio_filename(HELLO, "kokoro", "kokoro:am_echo", voice="am_michael")
    voiceless = audio_filename(HELLO, "kokoro", "kokoro:am_echo")
    (ad / exact).write_bytes(b"garbage")
    (ad / voiceless).write_bytes(b"garbage")

    clean(pdf, keep="exact")
    assert (ad / exact).exists()  # the name synthesis actually writes
    assert not (ad / voiceless).exists()  # default voice is am_michael, not None


def test_keep_exact_keeps_only_active_engine_config(tmp_path: Path) -> None:
    pdf = _seed_deck(tmp_path)
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    # Active engine with defaults: kokoro, voice am_echo -> cache_key "kokoro:am_echo"
    exact = audio_filename(HELLO, "kokoro", "kokoro:am_echo")
    other_config = audio_filename(HELLO, "kokoro", "kokoro:af_bella")
    other_engine = audio_filename(HELLO, "inworld", "inworld:v:m:0.5:0.75")
    for name in (exact, other_config, other_engine):
        (ad / name).write_bytes(b"a")

    result = clean(pdf, keep="exact")
    assert (ad / exact).exists()
    assert not (ad / other_config).exists()  # same text, different engine config
    assert not (ad / other_engine).exists()  # same text, inactive engine
    assert result.kept_files == 1


def test_keep_exact_resolves_block_voice_preset(tmp_path: Path) -> None:
    pdf = _seed_deck(tmp_path, with_voices=True)
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    voiced = audio_filename(SECOND, "kokoro", "kokoro:am_echo", voice="af_bella")
    unvoiced = audio_filename(SECOND, "kokoro", "kokoro:am_echo")
    (ad / voiced).write_bytes(b"a")
    (ad / unvoiced).write_bytes(b"a")

    clean(pdf, keep="exact")
    assert (ad / voiced).exists()  # narrator preset resolves to af_bella on kokoro
    assert not (ad / unvoiced).exists()  # default-voice variant is not the exact name


def test_keep_exact_keeps_paced_utterance_cache(tmp_path: Path) -> None:
    """Paced utterances embed the multiplied speed in the cache key — exact-keep
    must predict that name, not the base engine's, or it deletes paid audio."""
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    blocks = [
        PageNarration("intro-title", [Segment.speech(HELLO, pace="fast")]),
        PageNarration("euler-setup", [Segment.speech(SECOND)]),
    ]
    (tmp_path / "marked.narration").write_text(serialize_sidecar(blocks), encoding="utf-8")
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    # fast pace -> kokoro_speed 1.0 * 1.15, which lands in the cache key
    paced = audio_filename(HELLO, "kokoro", "kokoro:am_echo:1.15")
    unpaced = audio_filename(SECOND, "kokoro", "kokoro:am_echo")
    stale = audio_filename(HELLO, "kokoro", "kokoro:am_echo")  # pace-less variant is stale
    for name in (paced, unpaced, stale):
        (ad / name).write_bytes(b"a")

    clean(pdf, keep="exact")
    assert (ad / paced).exists()  # the clip synthesis actually uses
    assert (ad / unpaced).exists()
    assert not (ad / stale).exists()


@pytest.mark.parametrize("keep", ["api", "current", "exact"])
def test_clean_missing_dirs_and_subdirs(tmp_path: Path, keep: KeepLevel) -> None:
    pdf = _seed_deck(tmp_path)
    assert clean(pdf, keep=keep).removed_files == 0  # no cache yet: nothing to do

    rd = render_dir(pdf)
    rd.mkdir(parents=True)
    (rd / "page-0001.png").write_bytes(b"img")
    result = clean(pdf, keep=keep)  # renders but no audio dir
    assert not rd.exists()
    assert (result.removed_files, result.kept_files) == (1, 0)

    ad = audio_dir(pdf)
    (ad / "nested").mkdir(parents=True)
    (ad / "nested" / "stray.wav").write_bytes(b"s")
    (ad / "aaaa.kokoro.bbbb.wav").write_bytes(b"x")
    result = clean(pdf, keep=keep)  # audio but no render dir
    assert result.removed_files == 1
    assert not (ad / "aaaa.kokoro.bbbb.wav").exists()
    assert (ad / "nested" / "stray.wav").exists()  # directories are skipped, not unlinked


# --- prune_local_orphans: silent on-edit cleanup of cheap local audio ---


def test_prune_local_orphans_drops_edited_away_local_clips(tmp_path: Path) -> None:
    pdf = _seed_deck(tmp_path)
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    current = audio_filename(HELLO, "kokoro", "kokoro:am_echo")
    stale = audio_filename("Old deleted text.", "kokoro", "kokoro:af_bella")
    paid_orphan = audio_filename("Old deleted text.", "inworld", "inworld:v")
    for name in (current, stale, paid_orphan):
        (ad / name).write_bytes(b"a")

    result = prune_local_orphans(pdf)
    assert (ad / current).exists()  # current text — kept
    assert not (ad / stale).exists()  # orphaned local clip — dropped
    assert (ad / paid_orphan).exists()  # paid audio is never auto-pruned
    assert result.removed_files == 1


def test_prune_local_orphans_keeps_expensive_local_qwen3(tmp_path: Path) -> None:
    """Qwen3 is free but slow (seconds/clip on the iGPU), so its orphans are kept.

    The eager auto-sweep must distinguish *cheap* local audio (Kokoro — regenerate
    in <1s) from *expensive* local audio (Qwen3), not just paid-vs-free: discarding
    a now-orphaned Qwen3 clip on an unrelated edit silently throws away minutes of
    own-voice generation.
    """
    pdf = _seed_deck(tmp_path)
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    kokoro_orphan = audio_filename("Old deleted text.", "kokoro", "kokoro:am_echo")
    qwen3_orphan = audio_filename("Old deleted text.", "qwen3", "qwen3:Dylan")
    for name in (kokoro_orphan, qwen3_orphan):
        (ad / name).write_bytes(b"a")

    result = prune_local_orphans(pdf)
    assert not (ad / kokoro_orphan).exists()  # cheap local — still swept eagerly
    assert (ad / qwen3_orphan).exists()  # expensive local — kept, not auto-discarded
    assert result.removed_files == 1


def test_prune_local_orphans_keeps_renders_and_unknown_names(tmp_path: Path) -> None:
    pdf = _seed_deck(tmp_path)
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    stale = audio_filename("Gone.", "kokoro", "kokoro:am_echo")
    (ad / stale).write_bytes(b"a")
    (ad / "legacy.wav").write_bytes(b"old")  # unparseable: left alone, not our call
    rd = render_dir(pdf)
    rd.mkdir(parents=True)
    (rd / "page-0001.png").write_bytes(b"img")

    prune_local_orphans(pdf)
    assert not (ad / stale).exists()
    assert (ad / "legacy.wav").exists()  # auto-prune never deletes unrecognized files
    assert (rd / "page-0001.png").exists()  # renders untouched


def test_prune_local_orphans_no_audio_dir(tmp_path: Path) -> None:
    pdf = _seed_deck(tmp_path)
    result = prune_local_orphans(pdf)  # never synthesized: nothing to do, no crash
    assert result.removed_files == 0


# ---- shared pool: per-deck clean never reaches into it -------------------------


def _pooled_deck(tmp_path: Path) -> tuple[Path, Path]:
    pdf = _seed(tmp_path)  # local audio + render dir seeded
    pool = tmp_path / "pool"
    pool.mkdir()
    (pool / "eeee.inworld.ffff.mp3").write_bytes(b"other deck's paid clip")
    (tmp_path / "slidesonnet.toml").write_text(
        f'[cache]\naudio_dir = "{pool.as_posix()}"\n', encoding="utf-8"
    )
    return pdf, pool


def test_clean_in_pool_mode_touches_scratch_only_and_reports_the_pool(tmp_path: Path) -> None:
    pdf, pool = _pooled_deck(tmp_path)
    log = cache_root(pdf) / "slidesonnet.log"
    log.write_text("log", encoding="utf-8")
    result = clean(pdf, keep="current")  # would sweep a private cache; here it can't
    assert result.pool == pool
    assert (pool / "eeee.inworld.ffff.mp3").exists()
    assert not render_dir(pdf).exists()
    assert not log.exists()


def test_clean_in_pool_mode_adopts_then_drops_the_legacy_local_audio(tmp_path: Path) -> None:
    """Clips left in the old deck-local cache are moved into the pool on clean,
    so nothing paid is lost and the duplicate stops taking space."""
    pdf, pool = _pooled_deck(tmp_path)
    parked = cache_root(pdf) / "audio" / "trash" / "9999.inworld.dddd.mp3"
    parked.parent.mkdir()
    parked.write_bytes(b"trashed by an earlier clean")
    clean(pdf, keep="api")
    assert (pool / "trash" / parked.name).exists()  # still parked, never lost
    assert (pool / "cccc.inworld.dddd.mp3").exists()
    assert (pool / "aaaa.kokoro.bbbb.wav").exists()
    assert not audio_dir(pdf).exists()  # the pool
    assert not (cache_root(pdf) / "audio").exists()  # the legacy local dir


def test_clean_keep_nothing_in_pool_mode_removes_only_the_local_cache(tmp_path: Path) -> None:
    pdf, pool = _pooled_deck(tmp_path)
    result = clean(pdf, keep="nothing")
    assert not cache_root(pdf).exists()
    assert (pool / "eeee.inworld.ffff.mp3").exists()
    assert result.pool == pool


def test_prune_local_orphans_is_a_noop_in_pool_mode(tmp_path: Path) -> None:
    pdf = _seed_deck(tmp_path)
    pool = tmp_path / "pool"
    pool.mkdir()
    orphan = pool / audio_filename("Some other deck's line.", "kokoro", "kokoro:am_echo")
    orphan.write_bytes(b"a")
    (tmp_path / "slidesonnet.toml").write_text(
        f'[cache]\naudio_dir = "{pool.as_posix()}"\n', encoding="utf-8"
    )
    result = prune_local_orphans(pdf)
    assert orphan.exists()
    assert result.removed_files == 0


def test_prune_keeps_clips_the_review_base_still_says(tmp_path: Path) -> None:
    """Under review, the old narration is still being compared (play old vs new),
    so its clip counts as in use even after the sidecar moved on."""
    from slidesonnet.review.base import snapshot

    pdf = _seed_deck(tmp_path)
    snapshot(pdf)  # base holds HELLO
    edited = [PageNarration("intro-title", [Segment.speech("A rewritten line.")])]
    (tmp_path / "marked.narration").write_text(serialize_sidecar(edited), encoding="utf-8")
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    old = audio_filename(HELLO, "kokoro", "kokoro:am_echo")
    gone = audio_filename("Never said anywhere.", "kokoro", "kokoro:am_echo")
    for name in (old, gone):
        (ad / name).write_bytes(b"a")

    prune_local_orphans(pdf)
    assert (ad / old).exists()  # the base's narration — kept
    assert not (ad / gone).exists()


# ---- one clip GC: the default audio dir is shared by every deck in the folder ----------

ONLY_A = "Only deck a says this."
ONLY_B = "Only deck b says this."
GONE = "Nobody says this any more."


def _two_decks(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    """Decks a and b side by side, so they share ``.slidesonnet/audio/``."""

    def deck(name: str, line: str) -> Path:
        pdf = tmp_path / f"{name}.pdf"
        pdf.write_bytes(MARKED.read_bytes())
        blocks = [PageNarration("intro-title", [Segment.speech(line)])]
        (tmp_path / f"{name}.narration").write_text(serialize_sidecar(blocks), encoding="utf-8")
        return pdf

    a, b = deck("a", ONLY_A), deck("b", ONLY_B)
    ad = audio_dir(a)
    ad.mkdir(parents=True)
    clips = {
        "a_local": ad / audio_filename(ONLY_A, "kokoro", "kokoro:am_echo"),
        "a_paid": ad / audio_filename(ONLY_A, "inworld", "inworld:v"),
        "b_local": ad / audio_filename(ONLY_B, "kokoro", "kokoro:am_echo"),
        "b_paid": ad / audio_filename(ONLY_B, "inworld", "inworld:v"),
        "gone_local": ad / audio_filename(GONE, "kokoro", "kokoro:am_echo"),
        "gone_paid": ad / audio_filename(GONE, "inworld", "inworld:v"),
    }
    for p in clips.values():
        p.write_bytes(b"clip")
    for pdf in (a, b):
        render_dir(pdf).mkdir(parents=True)
        (render_dir(pdf) / "page-0001.png").write_bytes(b"img")
    return a, b, clips


@pytest.mark.parametrize(
    ("keep", "a_survivors"),
    [
        ("nothing", set()),
        ("api", {"a_paid", "gone_paid"}),
        ("current", {"a_local", "a_paid"}),
        ("exact", {"a_local"}),  # the active engine is kokoro
    ],
)
def test_clean_keeps_what_a_sibling_deck_uses_and_trashes_paid(
    tmp_path: Path, keep: KeepLevel, a_survivors: set[str]
) -> None:
    a, b, clips = _two_decks(tmp_path)
    result = clean(a, keep=keep)

    assert clips["b_local"].exists() and clips["b_paid"].exists()  # b loses nothing
    assert (render_dir(b) / "page-0001.png").exists()  # not even its renders
    assert not render_dir(a).exists()
    for name in ("a_local", "a_paid", "gone_local", "gone_paid"):
        assert clips[name].exists() == (name in a_survivors), name
    paid_gone = {"a_paid", "gone_paid"} - a_survivors
    trash = audio_dir(a) / "trash"
    trashed = {p.name for p in trash.iterdir()} if trash.exists() else set()
    assert trashed == {clips[n].name for n in paid_gone}
    assert result.trashed_files == len(paid_gone)  # paid clips are parked, never deleted
    assert result.kept_paid == 1 + len({"a_paid", "gone_paid"} & a_survivors)


def test_clean_refuses_when_a_sibling_sidecar_is_unreadable(tmp_path: Path) -> None:
    a, _b, clips = _two_decks(tmp_path)
    (tmp_path / "b.narration").write_bytes(b"\xff\xfe not utf-8 \xff")
    with pytest.raises(SlideSonnetError, match="b.pdf"):
        clean(a, keep="current")
    assert all(p.exists() for p in clips.values())  # nothing touched
    assert prune_local_orphans(a).removed_files == 0  # the sweep fails safe too
    assert clips["gone_local"].exists()


def test_the_sweep_spares_sibling_clips_and_honours_the_narration_override(
    tmp_path: Path,
) -> None:
    a, _b, clips = _two_decks(tmp_path)
    override = tmp_path / "draft.narration"
    override.write_text(
        serialize_sidecar([PageNarration("intro-title", [Segment.speech(GONE)])]),
        encoding="utf-8",
    )
    prune_local_orphans(a, override)
    assert clips["b_local"].exists()  # deck b still says it
    assert clips["gone_local"].exists()  # the override sidecar says it
    assert clips["a_local"].exists()  # a's default sidecar is still a root


def test_the_sweep_waits_out_a_grace_period_that_restarts_on_reuse(tmp_path: Path) -> None:
    """Try a voice, revert: the old clips were orphans for a moment, then live again."""
    a, _b, clips = _two_decks(tmp_path)
    sidecar = tmp_path / "a.narration"
    original = sidecar.read_text(encoding="utf-8")
    since: dict[str, float] = {}

    def sweep(now: float) -> CleanResult:
        return prune_local_orphans(a, orphaned_since=since, grace_s=600, now=now)

    assert sweep(0.0).deferred_files == 1  # gone_local: orphaned, but only just
    sidecar.write_text(original.replace(ONLY_A, "Trying something."), encoding="utf-8")
    sweep(10.0)  # a_local orphaned
    sidecar.write_text(original, encoding="utf-8")  # reverted
    sweep(20.0)
    sidecar.write_text(original.replace(ONLY_A, "Trying again."), encoding="utf-8")
    assert sweep(599.0).removed_files == 0
    assert sweep(615.0).removed_files == 1  # gone_local, orphaned since t=0
    assert not clips["gone_local"].exists()
    assert clips["a_local"].exists()  # orphaned again only since t=599
    assert clips["gone_paid"].exists()  # the sweep never touches paid audio


@pytest.mark.parametrize("where", ["same", "inside", "parent"])
def test_retire_legacy_audio_never_deletes_the_pool(tmp_path: Path, where: str) -> None:
    pdf = _seed(tmp_path)
    legacy = cache_root(pdf) / "audio"
    pool = {"same": legacy, "inside": legacy / "pool", "parent": cache_root(pdf)}[where]
    pool.mkdir(parents=True, exist_ok=True)
    (pool / "ffff.inworld.eeee.mp3").write_bytes(b"paid")
    assert retire_legacy_audio(pdf, pool) == 0
    assert (pool / "ffff.inworld.eeee.mp3").exists()
    assert (legacy / "cccc.inworld.dddd.mp3").exists()
