"""GUI editor tests via NiceGUI's in-process user simulation."""

from __future__ import annotations

from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

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


@pytest.mark.integration
async def test_generate_and_preview(
    user: User, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _prep(tmp_path, sidecar="@intro-title\nWelcome to the deck.\n")
    monkeypatch.setenv("SLIDESONNET_EDIT_PDF", str(pdf))
    await user.open("/")
    user.find("Generate").click()
    # synthesis runs off the event loop now; allow up to 30s for kokoro
    await user.should_see("Synthesized", retries=300)
    # audio cache now exists for intro-title
    from slidesonnet.cache import audio_dir

    assert any(audio_dir(pdf).glob("*.wav"))


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
