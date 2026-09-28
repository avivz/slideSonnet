"""How the editor opens a browser: desktop, WSL, explicit commands, app windows."""

from __future__ import annotations

import pytest

from slidesonnet.server.launch import (
    app_invocation,
    apply_url,
    browser_invocation,
    find_chromium,
)

EDGE = "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe"


@pytest.mark.parametrize(
    ("flag", "env", "wsl", "wslview", "opener", "use_default"),
    [
        ("wslview", None, True, "/usr/bin/wslview", ["wslview"], False),  # explicit flag wins
        ("cmd.exe /c start", None, False, None, ["cmd.exe", "/c", "start"], False),  # shlex-split
        (None, "firefox.exe", False, None, ["firefox.exe"], False),  # $SLIDESONNET_BROWSER
        ("wslview", "firefox.exe", True, "wslview", ["wslview"], False),  # flag over env
        (None, None, True, "/usr/bin/wslview", ["/usr/bin/wslview"], False),  # WSL: wslview
        (None, None, True, None, None, False),  # WSL, no wslview: never a Linux browser
        (None, None, False, None, None, True),  # desktop: the default browser
    ],
)
def test_browser_choice(
    flag: str | None,
    env: str | None,
    wsl: bool,
    wslview: str | None,
    opener: list[str] | None,
    use_default: bool,
) -> None:
    assert browser_invocation(flag, env_browser=env, wsl=wsl, wslview=wslview) == (
        opener,
        use_default,
    )


def test_url_is_substituted_or_appended() -> None:
    assert apply_url(["wslview"], "http://x:8080") == ["wslview", "http://x:8080"]
    assert apply_url(["msedge.exe", "--app={url}"], "http://x:8080") == [
        "msedge.exe",
        "--app=http://x:8080",
    ]


@pytest.mark.parametrize(
    ("wsl", "exists", "which", "found"),
    [
        (True, {EDGE}, {}, EDGE),  # WSL: Edge/Chrome under /mnt/c
        (True, set(), {}, None),
        (False, set(), {"chromium": "/usr/bin/chromium"}, "/usr/bin/chromium"),  # desktop: PATH
    ],
)
def test_chromium_detection_for_app_windows(
    wsl: bool, exists: set[str], which: dict[str, str], found: str | None
) -> None:
    assert find_chromium(wsl=wsl, exists=exists.__contains__, which=which.get) == found


def test_app_window_command() -> None:
    none = {"exists": lambda _p: False, "which": lambda _n: None}
    assert app_invocation(None, wsl=True, exists=lambda p: p == EDGE, which=lambda _n: None) == [
        EDGE,
        "--app={url}",
    ]
    assert app_invocation("msedge.exe", wsl=True, **none) == ["msedge.exe", "--app={url}"]  # type: ignore[arg-type]
    assert app_invocation(None, wsl=True, **none) is None  # type: ignore[arg-type]
