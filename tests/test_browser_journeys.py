"""Real-browser (Playwright) GUI journeys for the editor.

Each test drives a REAL editor server (``tests/browser_main.py``, subprocess)
from a real headless Chromium, exercising the focus/blur/value-sync/playback
lifecycle that the in-process NiceGUI ``user`` simulation structurally cannot
see (it writes widget ``.value`` synchronously; no DOM, no blur, no websocket).

Local-only: everything here is marked ``browser`` and excluded from CI.
Journeys that reproduce known open bugs are ``xfail`` (non-strict) with the
bug spelled out in the reason.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol

import pytest
from playwright.sync_api import Locator, Page, expect

from slidesonnet.cache import audio_dir
from slidesonnet.hashing import text_hash
from tests.conftest import simple_narration

pytestmark = pytest.mark.browser

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"
LAUNCHER = Path(__file__).parent / "browser_main.py"


# --------------------------------------------------------------------------
# infrastructure: server subprocess, marker targeting, small wait helper
# --------------------------------------------------------------------------


class ServerFactory(Protocol):
    """Start an editor server for a deck; returns its base URL."""

    def __call__(self, pdf: Path, *, real_tts: bool = False, stub_seconds: float = 1.0) -> str: ...


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, Any]) -> dict[str, Any]:
    """Let <audio>.play() succeed without a user gesture (the preview player)."""
    args = [*browser_type_launch_args.get("args", []), "--autoplay-policy=no-user-gesture-required"]
    return {**browser_type_launch_args, "args": args}


@pytest.fixture(autouse=True)
def _fast_timeouts(page: Page) -> None:
    """Fail fast: rely on Playwright auto-waiting with a ~10s cap, not sleeps."""
    page.set_default_timeout(10_000)
    page.set_default_navigation_timeout(15_000)


@pytest.fixture
def editor_server() -> Iterator[ServerFactory]:
    """Factory that launches the real editor server in a subprocess per deck."""
    procs: list[subprocess.Popen[bytes]] = []

    def start(pdf: Path, *, real_tts: bool = False, stub_seconds: float = 1.0) -> str:
        port = _free_port()
        # NiceGUI's ui.run special-cases PYTEST_*/NICEGUI_* env vars (its own
        # screen-test mode); the subprocess is a REAL server, so drop them.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "NICEGUI_"))}
        env["SLIDESONNET_EDIT_PDF"] = str(pdf)
        env["SLIDESONNET_TEST_PORT"] = str(port)
        env["SLIDESONNET_TEST_STUB_SECONDS"] = str(stub_seconds)
        if real_tts:
            env["SLIDESONNET_TEST_REAL_TTS"] = "1"
        proc = subprocess.Popen([sys.executable, str(LAUNCHER)], env=env)
        procs.append(proc)
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30.0
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"editor server died on startup (rc={proc.returncode})")
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        return url
            except OSError:
                time.sleep(0.2)
        proc.kill()
        raise RuntimeError("editor server did not become ready within 30s")

    yield start
    for proc in procs:
        proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def marked(page: Page, name: str) -> Locator:
    """Locate an element the app ``.mark()``-ed *name*.

    The test launcher renders every NiceGUI marker as an ``ss-marker-<name>``
    CSS class (stock NiceGUI keeps markers server-side only), so this survives
    the block editor's destructive re-renders.
    """
    return page.locator(f".ss-marker-{name}")


def _prep(tmp_path: Path, sidecar: str = "") -> Path:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    if sidecar:
        (tmp_path / "marked.narration").write_text(simple_narration(sidecar), encoding="utf-8")
    return pdf


def _sidecar(tmp_path: Path) -> str:
    path = tmp_path / "marked.narration"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _eventually(predicate: Callable[[], bool], timeout: float = 10.0) -> bool:
    """Poll *predicate* (for on-disk effects Playwright cannot auto-wait on)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


# --------------------------------------------------------------------------
# journey 1: navigation — buttons, arrow keys, filmstrip
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_navigate_via_buttons_keys_and_filmstrip(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello.\n")
    page.goto(editor_server(pdf))
    expect(page.get_by_text("Slide 1 / 6")).to_be_visible()
    expect(page.locator(".ss-id")).to_have_text("intro-title")
    stage_img = page.locator(".ss-stage-img img")
    expect(stage_img).to_be_visible()
    first_src = stage_img.get_attribute("src")
    assert first_src

    marked(page, "Next").click()
    expect(page.get_by_text("Slide 2 / 6")).to_be_visible()
    expect(page.locator(".ss-id")).to_have_text("euler-setup")
    expect(stage_img).not_to_have_attribute("src", first_src)

    page.keyboard.press("ArrowRight")
    expect(page.get_by_text("Slide 3 / 6")).to_be_visible()
    expect(page.locator(".ss-id")).to_have_text("euler-trick")
    page.keyboard.press("ArrowLeft")
    expect(page.get_by_text("Slide 2 / 6")).to_be_visible()

    marked(page, "thumb-3").click()
    expect(page.get_by_text("Slide 4 / 6")).to_be_visible()
    expect(page.locator(".ss-id")).to_have_text("euler-result")


# --------------------------------------------------------------------------
# journey 2 (known bug): type, then act WITHOUT blurring first
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
@pytest.mark.xfail(
    reason="save-on-blur race: the textarea commits to the sidecar only on blur, so "
    "clicking Generate right after typing can synthesize the stale text before the "
    "browser's new value reaches the server",
    strict=False,
)
def test_typing_then_generating_without_blur_uses_the_typed_text(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nOld words.\n")
    page.goto(editor_server(pdf))
    box = marked(page, "utext-0").locator("textarea")
    expect(box).to_have_value("Old words.")
    box.click()
    box.fill("")
    box.press_sequentially("Brand new words.")
    marked(page, "gen-slide").click()  # straight to Generate — no blur-click elsewhere
    expect(page.get_by_text("Synthesized").first).to_be_visible(timeout=30_000)
    assert "Brand new words." in _sidecar(tmp_path)
    new_hash = text_hash("Brand new words.")
    cached = [f.name for f in audio_dir(pdf).glob("*.wav")]
    assert any(name.startswith(new_hash) for name in cached), (
        f"synthesized the stale text, not the typed one (cache: {cached})"
    )


# --------------------------------------------------------------------------
# journey 3 (known bug): typing during deck playback vs the cue flip
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
@pytest.mark.xfail(
    reason="playback auto-advance rebuilds the block editor destructively: when the cue "
    "flip lands mid-typing it saves only the synced prefix, destroys the focused "
    "textarea under the user's fingers, and the rest of the sentence is lost",
    strict=False,
)
def test_editing_during_deck_playback_survives_the_cue_flip(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    page.goto(editor_server(pdf, stub_seconds=2.0))
    marked(page, "play-deck").click()
    expect(page.get_by_text("Preview ready").first).to_be_visible(timeout=30_000)
    # type slowly enough that slide 2's cue flip lands mid-sentence (the stub
    # track flips after ~3s; 60 chars at 120 ms/keystroke span ~7s)
    sentence = "The quick brown fox jumps over the lazy dog, twice over."
    box = marked(page, "utext-0").locator("textarea")
    box.click()
    box.fill("")
    box.press_sequentially(sentence, delay=120)
    # the cue flip happened mid-typing (playback may have advanced further since)
    expect(page.locator(".ss-counter")).not_to_have_text("Slide 1 / 6", timeout=30_000)
    marked(page, "stop").click()
    marked(page, "thumb-0").click()
    expect(page.get_by_text("Slide 1 / 6")).to_be_visible()
    assert sentence in _sidecar(tmp_path), (
        f"typed sentence was truncated by the cue flip; sidecar has: {_sidecar(tmp_path)!r}"
    )


# --------------------------------------------------------------------------
# journey 4 (REAL KOKORO): generate → cache → re-generate → blur-edit
# --------------------------------------------------------------------------


@pytest.mark.timeout(600)
def test_generate_cache_regenerate_and_blur_edit_with_real_kokoro(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pytest.importorskip("kokoro")
    pdf = _prep(tmp_path, "@intro-title\nWelcome to the deck.\n")
    page.goto(editor_server(pdf, real_tts=True))
    gen = marked(page, "gen-slide")
    expect(gen).to_contain_text("graphic_eq")  # nothing cached: plain generate

    gen.click()
    expect(page.get_by_text("Synthesized").first).to_be_visible(timeout=540_000)
    wavs = list(audio_dir(pdf).glob("*.wav"))
    assert len(wavs) == 1, f"expected one cached clip, found {wavs}"
    clip = wavs[0]
    first_mtime = clip.stat().st_mtime_ns
    expect(gen).to_contain_text("autorenew")  # fully cached: re-generate affordance

    gen.click()
    expect(page.get_by_text("Re-generated").first).to_be_visible(timeout=120_000)
    assert clip.stat().st_mtime_ns != first_mtime, "force synth did not rewrite the clip"

    # a PROPER blur-edit: type, then click elsewhere so blur commits the text
    box = marked(page, "utext-0").locator("textarea")
    box.click()
    box.fill("A different narration line.")
    page.locator(".ss-id").click()
    assert _eventually(lambda: "A different narration line." in _sidecar(tmp_path))
    expect(gen).to_contain_text("graphic_eq")  # new text means uncached again

    gen.click()
    # wait on the cache file itself — the "Synthesized" toast from the first
    # generation may still be on screen, so its text can't be trusted here
    new_hash = text_hash("A different narration line.")
    assert _eventually(
        lambda: any(f.name.startswith(new_hash) for f in audio_dir(pdf).glob("*.wav")),
        timeout=120.0,
    ), "no cache entry for the blur-edited text"
    expect(gen).to_contain_text("autorenew", timeout=30_000)  # cached again


# --------------------------------------------------------------------------
# journey 5: structured block editing
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_block_editing_add_attrs_reorder_delete(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path)  # no sidecar: intro-title starts empty
    page.goto(editor_server(pdf))

    marked(page, "add-utterance").click()
    box = marked(page, "utext-0").locator("textarea")
    box.click()
    box.fill("First spoken line.")
    page.locator(".ss-id").click()  # blur commits
    assert _eventually(lambda: "text: First spoken line." in _sidecar(tmp_path))

    marked(page, "add-pause").click()
    assert _eventually(lambda: "pause: 1" in _sidecar(tmp_path))

    marked(page, "uvoice-0").click()
    page.get_by_role("option", name="af_bella", exact=True).click()
    assert _eventually(lambda: "voice: af_bella" in _sidecar(tmp_path))

    marked(page, "upace-0").click()
    page.get_by_role("option", name="slow", exact=True).click()
    assert _eventually(lambda: "pace: slow" in _sidecar(tmp_path))

    note = marked(page, "udirect-0").locator("input")
    note.click()
    note.fill("warmly")
    page.locator(".ss-id").click()  # blur commits
    assert _eventually(lambda: "direct: warmly" in _sidecar(tmp_path))

    marked(page, "seg-down-0").click()  # move the utterance below the pause
    assert _eventually(
        lambda: (
            "pause: 1" in _sidecar(tmp_path)
            and _sidecar(tmp_path).index("pause: 1") < _sidecar(tmp_path).index("text: First")
        )
    )

    marked(page, "seg-del-0").click()  # the pause sits at index 0 now — delete it
    assert _eventually(lambda: "pause:" not in _sidecar(tmp_path))
    assert "text: First spoken line." in _sidecar(tmp_path)


# --------------------------------------------------------------------------
# journey 6: transitions persist
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_transition_out_crossfade_persists_across_navigation(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHi.\n")
    page.goto(editor_server(pdf))

    marked(page, "trans-out").get_by_text("crossfade", exact=True).click()
    assert _eventually(lambda: "transition-out: crossfade 0.5" in _sidecar(tmp_path))

    row = page.locator(".ss-transition", has=marked(page, "trans-out"))
    secs = row.locator(".ss-trans-secs input")
    secs.click()
    secs.fill("1.2")
    page.locator(".ss-id").click()  # blur commits
    assert _eventually(lambda: "transition-out: crossfade 1.2" in _sidecar(tmp_path))

    marked(page, "Next").click()
    expect(page.get_by_text("Slide 2 / 6")).to_be_visible()
    marked(page, "Previous").click()
    expect(page.get_by_text("Slide 1 / 6")).to_be_visible()
    expect(row.locator(".ss-trans-secs input")).to_have_value("1.2")
    assert "transition-out: crossfade 1.2" in _sidecar(tmp_path)


# --------------------------------------------------------------------------
# journey 7: pane collapse / expand
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_pane_collapse_and_expand(page: Page, editor_server: ServerFactory, tmp_path: Path) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHi.\n")
    page.goto(editor_server(pdf))
    # panes collapse to width 0 (their content is clipped, not detached, so
    # assert the panel's computed width rather than element visibility)
    strip_pane = marked(page, "split-strip").locator("> .q-splitter__before")
    console_pane = marked(page, "split-console").locator("> .q-splitter__after")
    expect(marked(page, "thumb-0")).to_be_visible()
    expect(page.get_by_text("Checks · this slide")).to_be_visible()
    expect(strip_pane).not_to_have_css("width", "0px")
    expect(console_pane).not_to_have_css("width", "0px")

    marked(page, "collapse-strip").click()
    expect(strip_pane).to_have_css("width", "0px")
    marked(page, "toggle-strip").click()
    expect(strip_pane).not_to_have_css("width", "0px")
    expect(marked(page, "thumb-0")).to_be_visible()

    marked(page, "collapse-console").click()
    expect(console_pane).to_have_css("width", "0px")
    marked(page, "toggle-console").click()
    expect(console_pane).not_to_have_css("width", "0px")
    expect(page.get_by_text("Checks · this slide")).to_be_visible()


# --------------------------------------------------------------------------
# journey 8: diagnostics badge + orphan tray
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_orphan_tray_badge_and_delete_flow(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHi.\n\n@ghost\nLost text to keep.\n")
    page.goto(editor_server(pdf))
    expect(page.locator(".ss-pill")).to_contain_text("1 errors")
    tray = marked(page, "orphan-tray")
    expect(tray).to_be_visible()
    expect(tray).to_contain_text("@ghost")
    expect(tray).to_contain_text("Lost text to keep.")

    marked(page, "delete-ghost").click()
    expect(page.get_by_text("Delete the unattached narration '@ghost'?")).to_be_visible()
    marked(page, "delete-confirm").click()
    expect(page.locator(".ss-pill")).to_contain_text("no errors")
    expect(tray).to_be_hidden()
    assert _eventually(lambda: "Lost text to keep." not in _sidecar(tmp_path))


# --------------------------------------------------------------------------
# journey 9: live reload of an externally edited sidecar
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_external_sidecar_edit_reloads_live(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nOriginal text.\n")
    page.goto(editor_server(pdf))
    expect(marked(page, "utext-0").locator("textarea")).to_have_value("Original text.")

    sidecar = tmp_path / "marked.narration"
    sidecar.write_text(simple_narration("@intro-title\nRewritten on disk.\n"), encoding="utf-8")
    later = time.time() + 5
    os.utime(sidecar, (later, later))

    expect(page.get_by_text("Deck files changed on disk — reloaded").first).to_be_visible(
        timeout=15_000
    )
    expect(marked(page, "utext-0").locator("textarea")).to_have_value("Rewritten on disk.")


# --------------------------------------------------------------------------
# journey 10: transport — play/pause icon, stop reset, deck cue flip
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_transport_play_stop_and_deck_cue_flip(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    page.goto(editor_server(pdf, stub_seconds=2.0))
    play = marked(page, "play-slide")

    play.click()
    expect(page.get_by_text("Preview ready").first).to_be_visible(timeout=30_000)
    expect(play).to_contain_text("pause")  # playing: the button mirrors the player
    expect(page.locator(".ss-time")).to_contain_text("/ 0:0")  # clock shows a duration

    marked(page, "stop").click()
    expect(play).to_contain_text("play_arrow")
    expect(page.locator(".ss-time")).to_have_text("")  # stop resets the transport
    expect(marked(page, "seek")).to_have_attribute("aria-disabled", "true")

    # deck preview: the stage image flips on the cue boundary
    stage_img = page.locator(".ss-stage-img img")
    first_src = stage_img.get_attribute("src")
    assert first_src
    marked(page, "play-deck").click()
    expect(page.get_by_text("Slide 2 / 6")).to_be_visible(timeout=30_000)
    expect(stage_img).not_to_have_attribute("src", first_src)
