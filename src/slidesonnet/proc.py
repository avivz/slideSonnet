"""Running external tools (ffmpeg/ffprobe/pdftoppm) with uniform error mapping.

One place for the try/except dance every subprocess call was repeating, plus a
timeout so a wedged tool can never hang an export or the editor's worker
thread forever.
"""

from __future__ import annotations

import subprocess

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
