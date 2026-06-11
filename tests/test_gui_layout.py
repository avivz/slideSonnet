"""Layout helpers: slide aspect ratio, sidebar collapse math, dev-server launch."""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

from slidesonnet.exceptions import ParserError
from slidesonnet.gui.app import toggled_width
from slidesonnet.pdf.reader import page_aspect

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def test_page_aspect_of_fixture() -> None:
    assert page_aspect(MARKED) == pytest.approx(4 / 3, abs=1e-3)


def test_page_aspect_missing_pdf_raises() -> None:
    with pytest.raises(ParserError):
        page_aspect(FIXTURES / "does-not-exist.pdf")


def test_toggled_width_collapses_open_pane_and_remembers() -> None:
    assert toggled_width(180.0, 0.0, default=150.0) == (0.0, 180.0)


def test_toggled_width_restores_remembered_width() -> None:
    assert toggled_width(0.0, 220.0, default=150.0) == (220.0, 220.0)


def test_toggled_width_falls_back_to_default() -> None:
    assert toggled_width(0.0, 0.0, default=150.0) == (150.0, 0.0)


def test_clamp_keeps_panes_when_stage_has_room() -> None:
    from slidesonnet.gui.app import clamp_panel_widths

    assert clamp_panel_widths(1600, 150, 264, reserve=680) == (150, 264)


def test_clamp_shrinks_console_first() -> None:
    from slidesonnet.gui.app import clamp_panel_widths

    strip, console = clamp_panel_widths(1200, 300, 400, reserve=680)
    assert (strip, console) == (300, 220)


def test_clamp_shrinks_strip_when_console_exhausted() -> None:
    from slidesonnet.gui.app import clamp_panel_widths

    strip, console = clamp_panel_widths(1000, 400, 300, reserve=680)
    assert console == 0
    assert strip == 320


def test_clamp_never_negative() -> None:
    from slidesonnet.gui.app import clamp_panel_widths

    assert clamp_panel_widths(500, 200, 200, reserve=680) == (0, 0)


def test_responsive_collapses_open_panes_when_narrow() -> None:
    from slidesonnet.gui.app import ResponsivePanes

    r = ResponsivePanes(breakpoint_px=1100)
    collapse, restore = r.update(900, {"strip": True, "console": True})
    assert collapse == {"strip", "console"}
    assert restore == set()
    assert r.narrow is True


def test_responsive_ignores_already_closed_panes() -> None:
    from slidesonnet.gui.app import ResponsivePanes

    r = ResponsivePanes(breakpoint_px=1100)
    collapse, _restore = r.update(900, {"strip": True, "console": False})
    assert collapse == {"strip"}
    # widening restores only what the breakpoint collapsed, not the manual close
    _collapse, restore = r.update(1400, {"strip": False, "console": False})
    assert restore == {"strip"}


def test_responsive_no_action_within_same_mode() -> None:
    from slidesonnet.gui.app import ResponsivePanes

    r = ResponsivePanes(breakpoint_px=1100)
    assert r.update(1400, {"strip": True, "console": True}) == (set(), set())
    r.update(900, {"strip": True, "console": True})
    assert r.update(800, {"strip": False, "console": False}) == (set(), set())


def test_responsive_skips_restore_for_user_reopened_pane() -> None:
    from slidesonnet.gui.app import ResponsivePanes

    r = ResponsivePanes(breakpoint_px=1100)
    r.update(900, {"strip": True, "console": True})
    # user reopened the strip while narrow (overlay); it is already open on widen
    _collapse, restore = r.update(1400, {"strip": True, "console": False})
    assert restore == {"console"}


def test_dev_invocation_builds_module_runner() -> None:
    import sys

    from slidesonnet.gui.app import dev_invocation

    argv, env = dev_invocation(MARKED, sidecar_path=None, host="127.0.0.1", port=9000)
    assert argv == [sys.executable, "-m", "slidesonnet.gui.devserver"]
    assert env["SLIDESONNET_DEV_PDF"] == str(MARKED.resolve())
    assert env["SLIDESONNET_DEV_HOST"] == "127.0.0.1"
    assert env["SLIDESONNET_DEV_PORT"] == "9000"
    assert "SLIDESONNET_DEV_SIDECAR" not in env


def test_dev_invocation_forwards_browser_flags() -> None:
    from slidesonnet.gui.app import dev_invocation

    _argv, env = dev_invocation(
        MARKED,
        sidecar_path=None,
        host="h",
        port=1,
        browser="wslview",
        app_window=True,
        no_browser=True,
    )
    assert env["SLIDESONNET_DEV_BROWSER"] == "wslview"
    assert env["SLIDESONNET_DEV_APP"] == "1"
    assert env["SLIDESONNET_DEV_NO_BROWSER"] == "1"


def test_dev_invocation_passes_sidecar() -> None:
    from slidesonnet.gui.app import dev_invocation

    sidecar = FIXTURES / "some.narration"
    _argv, env = dev_invocation(MARKED, sidecar_path=sidecar, host="h", port=1)
    assert env["SLIDESONNET_DEV_SIDECAR"] == str(sidecar.resolve())


def test_devserver_module_imports_without_launching() -> None:
    # the __main__/__mp_main__ guard must keep a plain import side-effect free
    import slidesonnet.gui.devserver  # noqa: F401


def test_should_open_browser_when_no_client_ever_connects() -> None:
    from slidesonnet.gui.devserver import should_open_browser

    assert should_open_browser([0, 0]) is True
    assert should_open_browser([None, 0]) is True  # probe failure ≠ connected client


def test_should_not_reopen_when_old_tab_reconnected() -> None:
    from slidesonnet.gui.devserver import should_open_browser

    assert should_open_browser([0, 1]) is False
    assert should_open_browser([2]) is False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.integration
def test_dev_server_boots_and_prints_banner_once(tmp_path: Path) -> None:
    """Boot the real watcher+worker pair: banner exactly once, HTTP serving."""
    from slidesonnet.gui.app import dev_invocation

    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    port = _free_port()
    argv, extra_env = dev_invocation(
        pdf, sidecar_path=None, host="127.0.0.1", port=port, no_browser=True
    )
    env = {**os.environ, **extra_env}
    env.pop("PYTEST_CURRENT_TEST", None)  # else NiceGUI's is_pytest() hijacks ui.run
    proc = subprocess.Popen(
        argv,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.3)
        else:
            pytest.fail("dev server never opened its port")
    finally:
        proc.terminate()
        out, _ = proc.communicate(timeout=15)
    assert out.count("slideSonnet editor (dev, auto-reload)") == 1, out
