"""Central logging configuration for the slideSonnet CLI and editor.

Every module logs through ``logging.getLogger(__name__)`` (so every name lives
under the ``slidesonnet`` package logger), but those records only reach a human
once a handler is configured. This module does that in one place:

* :func:`configure_console_logging` installs a single console handler whose level
  comes from ``--quiet`` / ``--verbose`` / the ``SLIDESONNET_LOG`` env var. Called
  once at CLI (and editor) startup so any module's ``logger.info`` is visible.
* :func:`attach_file_handler` adds a size-rotating file handler — by default under
  the deck's ``.slidesonnet/`` cache — that always captures ``DEBUG`` detail for
  post-mortem diagnosis, independent of the (usually quieter) console level.

The console handler lives on the root logger (so third-party warnings surface
too); the file handler lives on the ``slidesonnet`` package logger, so the log
file stays focused on our own records rather than every library's debug chatter.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from slidesonnet.cache import cache_root

#: The package logger every module's ``getLogger(__name__)`` descends from.
PACKAGE_LOGGER = "slidesonnet"

#: Env var that sets the console level when no ``--quiet``/``--verbose`` is passed.
ENV_LEVEL = "SLIDESONNET_LOG"

#: Default log filename, written under the deck's ``.slidesonnet/`` cache.
LOG_FILENAME = "slidesonnet.log"

#: Rotation defaults: cap disk at ``max_bytes * (backup_count + 1)`` (~8 MB).
DEFAULT_MAX_BYTES = 2_000_000
DEFAULT_BACKUP_COUNT = 3

_CONSOLE_HANDLER_NAME = "slidesonnet-console"
_FILE_HANDLER_NAME = "slidesonnet-file"


class _ConsoleFormatter(logging.Formatter):
    """Bare message for INFO/DEBUG; ``LEVEL: message`` for warnings and errors.

    Progress lines (INFO) read as clean terminal output, while warnings and
    errors are clearly tagged.
    """

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno >= logging.WARNING:
            return f"{record.levelname}: {record.getMessage()}"
        return record.getMessage()


def resolve_console_level(
    *, quiet: bool = False, verbose: bool = False, env: str | None = None
) -> int:
    """Resolve the console log level. Explicit flags beat *env* beats INFO.

    *env* is a level name (e.g. ``"DEBUG"``); an unrecognized value is ignored.
    """
    if quiet and verbose:
        raise ValueError("quiet and verbose are mutually exclusive")
    if verbose:
        return logging.DEBUG
    if quiet:
        return logging.WARNING
    if env:
        level = logging.getLevelName(env.strip().upper())
        if isinstance(level, int):
            return level
    return logging.INFO


def configure_console_logging(level: int) -> None:
    """Install (or re-level) the single slideSonnet console handler on root.

    Idempotent: repeated calls adjust the level rather than stacking handlers.
    """
    root = logging.getLogger()
    handler = _named_handler(root, _CONSOLE_HANDLER_NAME)
    if handler is None:
        handler = logging.StreamHandler()
        handler.set_name(_CONSOLE_HANDLER_NAME)
        handler.setFormatter(_ConsoleFormatter())
        root.addHandler(handler)
    handler.setLevel(level)
    # Third-party loggers (no explicit level) inherit root; keep them as quiet as
    # the console. Our own package logger is set so it never filters out anything
    # a configured handler wants — handler levels do the real filtering.
    root.setLevel(level)
    _lower_package_level(level)


def attach_file_handler(
    path: Path,
    *,
    level: int = logging.DEBUG,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> RotatingFileHandler:
    """Attach a size-rotating file handler for ``slidesonnet`` records at *path*.

    Re-targets if called again (a process logs to one file), so the latest call
    wins rather than silently keeping a stale path. The file always captures down
    to *level* (DEBUG by default), independent of the console level.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    pkg = logging.getLogger(PACKAGE_LOGGER)
    existing = _named_handler(pkg, _FILE_HANDLER_NAME)
    if existing is not None:
        pkg.removeHandler(existing)
        existing.close()
    handler = RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.set_name(_FILE_HANDLER_NAME)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    pkg.addHandler(handler)
    _lower_package_level(level)
    return handler


def default_log_path(deck_path: Path) -> Path:
    """Where the log for *deck_path* lives by default (under its cache)."""
    return cache_root(deck_path) / LOG_FILENAME


def attach_deck_file_logging(
    deck_path: Path, *, override: Path | None = None, disabled: bool = False
) -> RotatingFileHandler | None:
    """Resolve and attach the run-log for *deck_path*.

    Precedence: *disabled* (``--no-log-file``) wins; then an explicit *override*
    (``--log-file``); then the deck's ``[logging]`` config; else the default under
    ``.slidesonnet/``. A failure to open the file is warned and swallowed — logging
    must never sink the command itself. Shared by the CLI and the dev server.
    """
    if disabled:
        return None
    try:
        if override is not None:
            return attach_file_handler(Path(override))
        from slidesonnet.config import load_config
        from slidesonnet.exceptions import SlideSonnetError
        from slidesonnet.models import LoggingConfig

        try:
            cfg = load_config(deck_path).logging
        except SlideSonnetError:
            # A broken slidesonnet.toml still gets a default log; the command's own
            # config load surfaces the real error to the user.
            cfg = LoggingConfig()
        if not cfg.enabled:
            return None
        path = Path(cfg.file) if cfg.file else default_log_path(deck_path)
        return attach_file_handler(
            path,
            level=logging.getLevelName(cfg.level),
            max_bytes=cfg.max_bytes,
            backup_count=cfg.backup_count,
        )
    except OSError as e:
        logging.getLogger(PACKAGE_LOGGER).warning("Could not open log file: %s", e)
        return None


def _lower_package_level(level: int) -> None:
    """Ensure the package logger emits at least down to *level* (never raises it)."""
    pkg = logging.getLogger(PACKAGE_LOGGER)
    current = pkg.level or logging.WARNING
    pkg.setLevel(min(current, level))


def _named_handler(logger: logging.Logger, name: str) -> logging.Handler | None:
    for handler in logger.handlers:
        if getattr(handler, "name", None) == name:
            return handler
    return None
