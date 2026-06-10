"""Tests for the dependency doctor."""

from __future__ import annotations

from slidesonnet.doctor import check_pymupdf, check_python, run_all_checks


def test_python_ok() -> None:
    assert check_python().status == "ok"


def test_pymupdf_detected() -> None:
    # PyMuPDF is a hard dependency, installed in the dev env
    assert check_pymupdf().status == "ok"


def test_run_all_checks_groups() -> None:
    groups = dict(run_all_checks())
    assert "Core (always required)" in groups
    names = {c.name for c in groups["Core (always required)"]}
    assert {"ffmpeg", "ffprobe", "pdftoppm", "PyMuPDF"} <= names
    # marp must be gone from the new toolchain
    all_names = {c.name for _, checks in run_all_checks() for c in checks}
    assert "marp-cli" not in all_names
