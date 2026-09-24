"""Tests for central logging configuration (slidesonnet.logging_setup)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from slidesonnet.logging_setup import (
    PACKAGE_LOGGER,
    attach_file_handler,
    configure_console_logging,
    default_log_path,
    resolve_console_level,
)

# ---- level resolution ----------------------------------------------------


def test_resolve_default_is_info() -> None:
    assert resolve_console_level() == logging.INFO


def test_resolve_quiet_is_warning() -> None:
    assert resolve_console_level(quiet=True) == logging.WARNING


def test_resolve_verbose_is_debug() -> None:
    assert resolve_console_level(verbose=True) == logging.DEBUG


def test_resolve_env_sets_level() -> None:
    assert resolve_console_level(env="DEBUG") == logging.DEBUG
    assert resolve_console_level(env="warning") == logging.WARNING


def test_resolve_invalid_env_falls_back_to_info() -> None:
    assert resolve_console_level(env="not-a-level") == logging.INFO


def test_resolve_flag_beats_env() -> None:
    assert resolve_console_level(verbose=True, env="ERROR") == logging.DEBUG
    assert resolve_console_level(quiet=True, env="DEBUG") == logging.WARNING


def test_resolve_quiet_and_verbose_conflict() -> None:
    with pytest.raises(ValueError):
        resolve_console_level(quiet=True, verbose=True)


# ---- console handler -----------------------------------------------------


def test_configure_console_is_idempotent() -> None:
    configure_console_logging(logging.INFO)
    configure_console_logging(logging.DEBUG)
    consoles = [h for h in logging.root.handlers if getattr(h, "name", "") == "slidesonnet-console"]
    assert len(consoles) == 1
    assert consoles[0].level == logging.DEBUG


def _console_shows(record: logging.LogRecord) -> bool:
    (console,) = [
        h for h in logging.root.handlers if getattr(h, "name", "") == "slidesonnet-console"
    ]
    return console.filter(record) is not False and record.levelno >= console.level


def _mismatch() -> logging.LogRecord:
    """The warning Kokoro's phonemizer emits for nearly every line it speaks."""
    return logging.LogRecord(
        "phonemizer",
        logging.WARNING,
        __file__,
        1,
        "words count mismatch on %s%% of the lines (%s/%s)",
        (100.0, 1, 1),
        None,
    )


def test_console_hides_phonemizer_word_count_noise() -> None:
    configure_console_logging(logging.INFO)
    assert not _console_shows(_mismatch())


def test_console_shows_phonemizer_noise_when_verbose() -> None:
    configure_console_logging(logging.DEBUG)
    assert _console_shows(_mismatch())


def test_console_keeps_other_phonemizer_warnings() -> None:
    configure_console_logging(logging.INFO)
    other = logging.LogRecord(
        "phonemizer", logging.WARNING, __file__, 1, "espeak not found", None, None
    )
    assert _console_shows(other)


# ---- file handler --------------------------------------------------------


def test_default_log_path_under_cache(tmp_path: Path) -> None:
    pdf = tmp_path / "deck.pdf"
    assert default_log_path(pdf) == tmp_path / ".slidesonnet" / "slidesonnet.log"


def test_attach_file_handler_writes_records(tmp_path: Path) -> None:
    log = tmp_path / "out.log"
    attach_file_handler(log)
    logging.getLogger(f"{PACKAGE_LOGGER}.unit").warning("hello-file")
    for h in logging.getLogger(PACKAGE_LOGGER).handlers:
        h.flush()
    assert "hello-file" in log.read_text(encoding="utf-8")


def test_file_handler_captures_debug_below_console_level(tmp_path: Path) -> None:
    """Console at INFO, but the file keeps DEBUG detail for diagnosis."""
    configure_console_logging(logging.INFO)
    log = tmp_path / "out.log"
    attach_file_handler(log, level=logging.DEBUG)
    logging.getLogger(f"{PACKAGE_LOGGER}.unit").debug("debug-only-detail")
    for h in logging.getLogger(PACKAGE_LOGGER).handlers:
        h.flush()
    assert "debug-only-detail" in log.read_text(encoding="utf-8")


def test_attach_file_handler_retargets_on_second_call(tmp_path: Path) -> None:
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    attach_file_handler(first)
    attach_file_handler(second)
    files = [h for h in logging.getLogger(PACKAGE_LOGGER).handlers if _is_file_handler(h)]
    assert len(files) == 1
    logging.getLogger(f"{PACKAGE_LOGGER}.unit").warning("only-in-second")
    for h in files:
        h.flush()
    assert second.exists()
    assert "only-in-second" in second.read_text(encoding="utf-8")
    assert "only-in-second" not in (first.read_text(encoding="utf-8") if first.exists() else "")


def test_file_handler_rotates_by_size(tmp_path: Path) -> None:
    log = tmp_path / "rot.log"
    attach_file_handler(log, max_bytes=200, backup_count=2)
    big = "x" * 80
    for _ in range(20):
        logging.getLogger(f"{PACKAGE_LOGGER}.unit").warning(big)
    for h in logging.getLogger(PACKAGE_LOGGER).handlers:
        h.flush()
    # Size-based rotation caps disk: the live file plus at most backup_count backups.
    assert log.exists()
    assert (tmp_path / "rot.log.1").exists()
    assert not (tmp_path / "rot.log.3").exists()


def _is_file_handler(handler: logging.Handler) -> bool:
    return getattr(handler, "name", "") == "slidesonnet-file"
