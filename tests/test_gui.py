"""GUI editor tests via NiceGUI's in-process user simulation."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from slidesonnet import api
from tests.conftest import prep_marked_deck as _prep, simple_narration

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"

pytestmark = pytest.mark.nicegui_main_file("tests/gui_main.py")


@pytest.fixture(autouse=True)
def _reset_auto_build_storage() -> Iterator[None]:
    """app.storage.general is process-global — clear the auto-build flag between
    tests so one test enabling it can't leak into another."""
    from nicegui import app

    app.storage.general.pop("auto_build", None)
    yield
    app.storage.general.pop("auto_build", None)


async def test_editor_loads(user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _prep(tmp_path)
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("intro-title")
    await user.should_see("Slide 1 / 6")


def test_morph_schedule_emits_only_animated_boundaries() -> None:
    from slidesonnet.audio.track import Cue
    from slidesonnet.gui.app import _morph_schedule
    from slidesonnet.narration.model import Deck, PageNarration, Transition

    deck = Deck(
        pdf_path=Path("d.pdf"),
        sidecar_path=Path("d.narration"),
        pages=["a", "b", "c"],
        narration={
            "a": PageNarration(slide_id="a", transition_out=Transition("wipeleft", 0.5)),
            "b": PageNarration(slide_id="b"),  # plain cut into c
            "c": PageNarration(slide_id="c"),
        },
    )
    cues = [Cue(0.0, "a"), Cue(4.0, "b"), Cue(7.0, "c")]
    images = [Path("a.png"), Path("b.png"), Path("c.png")]

    sched = _morph_schedule(cues, deck, images, lambda p: f"/u/{p.name}")

    assert len(sched) == 1  # only the a→b wipe; b→c is a cut
    (step,) = sched
    assert step["kind"] == "wipeleft"
    assert step["at"] == 4.0  # morph completes at the destination's cue start
    assert step["dur"] == 0.5
    assert step["from"] == "/u/a.png"
    assert step["to"] == "/u/b.png"


def test_morph_schedule_clamps_duration_to_slide_span() -> None:
    from slidesonnet.audio.track import Cue
    from slidesonnet.gui.app import _morph_schedule
    from slidesonnet.narration.model import Deck, PageNarration, Transition

    deck = Deck(
        pdf_path=Path("d.pdf"),
        sidecar_path=Path("d.narration"),
        pages=["a", "b"],
        narration={"a": PageNarration(slide_id="a", transition_out=Transition("fade", 3.0))},
    )
    cues = [Cue(0.0, "a"), Cue(1.0, "b")]  # outgoing slide only spans 1s
    images = [Path("a.png"), Path("b.png")]

    (step,) = _morph_schedule(cues, deck, images, lambda p: p.name)

    assert step["dur"] == 1.0  # clamped to the span, never morphs over the boundary


async def test_navigation(user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _prep(tmp_path)
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    user.find("Next").click()
    await user.should_see("euler-setup")
    await user.should_see("Slide 2 / 6")


async def test_filmstrip_jump(user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _prep(tmp_path)
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    user.find(marker="thumb-2").click()  # filmstrip jump straight to slide 3
    await user.should_see("Slide 3 / 6")


async def test_in_panel_collapse_buttons(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path)
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    strip = next(iter(user.find(marker="split-strip").elements))
    console = next(iter(user.find(marker="split-console").elements))
    assert isinstance(strip, ui.splitter) and isinstance(console, ui.splitter)
    assert strip.value > 0 and console.value > 0
    user.find(marker="collapse-strip").click()
    assert strip.value == 0
    user.find(marker="collapse-console").click()
    assert console.value == 0
    # the persistent header toggles bring the panes back at their default widths
    user.find(marker="toggle-strip").click()
    user.find(marker="toggle-console").click()
    assert strip.value > 0 and console.value > 0


async def test_edit_persists(user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _prep(tmp_path)
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    # empty slide: add a spoken line, type into it, then add a pause block
    user.find(marker="add-utterance").click()
    user.find(ui.textarea).type("Hello deck.")
    user.find(marker="add-pause").click()
    user.find("Next").click()  # nav saves the current slide first
    sidecar = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "@intro-title" in sidecar
    assert "text: Hello deck." in sidecar
    assert "pause: 1" in sidecar  # default pause length


async def test_transition_picker_family_and_direction_persist(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    # pick a family from the short Type list, then a direction; the stored name
    # is the recomposed flat xfade name (wipe + Up -> wipeup).
    next(iter(user.find(marker="trans-out").elements)).set_value("wipe")
    next(iter(user.find(marker="trans-out-dir").elements)).set_value("Up")
    user.find("Next").click()  # nav saves the current slide first
    sidecar = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "transition-out: wipeup 0.5" in sidecar


async def test_per_utterance_voice_and_pace_persist(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    # the utterance's options carry voice (chosen from the engine's set), pace, note
    next(iter(user.find(marker="uvoice-0").elements)).set_value("af_bella")
    next(iter(user.find(marker="upace-0").elements)).set_value("slow")
    user.find(marker="udirect-0").type("warmly")
    user.find("Next").click()
    sidecar = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "voice: af_bella" in sidecar
    assert "pace: slow" in sidecar
    assert "direct: warmly" in sidecar


async def test_voice_box_shows_deck_default_when_unset(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An utterance with no explicit voice shows the deck default, not an empty box."""
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    (tmp_path / "slidesonnet.toml").write_text(
        '[tts.kokoro]\nvoice = "bm_george"\n', encoding="utf-8"
    )
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    voice = next(iter(user.find(marker="uvoice-0").elements))
    assert voice.value is None  # unset stays unset — the sidecar isn't touched
    assert voice.props.get("placeholder") == "bm_george (default)"


async def test_action_messages_flash_on_the_bottom_bar(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Status messages land in the footer flash area, not as popup pills."""
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    await user.open("/")
    flash = next(iter(user.find(marker="flash").elements))
    assert flash.text == ""  # quiet until something happens

    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    assert "Preview ready" in flash.text  # the message is the footer's, not a popup


async def test_ctrl_s_saves_the_field_being_typed(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl+S commits the field under the cursor without leaving it."""
    pdf = _prep(tmp_path, sidecar="@intro-title\nOld words.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    user.find(ui.textarea).clear().type("Fresh words, mid-edit.")
    user.find(marker="utext-0").trigger("keydown.ctrl.s.prevent")  # no blur, no nav
    sidecar = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "Fresh words, mid-edit." in sidecar


async def test_diagnostics_visible(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path, sidecar="@intro-title\nHi.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    # page 5/6 are auto-* -> warnings; navigate there
    for _ in range(4):
        user.find("Next").click()
    await user.should_see("auto-")


async def test_console_shows_audio_generation_status(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello. [pause 1] World.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("0 of 2 generated")  # two speech segments, nothing cached yet


async def test_console_checks_are_per_slide(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path, sidecar="@intro-title\nHi.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("no issues on this slide")


async def test_recompile_while_editing_updates_deck_live(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import write_pdf

    pdf = write_pdf(tmp_path / "deck.pdf", ["alpha", "beta"])
    (tmp_path / "deck.narration").write_text(
        simple_narration("@alpha\nHi.\n\n@beta\nBye.\n"), encoding="utf-8"
    )
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("Slide 1 / 2")
    # "recompile": the deck gains a slide while the editor is open
    write_pdf(pdf, ["alpha", "beta", "gamma"])
    later = time.time() + 5
    os.utime(pdf, (later, later))
    await user.should_see("Deck files changed on disk — reloaded", retries=300)
    await user.should_see("Slide 1 / 3")
    # the new slide is empty; saving must NOT scaffold a bare @gamma block, which
    # would read back as a (narrated-but-empty) block and hide its missing warning
    user.find(marker="thumb-2").click()
    await user.should_see("Slide 3 / 3")
    await user.should_see("no speech on this slide")
    sidecar = (tmp_path / "deck.narration").read_text(encoding="utf-8")
    assert "@gamma" not in sidecar  # stays unnarrated until it gets real content


@pytest.mark.integration
async def test_generate_and_preview(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    # a SECOND narrated slide stays ungenerated: single-slide preview must not
    # trip over its missing clips (regression: IndexError in page_pieces)
    pdf = _prep(
        tmp_path,
        sidecar="@intro-title\nWelcome to the deck.\n\n@euler-setup\nNot generated yet.\n",
    )
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    from slidesonnet.cache import audio_dir

    user.find(marker="gen-seg-0").click()
    # synthesis runs on the background queue now; wait for the cache file to land
    for _ in range(600):  # up to ~30s for real kokoro
        if any(audio_dir(pdf).glob("*.wav")):
            break
        await asyncio.sleep(0.05)
    assert any(audio_dir(pdf).glob("*.wav"))
    # once the job finishes the queue repaints the button to the re-generate state
    gen = next(iter(user.find(marker="gen-seg-0").elements))
    assert isinstance(gen, ui.button)
    for _ in range(100):
        if gen.props.get("icon") == "autorenew" and gen.enabled:
            break
        await asyncio.sleep(0.05)
    assert gen.props.get("icon") == "autorenew" and gen.enabled
    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)


def _fake_preview(pdf: Path, cues: list[tuple[float, str]]) -> "api.Preview":
    """A ready-made Preview backed by the silence fixture (no TTS, no ffmpeg)."""
    from slidesonnet.cache import render_dir

    rdir = render_dir(pdf)
    rdir.mkdir(parents=True, exist_ok=True)
    track = rdir / "preview.wav"
    track.write_bytes((FIXTURES / "silence.wav").read_bytes())
    return api.Preview(track=track, cues=cues, total_duration=4.0)


async def test_stop_during_preview_build_cancels_playback(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop pressed while the track is still building must win over the play."""
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))

    def slow_build(self: EditorState) -> api.Preview:
        time.sleep(1.0)  # the synthesis window the user interrupts
        return _fake_preview(self.pdf_path, [])

    monkeypatch.setattr(EditorState, "preview_current", slow_build)
    await user.open("/")
    user.find(marker="play-slide").click()
    user.find(marker="stop").click()
    await user.should_see("Preview stopped", retries=300)


async def test_deck_playback_cue_flip_saves_pending_edits(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cue flip during deck preview must not clobber narration typed meanwhile."""
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))

    def instant_build(self: EditorState) -> api.Preview:
        return _fake_preview(self.pdf_path, [(0.0, "intro-title"), (2.0, "euler-setup")])

    monkeypatch.setattr(EditorState, "preview_deck", instant_build)
    await user.open("/")
    user.find(marker="play-deck").click()
    await user.should_see("Preview ready", retries=300)
    user.find(ui.textarea).clear().type("Typed during playback.")
    # the track reaches the second slide's cue: the editor flips the page
    user.find(marker="preview-audio").trigger("timeupdate", args=2.5)
    await user.should_see("Slide 2 / 6")
    sidecar = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "Typed during playback." in sidecar  # saved under @intro-title, not lost


async def test_cue_flip_is_deferred_while_a_field_is_focused(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Playback must not yank the block editor mid-edit; following resumes on blur."""
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))

    def instant_build(self: EditorState) -> api.Preview:
        return _fake_preview(self.pdf_path, [(0.0, "intro-title"), (2.0, "euler-setup")])

    monkeypatch.setattr(EditorState, "preview_deck", instant_build)
    await user.open("/")
    user.find(marker="play-deck").click()
    await user.should_see("Preview ready", retries=300)
    user.find(ui.textarea).trigger("focus")  # the user is mid-edit
    user.find(marker="preview-audio").trigger("timeupdate", args=2.5)
    await user.should_see("Slide 1 / 6")  # flip deferred, editor untouched
    user.find(ui.textarea).trigger("blur")
    user.find(marker="preview-audio").trigger("timeupdate", args=2.6)
    await user.should_see("Slide 2 / 6")  # following resumed after blur


async def test_replaying_preview_reloads_the_new_track(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every preview renders to the same track path; the browser must still refetch.

    Regression: preview slide A, navigate, preview slide B — the audio element
    kept playing A because the source URL was unchanged.
    """
    import asyncio

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    await user.open("/")
    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    audio = next(iter(user.find(marker="preview-audio").elements))
    first = str(audio.props.get("src"))
    assert "preview.wav" in first

    user.find("Next").click()
    user.find(marker="play-slide").click()
    for _ in range(100):  # wait for the second build to land
        if str(audio.props.get("src")) != first:
            break
        await asyncio.sleep(0.05)
    second = str(audio.props.get("src"))
    assert "preview.wav" in second
    assert second != first  # same path, but the browser must see a fresh URL


async def test_stop_then_switch_slides_resets_player(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """play slide 1 → stop → next slide: the player resets; play builds slide 2."""
    import asyncio

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    await user.open("/")
    play_btn = next(iter(user.find(marker="play-slide").elements))
    audio = next(iter(user.find(marker="preview-audio").elements))

    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    assert play_btn.props.get("icon") == "pause"  # transport mirrors the player

    user.find(marker="stop").click()
    assert play_btn.props.get("icon") == "play_arrow"  # reset, not lingering paused

    first = str(audio.props.get("src"))
    user.find("Next").click()
    user.find(marker="play-slide").click()  # must build slide 2, not resume slide 1
    for _ in range(100):
        if str(audio.props.get("src")) != first:
            break
        await asyncio.sleep(0.05)
    assert str(audio.props.get("src")) != first


async def test_play_button_toggles_pause_and_resume(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One transport: the play button pauses/resumes its own track, no rebuild."""
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    await user.open("/")
    play_btn = next(iter(user.find(marker="play-slide").elements))
    audio = next(iter(user.find(marker="preview-audio").elements))

    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    loaded = str(audio.props.get("src"))
    assert play_btn.props.get("icon") == "pause"

    user.find(marker="play-slide").click()  # pause
    assert play_btn.props.get("icon") == "play_arrow"
    assert str(audio.props.get("src")) == loaded  # same track, no rebuild

    user.find(marker="play-slide").click()  # resume
    assert play_btn.props.get("icon") == "pause"
    assert str(audio.props.get("src")) == loaded


async def test_nav_during_single_slide_build_cancels_it(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """play → immediately arrow on: slide 1's audio must not start over slide 2."""
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))

    def slow_build(self: EditorState) -> api.Preview:
        time.sleep(1.0)
        return _fake_preview(self.pdf_path, [])

    monkeypatch.setattr(EditorState, "preview_current", slow_build)
    await user.open("/")
    user.find(marker="play-slide").click()
    user.find("Next").click()
    await user.should_see("Preview stopped", retries=300)


async def test_seek_bar_tracks_position_and_resets_on_stop(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transport shows position/duration and a scrubber; Stop resets both."""
    from nicegui import ui as ngui

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    await user.open("/")
    seek = next(iter(user.find(marker="seek").elements))
    assert isinstance(seek, ngui.slider)
    assert "disable" in seek.props  # nothing loaded yet

    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    await user.should_see("0:00 / 0:04")  # fake preview is 4 seconds long
    assert "disable" not in seek.props

    # the track advances: the scrubber and clock follow
    user.find(marker="preview-audio").trigger("timeupdate", args=2.0)
    await user.should_see("0:02 / 0:04")
    assert seek.value == pytest.approx(0.5)

    user.find(marker="stop").click()
    assert seek.value == 0.0
    assert "disable" in seek.props


async def test_generate_resets_rolling_player(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-generating audio stops a rolling preview and rewinds the transport."""
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    monkeypatch.setattr(EditorState, "speech_cached_flags", lambda self: [True])
    # the queue drives synthesis off the worker — stub it so no real Kokoro runs
    monkeypatch.setattr(EditorState, "synth_targets", lambda self, t, *, force=False: 1)
    await user.open("/")
    play_btn = next(iter(user.find(marker="play-slide").elements))
    seek = next(iter(user.find(marker="seek").elements))

    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    user.find(marker="preview-audio").trigger("timeupdate", args=2.0)
    await user.should_see("0:02 / 0:04")  # mid-run
    assert play_btn.props.get("icon") == "pause"

    # Re-generating the playing slide's clip makes the rolling track stale, so the
    # transport resets at click time (before the background job even finishes).
    user.find(marker="gen-seg-0").click()
    assert play_btn.props.get("icon") == "play_arrow"  # stopped, not lingering paused
    assert seek.value == 0.0  # rewound
    assert "disable" in seek.props


async def test_structural_edit_resets_player(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adding/deleting a segment card changes what should be heard: player resets."""
    import asyncio

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    await user.open("/")
    play_btn = next(iter(user.find(marker="play-slide").elements))
    seek = next(iter(user.find(marker="seek").elements))
    audio = next(iter(user.find(marker="preview-audio").elements))

    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    assert play_btn.props.get("icon") == "pause"

    user.find(marker="add-pause").click()  # mid-run: the audible content just changed
    assert play_btn.props.get("icon") == "play_arrow"
    assert seek.value == 0.0
    assert "disable" in seek.props

    first = str(audio.props.get("src"))
    user.find(marker="play-slide").click()  # must rebuild — the player was reset, not paused
    for _ in range(100):
        if str(audio.props.get("src")) != first:
            break
        await asyncio.sleep(0.05)
    assert str(audio.props.get("src")) != first
    assert play_btn.props.get("icon") == "pause"

    user.find(marker="seg-del-1").click()  # delete the pause card mid-run
    assert play_btn.props.get("icon") == "play_arrow"
    assert "disable" in seek.props


async def test_pause_length_edit_resets_player_so_replay_rebuilds(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing a pause's seconds mid-run changes what should be heard.

    Regression: the edit saved, but the player kept rolling and the old track
    stayed loaded — so replaying resumed the stale audio and the new silence
    was never heard, no matter how many times play was pressed.
    """
    import asyncio

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello. [pause 1] World.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    await user.open("/")
    play_btn = next(iter(user.find(marker="play-slide").elements))
    seek = next(iter(user.find(marker="seek").elements))
    audio = next(iter(user.find(marker="preview-audio").elements))

    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    assert play_btn.props.get("icon") == "pause"

    # mid-run: stretch the silence from 1s to 3s and leave the field
    next(iter(user.find(marker="pause-secs-1").elements)).set_value(3.0)
    user.find(marker="pause-secs-1").trigger("blur")
    sidecar = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "pause: 3" in sidecar  # the edit itself saved
    assert play_btn.props.get("icon") == "play_arrow"  # player stopped...
    assert "disable" in seek.props  # ...and rewound

    first = str(audio.props.get("src"))
    user.find(marker="play-slide").click()  # replay must rebuild, not resume the stale track
    for _ in range(100):
        if str(audio.props.get("src")) != first:
            break
        await asyncio.sleep(0.05)
    assert str(audio.props.get("src")) != first


async def test_pdf_only_refresh_keeps_narration_field(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repro #1: a PDF-only recompile must not rebuild the block editor — that
    would revert whatever the user is mid-typing. The editor (and its live
    textarea) is left intact; only PDF-side surfaces refresh."""
    from tests.conftest import write_pdf

    pdf = write_pdf(tmp_path / "deck.pdf", ["a", "b"])
    (tmp_path / "deck.narration").write_text(
        simple_narration("@a\nHi.\n\n@b\nBye.\n"), encoding="utf-8"
    )
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("Slide 1 / 2")
    before = next(iter(user.find(ui.textarea).elements))

    write_pdf(pdf, ["a", "b"])  # recompile, same ids — narration on disk untouched
    later = time.time() + 5
    os.utime(pdf, (later, later))
    await user.should_see("Deck files changed on disk — reloaded", retries=300)

    after = next(iter(user.find(ui.textarea).elements))
    assert before is after  # same widget → not rebuilt → in-progress typing survives


async def test_text_edit_revokes_loaded_track(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repro #3: editing an utterance's words while a preview is loaded must drop
    the stale track so the next Play rebuilds with the new narration."""
    import asyncio

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    await user.open("/")
    play_btn = next(iter(user.find(marker="play-slide").elements))
    seek = next(iter(user.find(marker="seek").elements))
    audio = next(iter(user.find(marker="preview-audio").elements))

    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    assert play_btn.props.get("icon") == "pause"

    # change the spoken words and leave the field
    user.find(marker="utext-0").clear().type("Completely different words.")
    user.find(marker="utext-0").trigger("blur")
    sidecar = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "Completely different words." in sidecar  # the edit saved
    assert play_btn.props.get("icon") == "play_arrow"  # player stopped...
    assert "disable" in seek.props  # ...and rewound

    first = str(audio.props.get("src"))
    user.find(marker="play-slide").click()  # replay must rebuild, not resume the stale track
    for _ in range(100):
        if str(audio.props.get("src")) != first:
            break
        await asyncio.sleep(0.05)
    assert str(audio.props.get("src")) != first


async def test_no_op_blur_keeps_playing(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard for #3's fix: blurring a field *without* changing it must not stop
    playback (a no-op save reports "unchanged")."""
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    await user.open("/")
    play_btn = next(iter(user.find(marker="play-slide").elements))
    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    assert play_btn.props.get("icon") == "pause"

    user.find(marker="utext-0").trigger("blur")  # focus left, nothing typed
    assert play_btn.props.get("icon") == "pause"  # still playing


async def test_ctrl_s_saves_without_rebuilding_field(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repro #4: Ctrl-S saves the field in place — same widget, no rebuild (so
    focus is retained) — and persists the edit to disk."""
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    before = next(iter(user.find(marker="utext-0").elements))
    user.find(marker="utext-0").clear().type("Saved with a keystroke.")
    user.find(marker="utext-0").trigger("keydown.ctrl.s.prevent")
    sidecar = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "Saved with a keystroke." in sidecar
    after = next(iter(user.find(marker="utext-0").elements))
    assert before is after  # field not rebuilt → focus is kept


async def test_play_all_starts_at_current_slide(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repro #5: whole-deck playback begins at the current slide, not slide 1."""
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))

    def instant_build(self: EditorState) -> api.Preview:
        return _fake_preview(self.pdf_path, [(0.0, "intro-title"), (2.0, "euler-setup")])

    monkeypatch.setattr(EditorState, "preview_deck", instant_build)
    await user.open("/")
    user.find("Next").click()  # move to slide 2 (euler-setup)
    await user.should_see("Slide 2 / 6")
    audio = next(iter(user.find(marker="preview-audio").elements))
    seek = next(iter(user.find(marker="seek").elements))

    user.find(marker="play-deck").click()
    await user.should_see("Preview ready", retries=300)
    # euler-setup's cue is 2.0s into a 4.0s track → seek there, not to 0
    assert "#t=2.0" in str(audio.props.get("src"))
    assert float(seek.value or 0.0) == pytest.approx(0.5)


async def test_generate_missing_keeps_unaffected_playback(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repro #6: filling *other* slides' missing audio in the background must not
    stop the narration currently playing — generation no longer touches the
    transport at all (the queue runs off the busy gate)."""
    import asyncio

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    # the playing slide is fully cached; only the *other* slide needs audio
    monkeypatch.setattr(
        EditorState, "uncached_count", lambda self, sid: 0 if sid == "intro-title" else 1
    )
    monkeypatch.setattr(EditorState, "uncached_total", lambda self: 1)
    monkeypatch.setattr(EditorState, "targets_for_sweep", lambda self, **k: {("euler-setup", 0)})
    calls: list[set[tuple[str, int]]] = []
    monkeypatch.setattr(
        EditorState,
        "synth_targets",
        lambda self, t, *, force=False: (calls.append(set(t)), 1)[1],
    )
    await user.open("/")
    play_btn = next(iter(user.find(marker="play-slide").elements))
    user.find(marker="play-slide").click()
    await user.should_see("Preview ready", retries=300)
    assert play_btn.props.get("icon") == "pause"  # intro-title is playing

    user.find(marker="gen-missing").click()
    for _ in range(100):  # let the background job synthesize the other slide
        if calls:
            break
        await asyncio.sleep(0.05)
    assert calls == [{("euler-setup", 0)}]  # only the uncached slide was generated
    assert play_btn.props.get("icon") == "pause"  # untouched playback keeps going


async def test_slide_image_refetches_after_recompile(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repro #7: a recompile reuses page-N.png paths, so without a cache-bust the
    browser keeps showing the stale (now-dropped) slide. The image URL must
    change when the underlying page image is re-rendered."""
    from tests.conftest import write_pdf

    pdf = write_pdf(tmp_path / "deck.pdf", ["a", "b", "c"])
    (tmp_path / "deck.narration").write_text(
        simple_narration("@a\nA.\n\n@b\nB.\n\n@c\nC.\n"), encoding="utf-8"
    )
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("Slide 1 / 3")
    img = next(iter(user.find(marker="stage-img").elements))
    before = str(img.props.get("src"))

    write_pdf(pdf, ["a", "b"])  # recompile drops a slide; pages re-rasterize in place
    later = time.time() + 5
    os.utime(pdf, (later, later))
    await user.should_see("Deck files changed on disk — reloaded", retries=300)

    after = str(img.props.get("src"))
    assert before != after  # cache-busted → the browser refetches the fresh image
    assert before.split("?")[0] == after.split("?")[0]  # same path, new version query


async def test_orphan_tray_lists_unattached_narration(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path, sidecar="@intro-title\nHi.\n\n@ghost\nLost text to keep.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("Unattached narration")
    await user.should_see("@ghost")
    await user.should_see("Lost text to keep.")


async def test_orphan_attach_flow(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path, sidecar="@intro-title\nHi.\n\n@ghost\nLost text to keep.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    user.find(marker="attach-ghost").click()
    await user.should_see("Attach narration '@ghost' to which slide?")
    # default target is the first un-narrated slide: euler-setup
    user.find(marker="attach-confirm").click()
    await user.should_see("Narration attached to 'euler-setup'")
    sidecar = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "Lost text to keep." in sidecar
    assert "@ghost" not in sidecar
    await user.should_see("✓ no errors")  # orphan error resolved


async def test_orphan_delete_flow(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path, sidecar="@intro-title\nHi.\n\n@ghost\nLost text to keep.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    user.find(marker="delete-ghost").click()
    await user.should_see("Delete the unattached narration '@ghost'?")
    user.find(marker="delete-confirm").click()
    await user.should_see("Deleted narration '@ghost'")
    assert "Lost text to keep." not in (tmp_path / "marked.narration").read_text(encoding="utf-8")


async def test_typing_survives_recompile_that_drops_the_slide(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Narration being typed when its slide is dropped lands in the tray, not /dev/null."""
    from tests.conftest import write_pdf

    pdf = write_pdf(tmp_path / "deck.pdf", ["alpha", "beta"])
    (tmp_path / "deck.narration").write_text(
        simple_narration("@alpha\nHi.\n\n@beta\nBye.\n"), encoding="utf-8"
    )
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("Slide 1 / 2")
    user.find(ui.textarea).clear().type("Fresh thoughts, unsaved.")
    # the recompile drops the slide being edited
    write_pdf(pdf, ["beta"])
    later = time.time() + 5
    os.utime(pdf, (later, later))
    await user.should_see("Deck files changed on disk — reloaded", retries=300)
    sidecar = (tmp_path / "deck.narration").read_text(encoding="utf-8")
    assert "Fresh thoughts, unsaved." in sidecar  # flushed before the reload
    await user.should_see("Unattached narration")
    await user.should_see("@alpha")


async def test_transport_grays_out_play_and_generate_when_pointless(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generate lives on each utterance card; play disables when there's nothing to hear."""
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello there.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    play = next(iter(user.find(marker="play-slide").elements))
    gen = next(iter(user.find(marker="gen-seg-0").elements))
    assert isinstance(play, ui.button) and isinstance(gen, ui.button)
    # narrated slide, nothing cached: both actions make sense
    assert play.enabled and gen.enabled
    assert gen.props.get("icon") == "graphic_eq"  # amber "no audio yet" state
    user.find("Next").click()  # euler-setup has no narration
    assert not play.enabled
    await user.should_see("empty — add a line or a pause above")  # no cards, no gen buttons


async def test_segment_generate_button_flips_to_regenerate_when_cached(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once an utterance's audio is cached its button turns into the green
    re-generate affordance, and clicking it forces a fresh synthesis (force=True)
    through the background queue."""
    import asyncio

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello there.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(EditorState, "speech_cached_flags", lambda self: [True])
    forces: list[bool] = []
    monkeypatch.setattr(
        EditorState,
        "synth_targets",
        lambda self, t, *, force=False: (forces.append(force), 1)[1],
    )
    await user.open("/")
    gen = next(iter(user.find(marker="gen-seg-0").elements))
    assert isinstance(gen, ui.button) and gen.enabled
    assert gen.props.get("icon") == "autorenew"  # re-generate affordance, not grayed out
    assert gen.props.get("color") == "positive"  # green = generated
    user.find(marker="gen-seg-0").click()
    for _ in range(100):  # the worker runs the forced re-synthesis off the loop
        if forces:
            break
        await asyncio.sleep(0.05)
    assert forces == [True]  # the click forced a fresh take


async def test_play_awaits_in_flight_generation_without_double_triggering(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story: press play right after generating. Play must wait for the in-flight
    job and reuse its clip — never launch a second synthesis of the same clip."""
    import asyncio
    import threading

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello there.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(EditorState, "speech_cached_flags", lambda self: [False])
    monkeypatch.setattr(
        EditorState, "preview_current", lambda self: _fake_preview(self.pdf_path, [])
    )
    gate = threading.Event()
    calls: list[set[tuple[str, int]]] = []

    def synth(self: EditorState, targets: set[tuple[str, int]], *, force: bool = False) -> int:
        calls.append(set(targets))
        gate.wait(timeout=5)  # hold the job "in flight" until the test releases it
        return 1

    monkeypatch.setattr(EditorState, "synth_targets", synth)
    await user.open("/")

    user.find(marker="gen-seg-0").click()  # enqueue; the worker blocks inside synth
    for _ in range(100):  # wait until the job is actually running
        if calls:
            break
        await asyncio.sleep(0.05)
    assert calls == [{("intro-title", 0)}]

    user.find(marker="play-slide").click()  # play must await the in-flight job
    await asyncio.sleep(0.2)
    await user.should_not_see("Preview ready")  # still waiting on the job, not built yet

    gate.set()  # let the generation finish
    await user.should_see("Preview ready", retries=300)
    assert calls == [{("intro-title", 0)}]  # one synthesis total — play didn't duplicate


async def test_editor_stays_live_and_queues_while_a_clip_generates(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story: generation no longer freezes the editor. While one clip renders you
    can navigate and queue another — the old single busy gate is gone."""
    import asyncio
    import threading

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(EditorState, "speech_cached_flags", lambda self: [False])
    gate = threading.Event()
    calls: list[set[tuple[str, int]]] = []

    def synth(self: EditorState, targets: set[tuple[str, int]], *, force: bool = False) -> int:
        calls.append(set(targets))
        gate.wait(timeout=5)  # every job blocks until released
        return 1

    monkeypatch.setattr(EditorState, "synth_targets", synth)
    await user.open("/")

    user.find(marker="gen-seg-0").click()  # job A starts and blocks in the worker
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.05)

    user.find("Next").click()  # UI stays responsive mid-generation
    await user.should_see("Slide 2 / 6")
    user.find(marker="gen-seg-0").click()  # queue job B — no busy lock rejects it
    await asyncio.sleep(0.1)
    assert len(calls) == 1  # serial worker: B is queued behind the still-running A

    gate.set()  # release both jobs
    for _ in range(100):
        if len(calls) == 2:
            break
        await asyncio.sleep(0.05)
    assert {("intro-title", 0)} in calls and {("euler-setup", 0)} in calls


async def test_auto_build_disabled_for_paid_engine(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story: auto-build is local-only. On a paid engine the checkbox is disabled
    and nothing is generated in the background, even if the flag was stored on."""
    import asyncio

    from nicegui import app

    from slidesonnet.gui.state import EditorState

    monkeypatch.setattr(EditorState, "tts_is_paid", property(lambda self: True))
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    app.storage.general["auto_build"] = True  # even if persisted on for a paid deck…
    calls: list[set[tuple[str, int]]] = []
    monkeypatch.setattr(
        EditorState, "synth_targets", lambda self, t, *, force=False: (calls.append(set(t)), 1)[1]
    )
    await user.open("/")
    cb = next(iter(user.find(marker="auto-build").elements))
    assert isinstance(cb, ui.checkbox)
    assert not cb.enabled  # disabled for paid engines
    await asyncio.sleep(0.1)
    assert calls == []  # …no background billing happens


async def test_enabling_auto_build_sweeps_uncached_clips_except_current(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story: turning auto-build on fills the deck in the background — every
    uncached clip except the slide you're currently on."""
    import asyncio

    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    calls: list[set[tuple[str, int]]] = []
    monkeypatch.setattr(
        EditorState, "synth_targets", lambda self, t, *, force=False: (calls.append(set(t)), 1)[1]
    )
    await user.open("/")  # opens on intro-title with auto-build off
    user.find(marker="auto-build").click()  # enable → sweep
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.05)
    flat = set().union(*calls)
    assert ("euler-setup", 0) in flat  # the other slide gets filled
    assert ("intro-title", 0) not in flat  # the current slide is skipped


async def test_auto_build_generates_edited_slide_after_debounce(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story: with auto-build on, editing a slide and moving on quietly generates
    that slide's audio after a debounce — no explicit generate click."""
    import asyncio

    from slidesonnet.gui import app as app_module
    from slidesonnet.gui.state import EditorState

    monkeypatch.setattr(app_module, "AUTO_BUILD_DEBOUNCE_S", 0.1)  # don't wait 2.5s in a test
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    calls: list[set[tuple[str, int]]] = []
    monkeypatch.setattr(
        EditorState, "synth_targets", lambda self, t, *, force=False: (calls.append(set(t)), 1)[1]
    )
    await user.open("/")
    user.find(marker="auto-build").click()  # enable (sweeps euler-setup)
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.05)
    calls.clear()  # ignore the one-time sweep; focus on the incremental path

    # edit the current slide, then navigate away — the save schedules a build
    user.find(marker="utext-0").clear().type("Hello again, world.")
    user.find("Next").click()
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.05)
    assert calls == [{("intro-title", 0)}]  # only the edited slide was generated


async def test_generate_missing_shows_count_and_rests_when_done(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deck-wide button says exactly how much work a click means."""
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello. [pause 1] World.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    btn = next(iter(user.find(marker="gen-missing").elements))
    assert isinstance(btn, ui.button) and btn.enabled
    assert btn.text == "Generate missing (2)"  # two uncached utterances


async def test_generate_missing_disabled_when_nothing_to_do(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(EditorState, "uncached_total", lambda self: 0)
    await user.open("/")
    btn = next(iter(user.find(marker="gen-missing").elements))
    assert isinstance(btn, ui.button) and not btn.enabled
    assert btn.text == "All audio generated"


async def test_filmstrip_flags_slides_with_ungenerated_audio(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A thumb wears the amber audio badge only while its speech isn't generated."""
    from slidesonnet.gui.state import EditorState

    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    monkeypatch.setattr(EditorState, "ungenerated_ids", lambda self: {"intro-title"})
    await user.open("/")
    badges = {
        m: next(iter(user.find(marker=m).elements)) for m in ("thumb-audio-0", "thumb-audio-1")
    }
    assert "hidden" not in badges["thumb-audio-0"].classes  # intro-title: ungenerated speech
    assert "hidden" in badges["thumb-audio-1"].classes  # euler-setup: nothing to generate


async def test_stage_has_draggable_slide_editor_divider(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The slide view and the narration cards share the stage via a splitter."""
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    split = next(iter(user.find(marker="split-stage").elements))
    assert isinstance(split, ui.splitter)
    assert split.props.get("horizontal") is True
    assert float(split.value) > 0


async def test_paid_engine_preview_asks_before_synthesis(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello there.\n")
    (tmp_path / "slidesonnet.toml").write_text('[tts]\nbackend = "elevenlabs"\n', encoding="utf-8")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    user.find(marker="play-slide").click()
    await user.should_see("API credits")  # confirm dialog instead of silent synthesis
    user.find("Cancel").click()
    # cancelled: nothing was synthesized (an attempt would also fail — no API key)
    from slidesonnet.cache import audio_dir

    assert not list(audio_dir(pdf).glob("*"))
