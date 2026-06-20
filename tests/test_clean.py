"""Tests for cache cleanup preservation levels."""

from __future__ import annotations

from pathlib import Path

from slidesonnet.cache import audio_dir, cache_root, render_dir
from slidesonnet.clean import CleanResult, clean, prune_local_orphans
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


def test_keep_nothing_removes_all(tmp_path: Path) -> None:
    pdf = _seed(tmp_path)
    result = clean(pdf, keep="nothing")
    assert not cache_root(pdf).exists()
    assert result.removed_files >= 3


def test_clean_no_cache(tmp_path: Path) -> None:
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    result = clean(pdf, keep="api")
    assert result.removed_files == 0


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


def test_keep_api_without_render_dir(tmp_path: Path) -> None:
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    (ad / "aaaa.kokoro.bbbb.wav").write_bytes(b"x")
    result = clean(pdf, keep="api")
    assert result.removed_files == 1
    assert not (ad / "aaaa.kokoro.bbbb.wav").exists()


def test_keep_api_without_audio_dir(tmp_path: Path) -> None:
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    rd = render_dir(pdf)
    rd.mkdir(parents=True)
    (rd / "page-0001.png").write_bytes(b"img")
    result = clean(pdf, keep="api")
    assert not rd.exists()
    assert result.removed_files == 1
    assert result.kept_files == 0


def test_keep_api_drops_unparseable_names_and_skips_subdirs(tmp_path: Path) -> None:
    pdf = _seed(tmp_path)
    ad = audio_dir(pdf)
    (ad / "oldformat.wav").write_bytes(b"old")  # pre-format file: not API audio
    sub = ad / "nested"
    sub.mkdir()
    (sub / "stray.wav").write_bytes(b"s")
    clean(pdf, keep="api")
    assert not (ad / "oldformat.wav").exists()
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
    assert not (ad / "oldformat.wav").exists()  # unparseable name
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


def test_keep_current_skips_subdirs_and_missing_audio_dir(tmp_path: Path) -> None:
    pdf = _seed_deck(tmp_path)
    result = clean(pdf, keep="current")  # cache root exists? no — early return
    assert result.removed_files == 0

    rd = render_dir(pdf)
    rd.mkdir(parents=True)  # cache root now exists, but no audio dir
    result = clean(pdf, keep="current")
    assert result.kept_files == 0

    ad = audio_dir(pdf)
    sub = ad / "nested"
    sub.mkdir(parents=True)
    (sub / "stray.wav").write_bytes(b"s")
    clean(pdf, keep="current")
    assert (sub / "stray.wav").exists()


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


def test_keep_exact_missing_audio_dir_and_subdirs(tmp_path: Path) -> None:
    pdf = _seed_deck(tmp_path)
    rd = render_dir(pdf)
    rd.mkdir(parents=True)
    result = clean(pdf, keep="exact")  # no audio dir: nothing to keep, no crash
    assert result.kept_files == 0

    ad = audio_dir(pdf)
    sub = ad / "nested"
    sub.mkdir(parents=True)
    (sub / "stray.wav").write_bytes(b"s")
    clean(pdf, keep="exact")
    assert (sub / "stray.wav").exists()
