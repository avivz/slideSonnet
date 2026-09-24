"""Unit tests for the streaming tool runner that follows ffmpeg's ``-progress``."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from slidesonnet.proc import parse_progress_seconds, run_tool_with_progress


class ToolError(Exception):
    pass


def _script(tmp_path: Path, body: str) -> list[str]:
    """A fake tool: an executable Python script, so injected flags land in its argv."""
    path = tmp_path / "tool.py"
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(0o755)
    return [str(path)]


def _run(cmd: list[str], sink: list[float], timeout: float = 30.0) -> None:
    run_tool_with_progress(
        cmd,
        on_time=sink.append,
        error_cls=ToolError,
        install_hint="the tool",
        fail_message="tool failed",
        timeout=timeout,
    )


@pytest.mark.parametrize(
    ("line", "seconds"),
    [
        ("out_time_us=2500000", 2.5),
        ("out_time_ms=1500000", 1.5),  # ffmpeg's misnamed key is microseconds too
        ("out_time_us=N/A", None),
        ("out_time=00:00:01.000000", None),  # the clock form is ignored; *_us is exact
        ("frame=12", None),
        ("progress=continue", None),
    ],
)
def test_parse_progress_seconds(line: str, seconds: float | None) -> None:
    assert parse_progress_seconds(line) == seconds


def test_streams_output_time_while_the_tool_runs(tmp_path: Path) -> None:
    cmd = _script(
        tmp_path,
        """
        import sys
        for us in (0, 1_000_000, 2_500_000):
            print(f"frame=1\\nout_time_us={us}\\nprogress=continue", flush=True)
            print("chatty ffmpeg banner " * 200, file=sys.stderr, flush=True)
        print("out_time_us=3000000\\nprogress=end", flush=True)
        """,
    )
    seen: list[float] = []
    _run(cmd, seen)
    assert seen == [0.0, 1.0, 2.5, 3.0]


def test_adds_the_progress_flags(tmp_path: Path) -> None:
    cmd = _script(
        tmp_path, "import sys\nprint(' '.join(sys.argv[1:]), file=sys.stderr)\nsys.exit(3)"
    )
    with pytest.raises(ToolError) as err:
        _run(cmd, [])
    assert "-progress pipe:1 -nostats" in str(err.value)


def test_failure_reports_stderr(tmp_path: Path) -> None:
    cmd = _script(tmp_path, "import sys\nprint('bad input', file=sys.stderr)\nsys.exit(1)")
    with pytest.raises(ToolError, match=r"tool failed:\n.*bad input"):
        _run(cmd, [])


def test_missing_binary_names_the_install(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="'no-such-tool-xyz' not found. Install the tool."):
        _run(["no-such-tool-xyz"], [])


def test_hung_tool_is_killed_at_the_timeout(tmp_path: Path) -> None:
    cmd = _script(tmp_path, "import time\ntime.sleep(30)")
    with pytest.raises(ToolError, match="timed out after 1s"):
        _run(cmd, [], timeout=1.0)
