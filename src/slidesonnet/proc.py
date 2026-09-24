"""Running external tools (ffmpeg/ffprobe/pdftoppm) with uniform error mapping.

One place for the try/except dance every subprocess call was repeating, plus a
timeout so a wedged tool can never hang an export or the editor's worker
thread forever. :func:`run_tool_with_progress` is the streaming variant for the
long ffmpeg passes, reporting how far the output has got as it runs.
"""

from __future__ import annotations

import subprocess
import tempfile
import threading
from collections.abc import Callable

# Generous per-invocation ceiling: every call here is one slide's compose, one
# clip's probe, or one rasterize — minutes-long is already pathological.
DEFAULT_TIMEOUT = 600.0


def run_tool(
    cmd: list[str],
    *,
    error_cls: type[Exception],
    install_hint: str,
    fail_message: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run *cmd*, mapping missing-binary / failure / hang to *error_cls*.

    *install_hint* names the package to install when the binary is missing;
    *fail_message* prefixes the tool's stderr on a non-zero exit.
    """
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise error_cls(f"'{cmd[0]}' not found. Install {install_hint}.") from None
    except subprocess.TimeoutExpired as e:
        raise error_cls(f"{fail_message}: timed out after {int(timeout)}s") from e
    except subprocess.CalledProcessError as e:
        raise error_cls(f"{fail_message}:\n{e.stderr}") from e


def parse_progress_seconds(line: str) -> float | None:
    """Output time from one line of ffmpeg's ``-progress`` stream, else ``None``.

    ``out_time_us`` is microseconds; the older ``out_time_ms`` key is also
    microseconds despite its name. Other keys and ``N/A`` values give ``None``.
    """
    key, sep, value = line.strip().partition("=")
    if not sep or key not in {"out_time_us", "out_time_ms"}:
        return None
    try:
        return int(value) / 1_000_000
    except ValueError:
        return None


def run_tool_with_progress(
    cmd: list[str],
    *,
    on_time: Callable[[float], None],
    error_cls: type[Exception],
    install_hint: str,
    fail_message: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """Run an ffmpeg *cmd*, calling *on_time* with seconds of output as it is written.

    Same error mapping as :func:`run_tool`. ``-progress pipe:1 -nostats`` is
    added after the program name, and the key=value stream ffmpeg writes to
    stdout is read line by line while stderr goes to a temporary file (a pipe
    left unread could fill up and stall ffmpeg). A watchdog kills the tool at
    *timeout*.
    """
    full = [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]
    with tempfile.TemporaryFile(mode="w+") as err:
        try:
            proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=err, text=True)
        except FileNotFoundError:
            raise error_cls(f"'{cmd[0]}' not found. Install {install_hint}.") from None
        timed_out = threading.Event()

        def _kill() -> None:
            timed_out.set()
            proc.kill()

        watchdog = threading.Timer(timeout, _kill)
        watchdog.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                seconds = parse_progress_seconds(line)
                if seconds is not None:
                    on_time(seconds)
            returncode = proc.wait()
        finally:
            watchdog.cancel()
            if proc.poll() is None:  # on_time raised: don't leave ffmpeg running
                proc.kill()
                proc.wait()
        if timed_out.is_set():
            raise error_cls(f"{fail_message}: timed out after {int(timeout)}s")
        if returncode != 0:
            err.seek(0)
            raise error_cls(f"{fail_message}:\n{err.read()}")
