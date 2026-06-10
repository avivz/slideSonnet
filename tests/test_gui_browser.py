"""Tests for the editor's browser-opening resolution (no server launched)."""

from __future__ import annotations

from slidesonnet.gui.app import browser_invocation


def test_explicit_browser_flag_wins() -> None:
    opener, show = browser_invocation("wslview", wsl=True, wslview="/usr/bin/wslview")
    assert opener == ["wslview"]
    assert show is False


def test_explicit_browser_is_shlex_split() -> None:
    opener, show = browser_invocation("cmd.exe /c start", wsl=False)
    assert opener == ["cmd.exe", "/c", "start"]
    assert show is False


def test_env_browser_used_when_no_flag() -> None:
    opener, show = browser_invocation(None, env_browser="firefox.exe", wsl=False)
    assert opener == ["firefox.exe"]
    assert show is False


def test_flag_overrides_env() -> None:
    opener, _ = browser_invocation(
        "wslview", env_browser="firefox.exe", wsl=True, wslview="wslview"
    )
    assert opener == ["wslview"]


def test_wsl_prefers_wslview() -> None:
    opener, show = browser_invocation(None, wsl=True, wslview="/usr/bin/wslview")
    assert opener == ["/usr/bin/wslview"]
    assert show is False


def test_wsl_without_wslview_does_not_open_linux_browser() -> None:
    opener, show = browser_invocation(None, wsl=True, wslview=None)
    assert opener is None
    assert show is False  # never falls back to NiceGUI's Linux browser under WSL


def test_desktop_uses_nicegui_default() -> None:
    opener, show = browser_invocation(None, wsl=False)
    assert opener is None
    assert show is True
