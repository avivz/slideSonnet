"""Unit tests for EditorState helpers that back the editor's filmstrip."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from slidesonnet.gui.state import (
    EditorState,
    bracket_silences,
    cue_start,
    split_edge_silences,
)
from slidesonnet.narration.format import parse_segments, serialize_body
from slidesonnet.narration.model import Segment
from tests.conftest import prep_marked_deck, simple_narration


def test_preview_forwards_progress_to_build_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The editor's preview entry points hand their progress callback down to
    api.build_preview, so the assembly bar can track the whole-deck track build."""
    from slidesonnet.api import Preview

    state = EditorState(prep_marked_deck(tmp_path, simple_narration("@intro-title\nHi.\n")))
    captured: list[object] = []

    def fake_build_preview(_pdf: Path, **kwargs: object) -> Preview:
        captured.append(kwargs.get("progress"))
        return Preview(track=tmp_path / "track.wav", cues=[], total_duration=0.0)

    monkeypatch.setattr("slidesonnet.gui.state.api.build_preview", fake_build_preview)

    def cb(label: str, done: int, total: int) -> None:
        return None

    state.preview_deck(cb)
    state.preview_current(cb)
    assert captured == [cb, cb]


def test_split_edge_silences_separates_holds_from_middle() -> None:
    s = Segment.speech("hi")
    # leading + trailing pauses are split out; the middle is the speech.
    lead, mid, trail = split_edge_silences([Segment.pause(1.0), s, Segment.pause(2.0)])
    assert (lead, mid, trail) == (1.0, [s], 2.0)
    # speech-only: no edge pauses -> both None.
    assert split_edge_silences([s]) == (None, [s], None)
    # a lone pause counts only as leading (a silent slide's single hold).
    assert split_edge_silences([Segment.pause(3.0)]) == (3.0, [], None)


def test_bracket_silences_round_trips_with_split() -> None:
    s = Segment.speech("hi")
    bracketed = bracket_silences([s], 0.3, 0.5)
    assert bracketed == [Segment.pause(0.3), s, Segment.pause(0.5)]
    assert split_edge_silences(bracketed) == (0.3, [s], 0.5)
    # a None edge is omitted; negatives are clamped to 0.
    assert bracket_silences([s], None, -1.0) == [s, Segment.pause(0.0)]


FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def _state(tmp_path: Path, sidecar: str = "") -> EditorState:
    return EditorState(prep_marked_deck(tmp_path, sidecar))


def test_actions_let_on_disk_config_pick_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synthesis/preview/export must not pin the editor's cached backend.

    The user can edit slidesonnet.toml between the 1s config polls; passing the
    stale cached backend could run the wrong (possibly paid) engine. Passing
    engine=None makes api re-read the on-disk config at action time.
    """
    from slidesonnet.gui import state as state_mod

    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    captured: dict[str, object] = {}

    def fake_synthesize_deck(pdf: Path, **kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    def fake_build_preview(pdf: Path, **kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    def fake_export(pdf: Path, output: Path, **kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(state_mod.api, "synthesize_deck", fake_synthesize_deck)
    monkeypatch.setattr(state_mod.api, "build_preview", fake_build_preview)
    monkeypatch.setattr(state_mod.api, "export", fake_export)

    for action in (
        lambda: state.synth_current(),
        lambda: state.synth_segment(0),
        lambda: state.synth_all(),
        lambda: state.preview_current(),
        lambda: state.preview_deck(),
        lambda: state.export(tmp_path / "out.mp4"),
    ):
        captured.clear()
        action()
        assert captured.get("engine", "MISSING") in (None, "MISSING"), (
            f"action pinned engine={captured.get('engine')!r} instead of "
            "deferring to on-disk config"
        )


def test_has_narration(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    assert state.has_narration("intro-title")
    assert not state.has_narration("euler-setup")


def test_generation_target_helpers(tmp_path: Path) -> None:
    """all_targets / targets_for_sweep / targets_for_slide back the job queue and
    auto-build: every clip is uncached in a fresh deck, with the right exclusions."""
    state = _state(tmp_path, sidecar="@intro-title\nHello. [pause 1] World.\n\n@euler-setup\nHi.\n")
    everything = {("intro-title", 0), ("intro-title", 1), ("euler-setup", 0)}

    assert state.all_targets() == everything
    assert state.all_targets(only_id="euler-setup") == {("euler-setup", 0)}

    # nothing is cached yet, so the sweep is the whole deck minus any exclusion
    assert state.targets_for_sweep() == everything
    assert state.targets_for_sweep(exclude_id="intro-title") == {("euler-setup", 0)}

    # per-slide, with the mid-edit utterance skippable
    assert state.targets_for_slide("intro-title") == {("intro-title", 0), ("intro-title", 1)}
    assert state.targets_for_slide("intro-title", exclude_speech=1) == {("intro-title", 0)}


def test_status_ready_for_narrated_slide(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    assert state.status_for("intro-title") == "ready"


def test_status_empty_for_unnarrated_slide(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    # missing-narration alone reads as "empty", not as a warning
    assert state.status_for("euler-setup") == "empty"


def test_status_warning_for_auto_id(tmp_path: Path) -> None:
    state = _state(tmp_path)
    auto = [p for p in state.deck.pages if p.startswith("auto-")]
    assert auto, "fixture should contain auto-* pages"
    assert state.status_for(auto[0]) == "warning"


def test_status_error_for_orphan_block(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@no-such-page\nGhost.\n")
    assert state.status_for("no-such-page") == "error"


@pytest.mark.parametrize("sidecar", ["", "@intro-title\nHello.\n"])
def test_statuses_cover_all_pages(tmp_path: Path, sidecar: str) -> None:
    state = _state(tmp_path, sidecar=sidecar)
    for sid in state.deck.pages:
        assert state.status_for(sid) in {"error", "warning", "ready", "empty"}


def test_uncached_count_counts_speech_segments(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello. [pause 1] World.\n")
    assert state.uncached_count("intro-title") == 2  # nothing synthesized yet
    assert state.uncached_count("euler-setup") == 0  # no narration at all
    assert state.uncached_total() == 2


def test_tts_is_paid_default_kokoro(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.tts_is_paid is False


def test_tts_is_realtime_flags_heavy_local_engine(tmp_path: Path) -> None:
    """Kokoro is realtime; Qwen3 is free but slow — the flag drives prioritization
    and the tooltip hint, not the auto-build gate (which is paid-only)."""
    assert _state(tmp_path).tts_is_realtime is True  # kokoro default

    (tmp_path / "slidesonnet.toml").write_text('[tts]\nbackend = "qwen3"\n', encoding="utf-8")
    qwen3 = EditorState(prep_marked_deck(tmp_path))
    assert qwen3.tts_is_paid is False  # free → auto-build allowed
    assert qwen3.tts_is_realtime is False  # but slow → nearby slides generated first


def test_gui_engine_pick_repoints_cost_gates(tmp_path: Path) -> None:
    """A session engine pick re-points the cost/realtime gates, with no config or
    sidecar edit.

    The per-utterance picker is engine-independent (named voices only), so it stays
    empty for a deck with no names regardless of the pick — engine voice lists live
    in the Voices dialog (see ``engine_voice_choices``)."""
    state = _state(tmp_path)
    assert state.active_backend == "kokoro"
    assert state.tts_is_paid is False
    assert state.voice_options() == []  # named-only, engine-independent

    state.set_backend("inworld")
    assert state.active_backend == "inworld"
    assert state.tts_is_paid is True  # paid gate follows the pick
    assert state.voice_options() == []  # still engine-independent

    state.set_backend("qwen3")
    assert state.tts_is_paid is False
    assert state.tts_is_realtime is False  # free but auto-build-gated

    # The pick is session-only — nothing written to disk.
    assert not (tmp_path / "slidesonnet.toml").exists()


def test_jobs_context_uses_the_session_selected_backend(tmp_path: Path) -> None:
    """The background queue must look up the cache under the *picked* engine, not the
    on-disk default.

    Otherwise clips cached under one engine (e.g. Kokoro .wavs) make the picked
    engine's audio look already-present, so ``enqueue`` skips every clip — the
    filmstrip shows N missing while the queue reports "queued 0".
    """
    state = _state(tmp_path)
    assert state.active_backend == "kokoro"
    _deck, cfg, _audio = state.jobs_context()
    assert cfg.tts.backend == "kokoro"

    state.set_backend("qwen3")
    _deck, cfg, _audio = state.jobs_context()
    assert cfg.tts.backend == "qwen3"  # follows the session pick, like the sweep does


def test_editing_an_utterance_prunes_stale_local_audio(tmp_path: Path) -> None:
    """An edit drops the just-orphaned local clip but keeps paid audio.

    Local engines are cheap to regenerate, so the editor reclaims a clip the
    moment its utterance text changes; Inworld audio (paid) is never swept.
    """
    from slidesonnet.cache import audio_dir
    from slidesonnet.hashing import audio_filename
    from slidesonnet.narration.model import Segment

    state = _state(tmp_path, "@intro-title\nOriginal narration line.")
    ad = audio_dir(state.pdf_path)
    ad.mkdir(parents=True, exist_ok=True)
    stale = audio_filename("Original narration line.", "kokoro", "kokoro:am_echo")
    paid = audio_filename("Original narration line.", "inworld", "inworld:v")
    (ad / stale).write_bytes(b"a")
    (ad / paid).write_bytes(b"b")

    assert state.replace_block([Segment.speech("Rewritten line entirely.")])

    assert not (ad / stale).exists()  # old local clip auto-pruned on save
    assert (ad / paid).exists()  # paid audio retained


def _voice_map_sidecar() -> str:
    return (
        "# slidesonnet-format: 2\n"
        "default-voice: lecturer\n"
        "voices:\n"
        "  lecturer:\n"
        "    kokoro: am_michael\n"
        "  guest:\n"
        "    kokoro: af_bella\n"
        "\n"
        "@intro-title\n"
        "  utterance:\n"
        "    voice: guest\n"
        "    text: Hello.\n"
    )


def test_editor_voice_options_list_only_named_voices(tmp_path: Path) -> None:
    """The per-utterance picker offers the deck's named voices only — no raw engine ids.

    An utterance references a portable name; the engine voice is resolved through
    the map. Raw ids (am_echo, af_heart, ...) would re-pin engine-specific voices
    onto utterances, which is exactly what the named layer exists to avoid.
    """
    from slidesonnet.tts.kokoro import KOKORO_VOICES

    pdf = prep_marked_deck(tmp_path)
    (tmp_path / "marked.narration").write_text(_voice_map_sidecar(), encoding="utf-8")
    state = EditorState(pdf)

    opts = state.voice_options()
    assert opts == ["guest", "lecturer"]  # named voices only, sorted
    assert not any(v in opts for v in KOKORO_VOICES)  # engine ids never offered here


def test_editor_voice_options_empty_without_named_voices(tmp_path: Path) -> None:
    """A deck with no named voices (e.g. a plain lecture deck) offers an empty list.

    The picker then has only 'default'; the user defines names in the Voices dialog.
    """
    assert _state(tmp_path, "@intro-title\nHello.").voice_options() == []


def test_editor_surfaces_voice_unmapped_for_active_engine(tmp_path: Path) -> None:
    """A named voice with no mapping for the *picked* engine lights its slide."""
    pdf = prep_marked_deck(tmp_path)
    # 'guest' maps for kokoro only; the slide narrates with voice: guest
    (tmp_path / "marked.narration").write_text(_voice_map_sidecar(), encoding="utf-8")
    state = EditorState(pdf)

    def voice_warnings() -> list[str]:
        return [d.slide_id or "" for d in state.all_diagnostics() if d.code == "voice-unmapped"]

    # kokoro: guest is mapped -> no warning, the slide reads ready
    assert voice_warnings() == []
    assert state.status_for("intro-title") == "ready"

    # pick an engine 'guest' has no voice for -> the warning lights that slide
    state.set_backend("inworld")
    assert voice_warnings() == ["intro-title"]
    assert state.status_for("intro-title") == "warning"
    assert any("guest" in d.message for d in state.diagnostics_for_current())

    # back to kokoro -> the warning clears (tracks the engine pick)
    state.set_backend("kokoro")
    assert voice_warnings() == []


def test_resolved_engine_voice_follows_the_active_engine(tmp_path: Path) -> None:
    """A named voice resolves to the active engine's voice id (None when unmapped)."""
    pdf = prep_marked_deck(tmp_path)
    (tmp_path / "marked.narration").write_text(_voice_map_sidecar(), encoding="utf-8")
    state = EditorState(pdf)
    assert state.resolved_engine_voice("lecturer") == "am_michael"  # kokoro mapping
    assert state.resolved_engine_voice("guest") == "af_bella"

    state.set_backend("inworld")
    assert state.resolved_engine_voice("lecturer") is None  # no inworld mapping


def test_editor_default_voice_label_is_the_named_default_only(tmp_path: Path) -> None:
    """The unset-voice label shows the deck's *named* default; never a raw engine id.

    With a named ``default-voice`` it returns that name; with none, it returns None
    (the picker then says "deck default" instead of leaking the engine's voice id).
    """
    pdf = prep_marked_deck(tmp_path)
    (tmp_path / "marked.narration").write_text(_voice_map_sidecar(), encoding="utf-8")
    assert EditorState(pdf).default_voice_label() == "lecturer"

    assert _state(tmp_path, "@intro-title\nHello.").default_voice_label() is None


# ---- editing the voice map in the editor (Now #2) ----------------------------


def test_engine_voice_choices_lists_voices_and_default(tmp_path: Path) -> None:
    """The Voices dialog gets a per-engine (voices, default): a list for Kokoro/Qwen3,
    free text for a cloud engine (Inworld) with account-specific voice ids."""
    from slidesonnet.tts.kokoro import KOKORO_VOICES

    state = _state(tmp_path)
    kokoro_opts, kokoro_default = state.engine_voice_choices("kokoro")
    assert kokoro_opts == list(KOKORO_VOICES)
    assert kokoro_default == "am_echo"  # the configured Kokoro default

    qwen_opts, qwen_default = state.engine_voice_choices("qwen3")
    assert "Dylan" in qwen_opts and qwen_default == "Dylan"  # CustomVoice speakers

    inworld_opts, _ = state.engine_voice_choices("inworld")
    assert inworld_opts == []  # account-specific ids, no fixed list → free text


def test_edit_voices_adds_named_voice_and_persists(tmp_path: Path) -> None:
    """Adding a voice + default writes a v2 preamble and offers the name live."""
    from slidesonnet.models import VoiceConfig

    pdf = prep_marked_deck(tmp_path)
    state = EditorState(pdf)  # no voice map yet
    assert state.deck.voices == {}

    wrote = state.edit_voices(
        {"lecturer": VoiceConfig("lecturer", {"kokoro": "am_michael"})},
        default_voice="lecturer",
    )
    assert wrote is True

    # the reloaded deck carries the new map + default
    assert state.deck.voices["lecturer"].backend_voices == {"kokoro": "am_michael"}
    assert state.deck.default_voice == "lecturer"
    # ...serialized as a portable v2 preamble
    text = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "# slidesonnet-format: 2" in text
    assert "default-voice: lecturer" in text
    assert "kokoro: am_michael" in text
    # ...and the editor offers it as a name + as the unset-voice placeholder
    assert "lecturer" in state.voice_options()
    assert state.default_voice_label() == "lecturer"


def test_edit_voices_unchanged_map_is_a_byte_stable_noop(tmp_path: Path) -> None:
    """Re-applying the displayed map untouched neither writes nor churns the file."""
    pdf = prep_marked_deck(tmp_path)
    (tmp_path / "marked.narration").write_text(_voice_map_sidecar(), encoding="utf-8")
    state = EditorState(pdf)
    before = (tmp_path / "marked.narration").read_text(encoding="utf-8")

    wrote = state.edit_voices(state.voice_map_for_display(), state.deck.default_voice)
    assert wrote is False
    assert (tmp_path / "marked.narration").read_text(encoding="utf-8") == before


def test_edit_voices_clears_voice_unmapped_warning(tmp_path: Path) -> None:
    """Mapping a name for the active engine relights its slide green."""
    pdf = prep_marked_deck(tmp_path)
    (tmp_path / "marked.narration").write_text(_voice_map_sidecar(), encoding="utf-8")
    state = EditorState(pdf)
    state.set_backend("inworld")  # 'guest' has no inworld voice
    assert any(d.code == "voice-unmapped" for d in state.all_diagnostics())

    voices = state.voice_map_for_display()
    voices["guest"].backend_voices["inworld"] = "IW_guest"
    state.edit_voices(voices, state.deck.default_voice)

    # the warning clears, and the mapping is on disk
    assert not any(d.code == "voice-unmapped" for d in state.all_diagnostics())
    assert "inworld: IW_guest" in (tmp_path / "marked.narration").read_text(encoding="utf-8")


def test_edit_voices_deletes_a_voice(tmp_path: Path) -> None:
    pdf = prep_marked_deck(tmp_path)
    (tmp_path / "marked.narration").write_text(_voice_map_sidecar(), encoding="utf-8")
    state = EditorState(pdf)

    voices = state.voice_map_for_display()
    del voices["guest"]
    assert state.edit_voices(voices, state.deck.default_voice) is True

    assert "guest" not in state.deck.voices
    assert "guest:" not in (tmp_path / "marked.narration").read_text(encoding="utf-8")


def test_edit_voices_qwen3_path_roundtrips_relative(tmp_path: Path) -> None:
    """A qwen3 .pt is stored relative on disk but absolute in memory for the engine."""
    from slidesonnet.models import VoiceConfig

    pdf = prep_marked_deck(tmp_path)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "lecturer.pt").write_bytes(b"fake-clone")
    state = EditorState(pdf)

    state.edit_voices(
        {"lecturer": VoiceConfig("lecturer", {"qwen3": "prompts/lecturer.pt"})},
        default_voice="lecturer",
    )
    # on disk: the portable relative path
    assert "qwen3: prompts/lecturer.pt" in (tmp_path / "marked.narration").read_text(
        encoding="utf-8"
    )
    # in memory after reload: absolute, so the engine loads it regardless of cwd
    assert Path(state.deck.voices["lecturer"].backend_voices["qwen3"]).is_absolute()
    # display relativizes again, and re-applying it is a byte-stable no-op
    disp = state.voice_map_for_display()
    assert disp["lecturer"].backend_voices["qwen3"] == "prompts/lecturer.pt"
    assert state.edit_voices(disp, "lecturer") is False


def test_model_warmup_pending_only_for_cold_heavy_engine(tmp_path: Path) -> None:
    """Light engines are always warm; a cold Qwen3 owes a heavy one-time load."""
    state = _state(tmp_path)
    assert state.active_backend == "kokoro"
    assert state.model_warmup_pending() is False  # nothing to load

    state.set_backend("qwen3")
    assert state.model_warmup_pending() is True  # model not yet in the process


def test_est_gen_seconds_scales_with_engine_rtf(tmp_path: Path) -> None:
    """The clip-time estimate grows with text length and the engine's real-time factor."""
    sidecar = "@intro-title\nThis is a fairly long sentence with quite a few words in it.\n"
    state = _state(tmp_path, sidecar=sidecar)
    fast = state.est_gen_seconds("intro-title", 0)
    state.set_backend("qwen3")
    slow = state.est_gen_seconds("intro-title", 0)
    assert fast is not None and slow is not None
    assert slow > fast  # qwen3 (~3.3x) is far slower per audio second than kokoro (~0.3x)
    assert state.est_gen_seconds("intro-title", 9) is None  # no such segment


def test_current_clip_meta_empty_until_generated(tmp_path: Path) -> None:
    """No cached audio yet → no per-clip duration/size to show."""
    state = _state(tmp_path, sidecar="@intro-title\nHello there.\n")
    assert state.current_clip_meta() == {}


def test_warm_active_engine_loads_the_active_backends_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Warming on engine switch delegates to the active engine's warm() (no real load)."""
    from slidesonnet.gui import state as state_mod

    warmed: list[str] = []

    class FakeEngine:
        def __init__(self, name: str) -> None:
            self._name = name

        def warm(self) -> None:
            warmed.append(self._name)

    monkeypatch.setattr(state_mod, "create_tts", lambda cfg: FakeEngine(cfg.backend))

    state = _state(tmp_path)
    state.set_backend("qwen3")
    state.warm_active_engine()
    assert warmed == ["qwen3"]  # warmed the picked engine, not the on-disk default


def test_gui_engine_pick_overrides_action_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With an engine picked, actions pass that engine (the GUI choice wins);
    with nothing picked they pass None (defer to on-disk config)."""
    from slidesonnet.gui import state as state_mod

    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        state_mod.api, "synthesize_deck", lambda pdf, **kw: (captured.update(kw), 0)[1]
    )

    state.synth_current()
    assert captured.get("engine") is None  # no pick → defer to config

    state.set_backend("qwen3")
    captured.clear()
    state.synth_current()
    assert captured.get("engine") == "qwen3"  # pick wins


def test_backend_options_lists_installed_plus_active(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert "kokoro" in state.backend_options()  # installed in the dev env
    # An engine whose package may not be installed is still offered once it's active.
    state.set_backend("qwen3")
    assert "qwen3" in state.backend_options()


def _bump_mtime(path: Path) -> None:
    """Force a visibly newer mtime regardless of filesystem timestamp granularity."""
    later = time.time() + 5
    os.utime(path, (later, later))


def test_poll_sources_false_when_unchanged(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    assert state.poll_sources() is False


def test_poll_sources_picks_up_external_sidecar_edit(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    sidecar = tmp_path / "marked.narration"
    sidecar.write_text(simple_narration("@intro-title\nChanged externally.\n"), encoding="utf-8")
    _bump_mtime(sidecar)
    assert state.poll_sources() is True
    assert "Changed externally." in serialize_body(state.current_block)
    assert state.poll_sources() is False  # baseline refreshed


def test_own_save_does_not_trigger_reload(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    state.replace_block(parse_segments("Edited in the GUI."))
    assert state.poll_sources() is False


def test_pdf_change_invalidates_image_cache(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state._images = [tmp_path / "fake.png"]  # primed cache
    _bump_mtime(tmp_path / "marked.pdf")
    assert state.poll_sources() is True
    assert state._images is None


def test_config_change_reloads_config(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.config.tts.backend == "kokoro"
    (tmp_path / "slidesonnet.toml").write_text('[tts]\nbackend = "inworld"\n', encoding="utf-8")
    assert state.poll_sources() is True
    assert state.config.tts.backend == "inworld"


def test_poll_surfaces_persistent_config_error(tmp_path: Path) -> None:
    """Invalid TOML won't fix itself by waiting — the user needs a signal,
    not an eternal silent retry (the deck keeps its last good config)."""
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    (tmp_path / "slidesonnet.toml").write_text("not = [valid toml", encoding="utf-8")
    assert state.poll_sources() is True  # the UI must refresh to show the error
    assert state.source_error is not None and "TOML" in state.source_error
    assert state.config.tts.backend == "kokoro"  # last good config retained
    assert state.poll_sources() is False  # reported once, not every tick

    (tmp_path / "slidesonnet.toml").write_text('[tts]\nbackend = "kokoro"\n', encoding="utf-8")
    _bump_mtime(tmp_path / "slidesonnet.toml")
    assert state.poll_sources() is True
    assert state.source_error is None  # fixed file clears the report


def test_poll_surfaces_sidecar_grammar_error(tmp_path: Path) -> None:
    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    sidecar = tmp_path / "marked.narration"
    sidecar.write_text("orphan text before any @block\n", encoding="utf-8")
    _bump_mtime(sidecar)
    assert state.poll_sources() is True
    assert state.source_error is not None
    assert "Hello." in serialize_body(state.current_block)  # last good deck retained


def test_reload_reuses_page_ids_when_pdf_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every commit saves + reloads; re-parsing the whole PDF per text-field
    blur stalls the event loop on big decks. Unchanged PDF → cached page ids."""
    from slidesonnet.gui import state as state_mod

    state = _state(tmp_path, sidecar="@intro-title\nHello.\n")
    calls = {"n": 0}
    real_read = state_mod.read_page_ids

    def counting_read(pdf: Path) -> list[str]:
        calls["n"] += 1
        return real_read(pdf)

    monkeypatch.setattr(state_mod, "read_page_ids", counting_read)
    state.replace_block(parse_segments("Edit one."))
    state.replace_block(parse_segments("Edit two."))
    assert calls["n"] == 0  # PDF untouched — commits must not re-open it

    _bump_mtime(tmp_path / "marked.pdf")
    assert state.poll_sources() is True
    assert calls["n"] >= 1  # changed PDF is re-read


# ---- recompiling the deck while the editor is open ------------------------


def _factory_state(tmp_path: Path, ids: list[str], sidecar: str = "") -> EditorState:
    from tests.conftest import write_pdf

    pdf = write_pdf(tmp_path / "deck.pdf", ids)
    if sidecar:
        (tmp_path / "deck.narration").write_text(simple_narration(sidecar), encoding="utf-8")
    return EditorState(pdf)


def _recompile(state: EditorState, ids: list[str]) -> None:
    from tests.conftest import write_pdf

    write_pdf(state.pdf_path, ids)
    _bump_mtime(state.pdf_path)


def test_poll_detects_same_mtime_size_change(tmp_path: Path) -> None:
    """Repro #2: a recompile the filesystem reports with an unchanged mtime
    (coarse-granularity mounts, same-second rebuilds) must still be detected —
    a size change gives it away. Mtime-only watching missed these entirely."""
    from tests.conftest import write_pdf

    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n\n@b\nBye.\n")
    pdf = state.pdf_path
    baseline_mtime = pdf.stat().st_mtime
    old_size = pdf.stat().st_size

    write_pdf(pdf, ["a", "b", "c"])  # recompile: a third slide changes the byte size
    os.utime(pdf, (baseline_mtime, baseline_mtime))  # pin mtime so only size differs
    assert pdf.stat().st_size != old_size, "sanity: the recompile changed the file size"
    assert pdf.stat().st_mtime == baseline_mtime, "sanity: mtime is unchanged"

    assert state.poll_sources() is True
    assert state.page_count == 3


def test_recompile_added_slide_flags_missing_narration(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n\n@b\nBye.\n")
    assert state.error_count == 0
    _recompile(state, ["a", "b", "c"])
    assert state.poll_sources() is True
    assert state.page_count == 3
    assert any(d.code == "missing-narration" and d.slide_id == "c" for d in state.diagnostics)


def test_recompile_renamed_slide_yields_orphan_error(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n\n@b\nBye.\n")
    _recompile(state, ["a", "b-renamed"])
    assert state.poll_sources() is True
    assert any(d.code == "orphan-narration" and d.slide_id == "b" for d in state.diagnostics)
    assert state.status_for("b") == "error"


def test_recompile_shrunk_deck_clamps_index(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b", "c"])
    state.go(2)
    _recompile(state, ["a"])
    assert state.poll_sources() is True
    assert state.index == 0
    assert state.current_id == "a"


def test_poll_survives_pdf_missing_mid_recompile(tmp_path: Path) -> None:
    # latexmk deletes/rewrites the PDF; a poll tick in that window must not crash
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n")
    state.pdf_path.unlink()
    assert state.poll_sources() is False  # keeps showing the last good deck
    assert state.page_count == 2
    _recompile(state, ["a", "b", "c"])  # compile finished
    assert state.poll_sources() is True
    assert state.page_count == 3


def test_poll_survives_partially_written_pdf(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n")
    state.pdf_path.write_bytes(b"%PDF-1.5 garbage truncated")
    _bump_mtime(state.pdf_path)
    assert state.poll_sources() is False  # unreadable: keep last good deck, retry next tick
    assert state.page_count == 2
    _recompile(state, ["a", "b"])
    assert state.poll_sources() is True


def test_poll_survives_malformed_config_edit(tmp_path: Path) -> None:
    # a half-saved slidesonnet.toml must not crash the poll loop: the error is
    # reported (not silently retried forever) and clears once the file is fixed
    state = _factory_state(tmp_path, ["a"], sidecar="@a\nHi.\n")
    cfg = tmp_path / "slidesonnet.toml"
    cfg.write_text("[tts\nbackend = ", encoding="utf-8")
    _bump_mtime(cfg)
    assert state.poll_sources() is True
    assert state.source_error is not None
    cfg.write_text('[tts]\nbackend = "kokoro"\n', encoding="utf-8")
    _bump_mtime(cfg)
    assert state.poll_sources() is True
    assert state.source_error is None


def test_duplicate_blocks_are_disambiguated_not_frozen(tmp_path: Path) -> None:
    # a repeated @a is renamed (a -> a-2) on load so neither block's text is lost;
    # editing an unrelated slide is no longer frozen, and a rewrite keeps both
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nFirst.\n\n@a\nSecond.\n\n@b\nBye.\n")
    assert "a-2" in state.deck.narration  # the second @a block was disambiguated
    state.go(1)  # onto slide b
    assert state.replace_block(parse_segments("edited b")) is True
    text = (tmp_path / "deck.narration").read_text(encoding="utf-8")
    assert "First." in text and "Second." in text  # both blocks preserved
    assert "edited b" in text


def test_save_returns_true_on_normal_write(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a"], sidecar="@a\nHi.\n")
    assert state.replace_block(parse_segments("Hello.")) is True
    assert "Hello." in (tmp_path / "deck.narration").read_text(encoding="utf-8")


def test_save_on_unmarked_page_is_a_safe_noop(tmp_path: Path) -> None:
    # an empty slide-id can't be keyed in the sidecar; writing "@" would corrupt it
    state = _factory_state(tmp_path, ["a", "", "b"], sidecar="@a\nHi.\n")
    state.go(1)
    assert state.current_id == ""
    assert state.replace_block(parse_segments("typed on an unmarked page")) is False
    text = (tmp_path / "deck.narration").read_text(encoding="utf-8")
    assert "typed on an unmarked page" not in text
    state.reload()  # the sidecar must still parse
    assert state.deck.page_narration("a").speech_text == "Hi."


# ---- unattached narration (slide dropped/renamed by a recompile) ------------


def test_orphan_blocks_lists_blocks_without_pages(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a"], sidecar="@a\nHi.\n\n@ghost\nLost text.\n")
    orphans = state.orphan_blocks()
    assert [b.slide_id for b in orphans] == ["ghost"]
    assert orphans[0].speech_text == "Lost text."


def test_orphan_blocks_empty_when_reconciled(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a"], sidecar="@a\nHi.\n")
    assert state.orphan_blocks() == []


def test_unnarrated_pages_lists_candidates(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b", "c"], sidecar="@a\nHi.\n\n@b\n")
    assert state.unnarrated_pages() == ["b", "c"]  # empty block counts as un-narrated


def test_attach_orphan_moves_narration_to_page(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n\n@ghost\nLost text.\n")
    state.attach_orphan("ghost", "b")
    assert state.orphan_blocks() == []
    assert state.deck.page_narration("b").speech_text == "Lost text."
    sidecar = (tmp_path / "deck.narration").read_text(encoding="utf-8")
    assert "Lost text." in sidecar
    assert "@ghost" not in sidecar
    assert state.error_count == 0  # orphan error resolved


def test_attach_orphan_refuses_narrated_target(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a"], sidecar="@a\nHi.\n\n@ghost\nLost text.\n")
    with pytest.raises(ValueError, match="already has narration"):
        state.attach_orphan("ghost", "a")
    with pytest.raises(ValueError, match="not a page"):
        state.attach_orphan("ghost", "nope")


def test_append_orphan_to_current_merges_segments(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nKeep me.\n\n@ghost\nLost text.\n")
    state.go(0)  # current slide is 'a', which already has narration
    state.append_orphan_to_current("ghost")
    assert state.orphan_blocks() == []
    # the orphan's text is appended after the slide's existing narration
    assert state.deck.page_narration("a").speech_text == "Keep me. Lost text."
    sidecar = (tmp_path / "deck.narration").read_text(encoding="utf-8")
    assert "Keep me." in sidecar and "Lost text." in sidecar and "@ghost" not in sidecar
    assert state.error_count == 0  # orphan error resolved


def test_append_orphan_to_current_refuses_unmarked_page(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "", "b"], sidecar="@a\nHi.\n\n@ghost\nLost.\n")
    state.go(1)  # the unmarked page has no slide-id to append onto
    with pytest.raises(ValueError, match="no slide-id"):
        state.append_orphan_to_current("ghost")


def test_delete_orphan_removes_block(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a"], sidecar="@a\nHi.\n\n@ghost\nLost text.\n")
    state.delete_orphan("ghost")
    assert state.orphan_blocks() == []
    assert "Lost text." not in (tmp_path / "deck.narration").read_text(encoding="utf-8")


def test_external_changes_reports_which_sources_moved(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n")
    assert state.external_changes() == set()
    _bump_mtime(state.pdf_path)
    assert state.external_changes() == {"pdf"}


def test_save_does_not_mask_concurrent_pdf_change(tmp_path: Path) -> None:
    # a recompile lands, then the GUI saves before the next poll: the reload
    # must still happen (save refreshes only the sidecar baseline)
    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n")
    _recompile(state, ["a", "b", "c"])
    state.replace_block(parse_segments("Hi there."))
    assert state.poll_sources() is True
    assert state.page_count == 3


# ---- structured block editing (replace_block + transitions) ----------------


def test_replace_block_persists_mixed_segments(tmp_path: Path) -> None:
    from slidesonnet.narration.model import Segment

    state = _factory_state(tmp_path, ["a"])
    ok = state.replace_block(
        [
            Segment.speech("Hello.", voice="af_bella", pace="slow", direction="warm"),
            Segment.pause(1.5),
            Segment.speech("Goodbye."),
        ]
    )
    assert ok
    block = state.current_block
    assert [s.kind for s in block.segments] == ["speech", "pause", "speech"]
    assert block.segments[0].voice == "af_bella"
    assert block.segments[0].pace == "slow"
    assert block.segments[0].direction == "warm"
    # survives a reload from disk
    state.reload()
    assert state.current_block.segments[0].direction == "warm"


def test_replace_block_empty_clears_the_text(tmp_path: Path) -> None:
    state = _factory_state(tmp_path, ["a"], sidecar="@a\nHi.\n")
    assert state.replace_block([]) is True
    assert state.current_block.is_silent  # bare @a header may remain, but no content
    assert "Hi." not in (tmp_path / "deck.narration").read_text(encoding="utf-8")


def test_set_transition_out_clears_next_slide_in(tmp_path: Path) -> None:
    from slidesonnet.narration.model import Segment, Transition

    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n\n@b\nBye.\n")
    # b initially carries a transition-in; setting a's transition-out normalizes it away
    state.go(1)
    state.replace_block([Segment.speech("Bye.")], transition_in=Transition("crossfade", 0.4))
    state.go(0)
    state.replace_block([Segment.speech("Hi.")], transition_out=Transition("crossfade", 0.5))
    assert state.deck.page_narration("a").transition_out == Transition("crossfade", 0.5)
    assert state.deck.page_narration("b").transition_in == Transition()  # cleared
    assert not any(d.code == "transition-conflict" for d in state.diagnostics)


def test_incoming_transition_mirrors_previous_slide_out(tmp_path: Path) -> None:
    """A slide's incoming transition is its boundary with the previous slide, so
    it always equals that slide's outgoing transition (the bug: they disagreed)."""
    from slidesonnet.narration.model import Segment, Transition

    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n\n@b\nBye.\n")
    state.replace_block([Segment.speech("Hi.")], transition_out=Transition("wipeleft", 0.5))
    state.go(1)  # move to b
    assert state.incoming_transition == Transition("wipeleft", 0.5)  # matches a's out
    assert state.current_block.transition_in == Transition()  # not duplicated on b


def test_editing_incoming_transition_writes_to_previous_slide_out(tmp_path: Path) -> None:
    """Editing a slide's 'in' edits the one boundary — stored on the previous
    slide's 'out' — so the two faces never drift apart."""
    from slidesonnet.narration.model import Segment, Transition

    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n\n@b\nBye.\n")
    state.go(1)  # on b, set its incoming transition to a fade
    assert (
        state.replace_block([Segment.speech("Bye.")], transition_in=Transition("fade", 0.7)) is True
    )
    assert state.deck.page_narration("a").transition_out == Transition("fade", 0.7)  # the boundary
    assert state.deck.page_narration("b").transition_in == Transition()  # stays cut on b
    assert state.incoming_transition == Transition("fade", 0.7)
    assert not any(d.code == "transition-conflict" for d in state.diagnostics)


def test_first_slide_keeps_its_own_incoming_transition(tmp_path: Path) -> None:
    """The deck's first slide has no previous, so its 'in' is its own (deck open)."""
    from slidesonnet.narration.model import Segment, Transition

    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n")
    assert (
        state.replace_block([Segment.speech("Hi.")], transition_in=Transition("fadeblack", 0.6))
        is True
    )
    assert state.current_block.transition_in == Transition("fadeblack", 0.6)
    assert state.incoming_transition == Transition("fadeblack", 0.6)


def test_unchanged_incoming_does_not_rewrite_the_sidecar(tmp_path: Path) -> None:
    """Re-saving a slide without touching its incoming transition is a no-op — it
    must not migrate an externally-authored transition-in or flash 'saved'."""
    from slidesonnet.narration.model import Segment, Transition

    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nHi.\n\n@b\nBye.\n")
    state.replace_block([Segment.speech("Hi.")], transition_out=Transition("slideup", 0.5))
    state.go(1)
    before = (tmp_path / "deck.narration").read_text(encoding="utf-8")
    # autosave on b with the same (effective) incoming value the editor showed
    assert (
        state.replace_block([Segment.speech("Bye.")], transition_in=state.incoming_transition)
        is False
    )
    assert (tmp_path / "deck.narration").read_text(encoding="utf-8") == before


def test_replace_block_succeeds_despite_duplicate_blocks(tmp_path: Path) -> None:
    from slidesonnet.narration.model import Segment

    state = _factory_state(tmp_path, ["a", "b"], sidecar="@a\nFirst.\n\n@a\nSecond.\n\n@b\nBye.\n")
    # writes are no longer frozen by a duplicate elsewhere in the file
    assert state.replace_block([Segment.speech("edited a")]) is True


def test_cue_start_finds_slide() -> None:
    cues = [(0.0, "a"), (3.5, "b"), (9.0, "c")]
    assert cue_start(cues, "b") == 3.5
    assert cue_start(cues, "a") == 0.0
    assert cue_start(cues, "zzz") is None


# ---- non-destructive save (hand-edited sidecars survive GUI saves) ---------

HAND_EDITED = """\
# lecture notes — keep the pacing relaxed

@a
  utterance:
    text: Hello from slide a,
      wrapped by hand.

# slide b is the punchline
@b
  utterance:
    text: Bye.
"""


def _hand_edited_state(tmp_path: Path) -> EditorState:
    from tests.conftest import write_pdf

    pdf = write_pdf(tmp_path / "deck.pdf", ["a", "b"])
    (tmp_path / "deck.narration").write_text(HAND_EDITED, encoding="utf-8")
    return EditorState(pdf)


def test_no_change_save_is_a_noop(tmp_path: Path) -> None:
    from slidesonnet.narration.model import Segment

    state = _hand_edited_state(tmp_path)
    # an autosave that changes nothing (the GUI fires these on blur/navigation):
    # it must report "unchanged" so callers don't flash "saved" or revoke a
    # playing preview, and it must leave the hand-edited file byte-identical.
    block = state.current_block
    assert not state.replace_block(
        list(block.segments),
        transition_in=block.transition_in,
        transition_out=block.transition_out,
    )
    assert (tmp_path / "deck.narration").read_text(encoding="utf-8") == HAND_EDITED
    assert isinstance(block.segments[0], Segment)  # sanity: we round-tripped real content


def test_editing_one_block_leaves_the_other_raw(tmp_path: Path) -> None:
    from slidesonnet.narration.model import Segment

    state = _hand_edited_state(tmp_path)
    state.go(1)
    state.replace_block([Segment.speech("Goodbye, rewritten.")])
    text = (tmp_path / "deck.narration").read_text(encoding="utf-8")
    # slide a keeps its hand wrapping and the file header comment
    assert "# lecture notes — keep the pacing relaxed\n" in text
    assert "    text: Hello from slide a,\n      wrapped by hand.\n" in text
    # the comment above the edited block survives, the body is canonical
    assert "# slide b is the punchline\n@b\n  utterance:\n    text: Goodbye, rewritten.\n" in text
