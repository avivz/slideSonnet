"""Real-browser journeys for the Vue editor (local only — never in CI).

Each journey drives the production frontend against the real Python server,
with synthesis stubbed at the TTS engine (instant silent WAVs; see
``tests/browser_main.py``). Only what needs a real browser lives here —
focus, timing, media, keyboard, navigation between pages. Everything else is
covered by Vitest (``frontend/tests``) and the API tests.

Needs the built frontend (``make frontend``; ``make test-browser`` builds it).
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
from typing import Protocol

import pytest
from playwright.sync_api import Locator, Page, expect

from slidesonnet.server.library import deck_token
from tests.conftest import prep_marked_deck as _prep
from tests.conftest import simple_narration

pytestmark = pytest.mark.browser

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"
LAUNCHER = Path(__file__).parent / "browser_main.py"


class Server(Protocol):
    def __call__(
        self, pdf: Path, *, stub_seconds: float = 1.0, root: Path | None = None
    ) -> str: ...


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, object]) -> dict[str, object]:
    """Let <audio>.play() succeed without a user gesture (the preview player)."""
    args = [*browser_type_launch_args.get("args", []), "--autoplay-policy=no-user-gesture-required"]  # type: ignore[misc]
    return {**browser_type_launch_args, "args": args}


@pytest.fixture(autouse=True)
def _fast_timeouts(page: Page) -> None:
    page.set_default_timeout(10_000)
    page.set_default_navigation_timeout(15_000)


@pytest.fixture
def server() -> Iterator[Server]:
    """Start the real editor (Vue frontend) for a deck; returns the deck's URL."""
    procs: list[subprocess.Popen[bytes]] = []

    def start(pdf: Path, *, stub_seconds: float = 1.0, root: Path | None = None) -> str:
        port = _free_port()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "NICEGUI_"))}
        env.update(
            SLIDESONNET_EDIT_PDF=str(pdf),
            SLIDESONNET_TEST_PORT=str(port),
            SLIDESONNET_TEST_STUB_SECONDS=str(stub_seconds),
        )
        if root is not None:
            env["SLIDESONNET_LIB_ROOT"] = str(root)
        proc = subprocess.Popen([sys.executable, str(LAUNCHER)], env=env, cwd=str(pdf.parent))
        procs.append(proc)
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"editor server died on startup (rc={proc.returncode})")
            try:
                with urllib.request.urlopen(f"{base}/api/v1/library", timeout=2) as r:
                    if r.status == 200:
                        return f"{base}/d/{deck_token(pdf)}"
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


def tid(page: Page, name: str) -> Locator:
    return page.get_by_test_id(name)


def _sidecar(pdf: Path) -> str:
    path = pdf.with_suffix(".narration")
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _eventually(predicate: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def test_navigate_with_buttons_keys_and_filmstrip(
    page: Page, server: Server, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHello.\n")
    page.goto(server(pdf))
    counter = tid(page, "counter")
    expect(counter).to_have_text("Slide 1 / 6")
    tid(page, "next").click()
    expect(counter).to_have_text("Slide 2 / 6")
    page.locator("body").click(position={"x": 700, "y": 30})  # focus off any field
    page.keyboard.press("ArrowRight")
    expect(counter).to_have_text("Slide 3 / 6")
    page.keyboard.press("ArrowUp")
    expect(counter).to_have_text("Slide 2 / 6")
    tid(page, "thumb-4").click()
    expect(counter).to_have_text("Slide 5 / 6")
    # arrows typed into a field move the caret, not the slide
    tid(page, "thumb-0").click()
    box = tid(page, "utext-0")
    box.click()
    page.keyboard.press("ArrowRight")
    expect(counter).to_have_text("Slide 1 / 6")


def test_typing_autosaves_without_leaving_the_field(
    page: Page, server: Server, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nOld words.\n")
    page.goto(server(pdf))
    box = tid(page, "utext-0")
    box.click()
    box.fill("")
    box.press_sequentially("New words, never blurred.", delay=20)
    assert _eventually(lambda: "New words, never blurred." in _sidecar(pdf))
    expect(box).to_be_focused()  # the save didn't disturb the field
    expect(tid(page, "save-state")).to_have_text("Saved")


def test_outside_edit_while_typing_keeps_both_versions(
    page: Page, server: Server, tmp_path: Path
) -> None:
    """B1: an agent's edit to the slide being typed on never erases either side."""
    pdf = _prep(tmp_path, "@intro-title\nOriginal.\n\n@euler-setup\nSecond.\n")
    page.goto(server(pdf))
    box = tid(page, "utext-0")
    box.click()
    box.fill("")
    box.press_sequentially("My half-typed", delay=10)
    # the agent rewrites the same slide before the autosave lands
    pdf.with_suffix(".narration").write_text(
        simple_narration("@intro-title\nThe agent's version.\n\n@euler-setup\nSecond.\n"),
        encoding="utf-8",
    )
    expect(tid(page, "conflict-mine")).to_contain_text("My half-typed", timeout=15_000)
    expect(tid(page, "conflict-theirs")).to_contain_text("The agent's version.")
    assert "The agent's version." in _sidecar(pdf)  # not overwritten while undecided
    tid(page, "conflict-keep").click()
    assert _eventually(lambda: "My half-typed" in _sidecar(pdf))


def test_block_editing_add_reorder_delete_and_attributes(
    page: Page, server: Server, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nFirst line.\n")
    page.goto(server(pdf))
    tid(page, "add-utterance").click()
    tid(page, "utext-1").fill("Second line.")
    tid(page, "add-pause").click()
    tid(page, "pause-secs-2").fill("1.5")
    tid(page, "pause-secs-2").press("Enter")
    tid(page, "seg-up-2").click()  # the pause moves between the lines
    tid(page, "usettings-2").click()  # voice/pace/note are folded away by default
    tid(page, "upace-2").select_option("slow")
    assert _eventually(
        lambda: (
            _sidecar(pdf).index("pause: 1.5") < _sidecar(pdf).index("Second line.")
            if "Second line." in _sidecar(pdf) and "pause: 1.5" in _sidecar(pdf)
            else False
        )
    ), _sidecar(pdf)
    assert _eventually(lambda: "pace: slow" in _sidecar(pdf))
    tid(page, "seg-del-1").click()  # delete the pause
    assert _eventually(lambda: "pause: 1.5" not in _sidecar(pdf))
    tid(page, "trans-out-kind").select_option("wipe")
    assert _eventually(lambda: "transition-out: wipeleft" in _sidecar(pdf)), _sidecar(pdf)


def test_generate_a_clip_and_see_it_turn_fresh(page: Page, server: Server, tmp_path: Path) -> None:
    pdf = _prep(tmp_path, "@intro-title\nMake me.\n")
    page.goto(server(pdf))
    gen = tid(page, "gen-seg-0")
    expect(gen).to_have_attribute("data-state", "missing")
    gen.click()
    expect(gen).to_have_attribute("data-state", "fresh", timeout=15_000)
    expect(tid(page, "audio-status")).to_have_text("1 of 1 clips generated")


@pytest.mark.timeout(120)
def test_preview_transport_and_deck_follow(page: Page, server: Server, tmp_path: Path) -> None:
    """Real <audio>: play, clock, speed, stop — and the editor follows a deck preview."""
    pdf = _prep(tmp_path, "@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    page.goto(server(pdf, stub_seconds=2.0))
    play = tid(page, "play-slide")
    play.click()
    expect(play).to_have_attribute("data-state", "playing", timeout=30_000)
    expect(tid(page, "time")).to_contain_text("/ 0:0")
    tid(page, "speed").click()
    tid(page, "speed").click()
    assert _eventually(
        lambda: page.evaluate("() => document.querySelector('audio')?.playbackRate") == 1.5
    )
    tid(page, "stop").click()
    expect(play).to_have_attribute("data-state", "idle")
    expect(tid(page, "time")).to_have_text("")
    tid(page, "play-deck").click()
    expect(tid(page, "counter")).to_have_text("Slide 2 / 6", timeout=30_000)


def test_keyboard_deck_switching(page: Page, server: Server, tmp_path: Path) -> None:
    decks = []
    for week, stem in (("week01", "intro"), ("week02", "advanced")):
        folder = tmp_path / week
        folder.mkdir()
        pdf = folder / f"{stem}.pdf"
        pdf.write_bytes(MARKED.read_bytes())
        (folder / f"{stem}.narration").write_text(
            simple_narration(f"@intro-title\nLine in {stem}.\n"), encoding="utf-8"
        )
        decks.append(pdf)
    url = server(decks[0], root=tmp_path)
    page.goto(url.rsplit("/d/", 1)[0] + "/")  # start at the library
    page.get_by_text("intro", exact=True).first.click()
    expect(tid(page, "deck-switcher")).to_contain_text("intro")
    page.locator("body").click(position={"x": 700, "y": 30})
    page.keyboard.press("Alt+ArrowRight")
    expect(tid(page, "deck-switcher")).to_contain_text("advanced")
    page.keyboard.press("Control+k")
    tid(page, "switcher-input").fill("intro")
    page.keyboard.press("Enter")
    expect(tid(page, "deck-switcher")).to_contain_text("intro")
    expect(tid(page, "utext-0")).to_have_value("Line in intro.")


@pytest.mark.timeout(120)
def test_a_review_round_with_the_agent(page: Page, server: Server, tmp_path: Path) -> None:
    """Start, compare a changed slide, send a note, see the agent's reply arrive, accept."""
    import pymupdf

    from slidesonnet.review import ops

    pdf = _prep(tmp_path, "@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    page.goto(server(pdf))
    tid(page, "console-tab-review").click()
    tid(page, "review-start").click()
    expect(tid(page, "review-clear")).to_be_visible()
    doc = pymupdf.open(pdf)  # the author recompiles with slide 2 changed
    doc[1].insert_text((40, 200), "a new line on the slide", fontsize=16)
    doc.saveIncr()
    doc.close()
    tid(page, "thumb-1").click()
    expect(tid(page, "stage-before")).to_be_visible(timeout=20_000)  # before | now
    note = tid(page, "slide-note")
    note.fill("Why did this change?")
    note.press("Enter")
    expect(page.get_by_text("Why did this change?")).to_be_visible()
    conv = ops.open_slide_conversations(pdf)[0].id
    ops.reply(pdf, conv, "To show the next step.", author="agent")
    expect(page.get_by_text("To show the next step.")).to_be_visible(timeout=15_000)
    expect(tid(page, "thumb-review-1")).to_have_text("your turn")
    tid(page, f"accept-{conv}").click()
    expect(tid(page, "thumb-review-1")).to_have_text("accepted")
