"""Tests for the editor's browser-opening resolution (no server launched)."""

from __future__ import annotations

from slidesonnet.gui.app import (
    app_invocation,
    apply_url,
    browser_invocation,
    find_chromium,
)


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


# --- {url} substitution ---


def test_apply_url_appends_when_no_placeholder() -> None:
    assert apply_url(["wslview"], "http://x:8080") == ["wslview", "http://x:8080"]


def test_apply_url_substitutes_placeholder() -> None:
    assert apply_url(["msedge.exe", "--app={url}"], "http://x:8080") == [
        "msedge.exe",
        "--app=http://x:8080",
    ]


# --- chromium detection for --app ---


def test_find_chromium_wsl_picks_first_existing() -> None:
    edge = "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe"
    exe = find_chromium(wsl=True, exists=lambda p: p == edge, which=lambda _n: None)
    assert exe == edge


def test_find_chromium_wsl_none_found() -> None:
    assert find_chromium(wsl=True, exists=lambda _p: False, which=lambda _n: None) is None


def test_find_chromium_desktop_uses_path() -> None:
    exe = find_chromium(
        wsl=False,
        exists=lambda _p: False,
        which=lambda n: "/usr/bin/chromium" if n == "chromium" else None,
    )
    assert exe == "/usr/bin/chromium"


def test_app_invocation_builds_app_flag() -> None:
    edge = "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe"
    cmd = app_invocation(None, wsl=True, exists=lambda p: p == edge, which=lambda _n: None)
    assert cmd == [edge, "--app={url}"]


def test_app_invocation_honors_explicit_browser() -> None:
    cmd = app_invocation("msedge.exe", wsl=True, exists=lambda _p: False, which=lambda _n: None)
    assert cmd == ["msedge.exe", "--app={url}"]


def test_app_invocation_none_when_no_chromium() -> None:
    assert app_invocation(None, wsl=True, exists=lambda _p: False, which=lambda _n: None) is None
