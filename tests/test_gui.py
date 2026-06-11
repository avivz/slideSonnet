"""GUI editor tests via NiceGUI's in-process user simulation."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from slidesonnet import api

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"

pytestmark = pytest.mark.nicegui_main_file("tests/gui_main.py")


def _prep(tmp_path: Path, sidecar: str = "") -> Path:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    if sidecar:
        (tmp_path / "marked.narration").write_text(sidecar, encoding="utf-8")
    return pdf


async def test_editor_loads(user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _prep(tmp_path)
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("intro-title")
    await user.should_see("Slide 1 / 6")


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
    user.find(ui.textarea).clear().type("Hello deck. [pause 1] Bye.")
    user.find("Next").click()  # nav saves the current slide first
    sidecar = (tmp_path / "marked.narration").read_text(encoding="utf-8")
    assert "@intro-title" in sidecar
    assert "Hello deck." in sidecar
    assert "[pause 1]" in sidecar


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
    (tmp_path / "deck.narration").write_text("@alpha\nHi.\n\n@beta\nBye.\n", encoding="utf-8")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    await user.should_see("Slide 1 / 2")
    # "recompile": the deck gains a slide while the editor is open
    write_pdf(pdf, ["alpha", "beta", "gamma"])
    later = time.time() + 5
    os.utime(pdf, (later, later))
    await user.should_see("Deck files changed on disk — reloaded", retries=300)
    await user.should_see("Slide 1 / 3")
    # jumping to the new slide saves, which scaffolds its (empty) sidecar block
    user.find(marker="thumb-2").click()
    await user.should_see("Slide 3 / 3")
    await user.should_see("no speech on this slide")
    sidecar = (tmp_path / "deck.narration").read_text(encoding="utf-8")
    assert "@gamma" in sidecar


@pytest.mark.integration
async def test_generate_and_preview(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a SECOND narrated slide stays ungenerated: single-slide preview must not
    # trip over its missing clips (regression: IndexError in page_pieces)
    pdf = _prep(
        tmp_path,
        sidecar="@intro-title\nWelcome to the deck.\n\n@euler-setup\nNot generated yet.\n",
    )
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    user.find(marker="gen-slide").click()
    # synthesis runs off the event loop now; allow up to 30s for kokoro
    await user.should_see("Synthesized", retries=300)
    # everything cached now: the generate button has nothing left to do
    gen = next(iter(user.find(marker="gen-slide").elements))
    assert isinstance(gen, ui.button) and not gen.enabled
    # audio cache now exists for intro-title
    from slidesonnet.cache import audio_dir

    assert any(audio_dir(pdf).glob("*.wav"))
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
    assert "@euler-setup\nLost text to keep." in sidecar
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
    (tmp_path / "deck.narration").write_text("@alpha\nHi.\n\n@beta\nBye.\n", encoding="utf-8")
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
    """Generate sits in the transport; play/generate disable when there's nothing to do."""
    pdf = _prep(tmp_path, sidecar="@intro-title\nHello there.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    play = next(iter(user.find(marker="play-slide").elements))
    gen = next(iter(user.find(marker="gen-slide").elements))
    assert isinstance(play, ui.button) and isinstance(gen, ui.button)
    # narrated slide, nothing cached: both actions make sense
    assert play.enabled and gen.enabled
    user.find("Next").click()  # euler-setup has no narration
    assert not play.enabled
    assert not gen.enabled


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
