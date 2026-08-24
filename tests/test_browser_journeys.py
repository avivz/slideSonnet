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
from tests.conftest import prep_marked_deck as _prep
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

    def __call__(
        self,
        pdf: Path,
        *,
        real_tts: bool = False,
        stub_seconds: float = 1.0,
        library_root: Path | None = None,
    ) -> str: ...


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

    def start(
        pdf: Path,
        *,
        real_tts: bool = False,
        stub_seconds: float = 1.0,
        library_root: Path | None = None,
    ) -> str:
        port = _free_port()
        # NiceGUI's ui.run special-cases PYTEST_*/NICEGUI_* env vars (its own
        # screen-test mode); the subprocess is a REAL server, so drop them.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "NICEGUI_"))}
        env["SLIDESONNET_EDIT_PDF"] = str(pdf)
        env["SLIDESONNET_TEST_PORT"] = str(port)
        env["SLIDESONNET_TEST_STUB_SECONDS"] = str(stub_seconds)
        if real_tts:
            env["SLIDESONNET_TEST_REAL_TTS"] = "1"
        if library_root is not None:
            env["SLIDESONNET_LIB_ROOT"] = str(library_root)
        # run from the deck's tmp dir so NiceGUI's app.storage.general (the
        # auto-build checkbox persists there) lands in .nicegui/ under tmp_path
        # — isolated per deck, never leaking the flag between browser subprocesses
        proc = subprocess.Popen([sys.executable, str(LAUNCHER)], env=env, cwd=str(pdf.parent))
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
# journey 2: type, then act WITHOUT blurring first
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_typing_then_generating_without_blur_uses_the_typed_text(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    """Regression guard: type → Generate with no blur synthesizes the NEW text.

    Safe because NiceGUI textareas sync their value per keystroke over the
    ordered websocket, so every update lands before the click event does.
    """
    pdf = _prep(tmp_path, "@intro-title\nOld words.\n")
    page.goto(editor_server(pdf))
    box = marked(page, "utext-0").locator("textarea")
    expect(box).to_have_value("Old words.")
    box.click()
    box.fill("")
    box.press_sequentially("Brand new words.")
    marked(page, "gen-seg-0").click()  # straight to Generate — no blur-click elsewhere
    # generation runs on the background queue (no toast); enqueue_segment flushes
    # the typed text to disk first, so the worker synthesizes the NEW words
    new_hash = text_hash("Brand new words.")
    assert _eventually(
        lambda: any(f.name.startswith(new_hash) for f in audio_dir(pdf).glob("*.wav")),
        timeout=30.0,
    ), (
        "synthesized the stale text, not the typed one "
        f"(cache: {[f.name for f in audio_dir(pdf).glob('*.wav')]})"
    )
    assert "Brand new words." in _sidecar(tmp_path)


# --------------------------------------------------------------------------
# journey 3: typing during deck playback vs the cue flip
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_editing_during_deck_playback_defers_the_cue_flip(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    """While a narration field is focused, playback must not yank the editor.

    A cue flip rebuilds the block editor, destroying the textarea under the
    user's fingers (history: text used to be truncated mid-word at the flip).
    The flip is deferred while a field is focused; following resumes on blur.
    """
    pdf = _prep(tmp_path, "@intro-title\nHello.\n\n@euler-setup\nWorld.\n")
    page.goto(editor_server(pdf, stub_seconds=2.0))
    marked(page, "play-deck").click()
    expect(page.get_by_text("Preview ready").first).to_be_visible(timeout=30_000)
    # type slowly enough that slide 2's cue flip would land mid-sentence (the
    # stub track flips after ~3s; 57 chars at 120 ms/keystroke span ~7s)
    sentence = "The quick brown fox jumps over the lazy dog, twice over."
    box = marked(page, "utext-0").locator("textarea")
    box.click()
    box.fill("")
    box.press_sequentially(sentence, delay=120)
    # the flip was deferred while we typed: the editor stayed on this slide
    # and the textarea kept every keystroke
    expect(page.locator(".ss-counter")).to_have_text("Slide 1 / 6")
    expect(box).to_have_value(sentence)
    marked(page, "stop").click()  # focus leaves the field: blur commits the edit
    assert _eventually(lambda: sentence in _sidecar(tmp_path)), (
        f"typed sentence missing from the sidecar; it has: {_sidecar(tmp_path)!r}"
    )


@pytest.mark.timeout(120)
def test_transition_morph_overlay_runs_during_deck_preview(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    """A wipe leaving slide 1 should animate in the preview, not hard-flip.

    The preview overlay (window.ssMorph) plays a browser-side approximation of
    the exported xfade against the audio clock, completing at the cue boundary.
    We can't assert pixels, but we can catch the overlay toggling ``ss-on`` for
    its morph window while the deck plays.
    """
    pdf = _prep(tmp_path, "@intro-title\nHello there friends.\n\n@euler-setup\nWorld.\n")
    sidecar = tmp_path / "marked.narration"
    text = sidecar.read_text(encoding="utf-8")
    sidecar.write_text(text + "  transition-out: wipeleft 1.2\n", encoding="utf-8")
    page.goto(editor_server(pdf, stub_seconds=2.0))
    marked(page, "play-deck").click()
    expect(page.get_by_text("Preview ready").first).to_be_visible(timeout=30_000)

    def overlay_on() -> bool:
        return bool(
            page.evaluate(
                "() => document.querySelector('.ss-morph')?.classList.contains('ss-on') ?? false"
            )
        )

    assert _eventually(overlay_on, timeout=15.0), "morph overlay never activated during preview"


@pytest.mark.timeout(120)
def test_single_slide_preview_transitions_gated_by_the_toggle(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    """The single-slide-transitions toggle (off by default) gates the in/out morph.

    Off: a single-slide play is a plain cut (no overlay). On: it animates the
    slide's own in/out transitions as before.
    """
    pdf = _prep(tmp_path, "@intro-title\nHello there friends.\n\n@euler-setup\nWorld.\n")
    sidecar = tmp_path / "marked.narration"
    text = sidecar.read_text(encoding="utf-8")
    # slide 1 fades in and wipes out; preview-only, so write the sidecar directly
    sidecar.write_text(
        text.replace(
            "@intro-title\n",
            "@intro-title\n  transition-in: fade 0.8\n  transition-out: wipeleft 0.8\n",
        ),
        encoding="utf-8",
    )
    page.goto(editor_server(pdf, stub_seconds=2.0))

    def overlay_on() -> bool:
        return bool(
            page.evaluate(
                "() => document.querySelector('.ss-morph')?.classList.contains('ss-on') ?? false"
            )
        )

    # default: toggle off → single-slide play is a plain cut, no morph overlay
    marked(page, "play-slide").click()
    expect(page.get_by_text("Preview ready").first).to_be_visible(timeout=30_000)
    assert not _eventually(overlay_on, timeout=4.0), "morph played with the toggle off"

    # turn the toggle on → the in/out transitions animate
    marked(page, "single-slide-transitions").click()
    marked(page, "stop").click()
    marked(page, "play-slide").click()
    expect(page.get_by_text("Preview ready").first).to_be_visible(timeout=30_000)
    assert _eventually(overlay_on, timeout=15.0), "single-slide morph never activated when enabled"


@pytest.mark.timeout(120)
def test_editing_a_generated_utterance_flips_badge_before_blur(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    """Typing in a generated utterance flips its badge amber before any blur; undo restores it.

    This is the keystroke/timing half the in-process sim can't see — it writes
    ``.value`` synchronously and never fires the per-keystroke value-change while
    the field stays focused.
    """
    pdf = _prep(tmp_path, "@intro-title\nHello there.\n")
    page.goto(editor_server(pdf, stub_seconds=1.0))

    def badge() -> str:
        return str(
            page.evaluate(
                """() => {
                    const b = document.querySelector('.ss-marker-gen-seg-0');
                    if (!b) return '?';
                    if (b.className.includes('text-positive')) return 'green';
                    if (b.className.includes('text-warning')) return 'amber';
                    return 'other';
                }"""
            )
        )

    marked(page, "gen-seg-0").click()  # stub TTS generates instantly
    assert _eventually(lambda: badge() == "green", timeout=15.0), "clip never showed generated"

    box = marked(page, "utext-0").locator("textarea")
    box.click()
    box.press_sequentially("!", delay=10)  # one keystroke, focus retained (no blur)
    assert _eventually(lambda: badge() == "amber", timeout=4.0), "badge didn't flip on edit"

    box.press("Backspace")  # undo back to the original text, still focused
    assert _eventually(lambda: badge() == "green", timeout=4.0), "badge didn't revert on undo"


@pytest.mark.timeout(120)
def test_speed_control_sets_playback_rate_on_the_audio_element(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    """Cycling the speed control sets the real HTML5 audio.playbackRate, pitch-preserved.

    The in-process sim can't run JS, so the actual playbackRate assignment is
    only observable in a real browser. The chosen rate must also survive the
    track (re)load that a play press triggers.
    """
    pdf = _prep(tmp_path, "@intro-title\nHello there friends.\n")
    page.goto(editor_server(pdf, stub_seconds=2.0))
    expect(page.get_by_text("Slide 1 / 6")).to_be_visible()  # let the editor settle first

    # NiceGUI's ui.audio renders the <audio> element itself with the ss-audio class.
    def audio_rate() -> float:
        return float(
            page.evaluate("() => document.querySelector('audio.ss-audio')?.playbackRate ?? -1")
        )

    def preserves_pitch() -> bool:
        return bool(
            page.evaluate("() => document.querySelector('audio.ss-audio')?.preservesPitch ?? false")
        )

    marked(page, "speed").click()  # → 1.25×
    marked(page, "speed").click()  # → 1.5×
    expect(marked(page, "speed")).to_have_text("1.5×")
    assert _eventually(lambda: audio_rate() == 1.5, timeout=5.0), "playbackRate not applied"
    assert preserves_pitch(), "preservesPitch should keep 2× natural, not chipmunked"

    # a play press reloads the track (set_source) — the chosen speed must stick
    marked(page, "play-slide").click()
    expect(page.get_by_text("Preview ready").first).to_be_visible(timeout=30_000)
    assert _eventually(lambda: audio_rate() == 1.5, timeout=5.0), "speed reset on track reload"


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
    gen = marked(page, "gen-seg-0")
    expect(gen).to_contain_text("graphic_eq")  # nothing cached: plain generate

    gen.click()
    # background queue: the button spins, then settles on the re-generate
    # affordance once the clip lands (no toast to wait on anymore)
    expect(gen).to_contain_text("autorenew", timeout=540_000)  # fully cached
    wavs = list(audio_dir(pdf).glob("*.wav"))
    assert len(wavs) == 1, f"expected one cached clip, found {wavs}"
    clip = wavs[0]
    first_mtime = clip.stat().st_mtime_ns

    gen.click()  # re-generate: force a fresh take
    assert _eventually(lambda: clip.stat().st_mtime_ns != first_mtime, timeout=120.0), (
        "force synth did not rewrite the clip"
    )
    expect(gen).to_contain_text("autorenew", timeout=120_000)  # cached again

    # a PROPER blur-edit: type, then click elsewhere so blur commits the text
    box = marked(page, "utext-0").locator("textarea")
    box.click()
    box.fill("A different narration line.")
    page.locator(".ss-id").click()
    assert _eventually(lambda: "A different narration line." in _sidecar(tmp_path))
    expect(gen).to_contain_text("graphic_eq")  # new text means uncached again

    gen.click()
    new_hash = text_hash("A different narration line.")
    assert _eventually(
        lambda: any(f.name.startswith(new_hash) for f in audio_dir(pdf).glob("*.wav")),
        timeout=120.0,
    ), "no cache entry for the blur-edited text"
    expect(gen).to_contain_text("autorenew", timeout=30_000)  # cached again


# --------------------------------------------------------------------------
# journey 4b: auto-build generates on a REAL blur after the debounce
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_auto_build_generates_edited_slide_on_blur(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    """Story: with 'Auto-generate as I edit' on, typing a slide then blurring it
    generates its audio in the background after the debounce — no generate click.

    This is the focus/blur + debounce path the in-process sim can't see: it
    writes widget values synchronously and never fires a real blur. Stub TTS, so
    the only delay is the ~2.5s debounce.
    """
    pdf = _prep(tmp_path, "@intro-title\nHello.\n")  # only intro-title is narrated
    page.goto(editor_server(pdf))
    # enable auto-build; the one-time sweep finds no other narrated slide to fill
    marked(page, "auto-build").click()
    box = marked(page, "utext-0").locator("textarea")
    box.click()
    box.fill("")
    box.press_sequentially("Quietly generated in the background.")
    page.locator(".ss-id").click()  # real blur → save → debounced auto-build
    new_hash = text_hash("Quietly generated in the background.")
    assert _eventually(
        lambda: any(f.name.startswith(new_hash) for f in audio_dir(pdf).glob("*.wav")),
        timeout=20.0,  # ~2.5s debounce + stub synth + slack
    ), "auto-build did not generate the edited slide's audio after blur"
    # and it lands as the cached (green) state without any generate click
    expect(marked(page, "gen-seg-0")).to_contain_text("autorenew", timeout=10_000)


# --------------------------------------------------------------------------
# journey 5: structured block editing
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_block_editing_add_attrs_reorder_delete(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path)  # no sidecar: intro-title starts empty
    # The per-utterance picker offers *named* voices only (raw engine ids are
    # deliberately not listed), so the deck needs a name defined to pick one.
    (tmp_path / "slidesonnet.toml").write_text(
        '[voices.guest]\nkokoro = "af_bella"\n', encoding="utf-8"
    )
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
    # the option reads "guest (af_bella)" — the name, with its engine voice greyed
    page.get_by_role("option", name="guest").first.click()
    assert _eventually(lambda: "voice: guest" in _sidecar(tmp_path))

    marked(page, "upace-0").click()
    page.get_by_role("option", name="slow", exact=True).click()
    assert _eventually(lambda: "pace: slow" in _sidecar(tmp_path))

    note = marked(page, "udirect-0").locator("input")
    note.click()
    note.fill("warmly")
    page.locator(".ss-id").click()  # blur commits
    assert _eventually(lambda: "direct: warmly" in _sidecar(tmp_path))

    # A *trailing* pause is the block's end-silence field, not a reorderable card
    # (split_edge_silences), so it can't be moved past — reordering needs a
    # second utterance to swap with.
    marked(page, "add-utterance").click()
    second = marked(page, "utext-1").locator("textarea")
    second.click()
    second.fill("Second spoken line.")
    page.locator(".ss-id").click()  # blur commits
    assert _eventually(lambda: "text: Second spoken line." in _sidecar(tmp_path))
    # The sidecar landing only says the *server* committed; a structural commit
    # then rebuilds the cards, and clicking a reorder arrow mid-rebuild hits a
    # detached button. Wait for the rebuilt DOM to carry both lines first.
    expect(marked(page, "utext-1").locator("textarea")).to_have_value("Second spoken line.")
    expect(marked(page, "utext-0").locator("textarea")).to_have_value("First spoken line.")

    marked(page, "seg-down-0").click()  # first line moves below the second
    assert _eventually(
        lambda: (
            "text: Second spoken line." in _sidecar(tmp_path)
            and _sidecar(tmp_path).index("text: Second") < _sidecar(tmp_path).index("text: First")
        )
    )

    # Same rebuild race as above: the reorder rebuilt the cards, so wait until
    # index 0 actually *is* the second line before clicking its delete button.
    expect(marked(page, "utext-0").locator("textarea")).to_have_value("Second spoken line.")

    marked(page, "seg-del-0").click()  # "Second" sits at index 0 now — delete it
    assert _eventually(lambda: "text: Second spoken line." not in _sidecar(tmp_path))
    assert "text: First spoken line." in _sidecar(tmp_path)


# --------------------------------------------------------------------------
# journey 6: transitions persist
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_transition_out_family_and_direction_persist(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    pdf = _prep(tmp_path, "@intro-title\nHi.\n")
    page.goto(editor_server(pdf))

    # pick a family from the short Type list, then a direction; stored as the
    # recomposed flat xfade name (Wipe + Up -> wipeup).
    marked(page, "trans-out").click()
    page.get_by_role("option", name="Wipe", exact=True).click()
    marked(page, "trans-out-dir").click()
    page.get_by_role("option", name="Up", exact=True).click()
    assert _eventually(lambda: "transition-out: wipeup 0.5" in _sidecar(tmp_path))

    row = page.locator(".ss-transition", has=marked(page, "trans-out"))
    secs = row.locator(".ss-trans-secs input")
    secs.click()
    secs.fill("1.2")
    page.locator(".ss-id").click()  # blur commits
    assert _eventually(lambda: "transition-out: wipeup 1.2" in _sidecar(tmp_path))

    marked(page, "Next").click()
    expect(page.get_by_text("Slide 2 / 6")).to_be_visible()
    marked(page, "Previous").click()
    expect(page.get_by_text("Slide 1 / 6")).to_be_visible()
    expect(row.locator(".ss-trans-secs input")).to_have_value("1.2")
    assert "transition-out: wipeup 1.2" in _sidecar(tmp_path)


@pytest.mark.timeout(120)
def test_incoming_transition_matches_previous_slide_out(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    """A slide's 'Transition in' mirrors the previous slide's 'Transition out' —
    they are one boundary and must never disagree (the reported UI mismatch)."""
    pdf = _prep(tmp_path, "@intro-title\nHi.\n\n@euler-setup\nThere.\n")
    page.goto(editor_server(pdf))

    # set slide 1's outgoing transition to a left wipe
    marked(page, "trans-out").click()
    page.get_by_role("option", name="Wipe", exact=True).click()
    marked(page, "trans-out-dir").click()
    page.get_by_role("option", name="Left", exact=True).click()
    assert _eventually(lambda: "transition-out: wipeleft 0.5" in _sidecar(tmp_path))

    # slide 2's incoming transition now shows that same boundary, not a stale cut
    marked(page, "Next").click()
    expect(page.get_by_text("Slide 2 / 6")).to_be_visible()
    expect(marked(page, "trans-in")).to_contain_text("Wipe")
    expect(marked(page, "trans-in-dir")).to_contain_text("Left")


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


# --------------------------------------------------------------------------
# journey 11: an external sidecar edit revokes a loaded preview track
# --------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_external_edit_revokes_loaded_preview(
    page: Page, editor_server: ServerFactory, tmp_path: Path
) -> None:
    """Editing the sidecar on disk while a whole-deck preview is loaded must drop
    the stale track, so the next play rebuilds with the new transition/audio
    instead of resuming the old one (the morph schedule is baked into the track)."""
    from slidesonnet.narration.format import serialize_sidecar
    from slidesonnet.narration.model import PageNarration, Segment, Transition

    pdf = _prep(tmp_path, "@intro-title\nOne.\n\n@euler-setup\nTwo.\n")
    page.goto(editor_server(pdf, stub_seconds=2.0))
    play_all = marked(page, "play-deck")

    play_all.click()
    expect(page.get_by_text("Preview ready").first).to_be_visible(timeout=30_000)
    expect(play_all).to_contain_text("pause")  # deck track loaded and playing

    # change a slide's transition out on disk — the loaded track's morph is now stale
    sidecar = tmp_path / "marked.narration"
    sidecar.write_text(
        serialize_sidecar(
            [
                PageNarration(
                    slide_id="intro-title",
                    segments=[Segment.speech("One.")],
                    transition_out=Transition("wipeup", 0.5),
                ),
                PageNarration(slide_id="euler-setup", segments=[Segment.speech("Two.")]),
            ]
        ),
        encoding="utf-8",
    )
    later = time.time() + 5
    os.utime(sidecar, (later, later))

    expect(page.get_by_text("Deck files changed on disk — reloaded").first).to_be_visible(
        timeout=15_000
    )
    # the loaded track was revoked: the transport reset, so the button is back to
    # its idle icon (the next press will rebuild, not resume the stale preview)
    expect(play_all).to_contain_text("playlist_play", timeout=5_000)
    expect(page.locator(".ss-time")).to_have_text("")


# --------------------------------------------------------------------------
# deck switching: real keyboard, real navigation
# --------------------------------------------------------------------------


def _course(tmp_path: Path) -> tuple[Path, Path]:
    """Two narrated decks in one tree; returns (root, first deck)."""
    decks: list[Path] = []
    for week, stem in (("week01", "intro"), ("week02", "advanced")):
        folder = tmp_path / week
        folder.mkdir(parents=True, exist_ok=True)
        pdf = folder / f"{stem}.pdf"
        pdf.write_bytes(MARKED.read_bytes())
        (folder / f"{stem}.narration").write_text(
            simple_narration(f"@intro\nLine in {stem}.\n"), encoding="utf-8"
        )
        decks.append(pdf)
    return tmp_path, decks[0]


def test_library_card_opens_a_deck(
    editor_server: ServerFactory, page: Page, tmp_path: Path
) -> None:
    root, first = _course(tmp_path)
    url = editor_server(first, library_root=root)
    page.goto(url)
    expect(page.get_by_text("2 decks")).to_be_visible()
    page.get_by_text("intro", exact=True).first.click()
    expect(marked(page, "deck-switcher")).to_be_visible()
    expect(page.get_by_text("week01 / intro")).to_be_visible()


def test_alt_arrow_steps_to_the_next_deck(
    editor_server: ServerFactory, page: Page, tmp_path: Path
) -> None:
    """The real keyboard path: a background task must still reach the page's slots."""
    root, first = _course(tmp_path)
    url = editor_server(first, library_root=root)
    page.goto(url)
    page.get_by_text("intro", exact=True).first.click()
    expect(page.get_by_text("week01 / intro")).to_be_visible()
    page.locator("body").click(position={"x": 5, "y": 400})  # focus off any field
    page.keyboard.press("Alt+ArrowRight")
    expect(page.get_by_text("week02 / advanced")).to_be_visible()


def test_ctrl_k_opens_the_switcher_and_filters(
    editor_server: ServerFactory, page: Page, tmp_path: Path
) -> None:
    root, first = _course(tmp_path)
    url = editor_server(first, library_root=root)
    page.goto(url)
    page.get_by_text("intro", exact=True).first.click()
    expect(page.get_by_text("week01 / intro")).to_be_visible()
    page.locator("body").click(position={"x": 5, "y": 400})
    page.keyboard.press("Control+k")
    expect(marked(page, "switcher-input")).to_be_visible()
    marked(page, "switcher-input").locator("input").fill("advanced")
    expect(marked(page, "switcher-row-0")).to_be_visible()
    page.keyboard.press("Enter")
    expect(page.get_by_text("week02 / advanced")).to_be_visible()
