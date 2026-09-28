"""slidesonnet.sty plain vs final builds, compiled for real (local-only).

A plain build (the default) hides position-dependent decorations — page
numbers, navigation, metropolis progress bars — while keeping their space, so
inserting a slide leaves every later slide's pixels unchanged and the layout
matches the final (``\\ssfinal``) build exactly.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import fitz
import pytest

from slidesonnet import api
from slidesonnet.pdf.reader import is_final_build, is_plain_build, read_page_ids

pytestmark = pytest.mark.integration

DECK = r"""\documentclass{beamer}
\usetheme[progressbar=frametitle]{metropolis}
\setbeamertemplate{footline}[frame number]
\usepackage{slidesonnet}
\begin{document}
\begin{frame}{First}\ssid{one} Hello world, some body text.\end{frame}
%INSERT%
\begin{frame}{Second}\ssid{two} More text.\vfill Bottom line.\end{frame}
\begin{frame}{Third}\ssid{three} Third.\end{frame}
\end{document}
"""
INSERTED = r"\begin{frame}{Inserted}\ssid{ins} A new slide.\end{frame}"


def _need_latex() -> None:
    if shutil.which("pdflatex") is None or shutil.which("kpsewhich") is None:
        pytest.skip("pdflatex not installed")
    found = subprocess.run(
        ["kpsewhich", "beamerthememetropolis.sty"], capture_output=True, text=True, check=False
    )
    if not found.stdout.strip():
        pytest.skip("metropolis theme not installed")


def _compile(tmp: Path, name: str, *, insert: bool = False, final: bool = False) -> Path:
    (tmp / f"{name}.tex").write_text(
        DECK.replace("%INSERT%", INSERTED if insert else ""), encoding="utf-8"
    )
    pre = r"\def\ssfinal{}" if final else ""
    for _ in range(2):  # the second pass settles the total frame count
        subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", pre + rf"\input{{{name}}}"],
            cwd=tmp,
            capture_output=True,
            check=True,
            timeout=120,
        )
    return tmp / f"{name}.pdf"


def _pixmaps(pdf: Path) -> list[fitz.Pixmap]:
    with fitz.open(pdf) as doc:
        return [page.get_pixmap(dpi=100) for page in doc]


def _word_boxes(pdf: Path) -> list[list[tuple[float, float, str]]]:
    """(x0, y0, word) per page, minus the invisible markers."""
    with fitz.open(pdf) as doc:
        return [
            [
                (round(w[0], 2), round(w[1], 2), w[4])
                for w in page.get_text("words")
                if not w[4].startswith("SSID:") and w[4] not in ("SSFINAL", "SSPLAIN")
            ]
            for page in doc
        ]


@pytest.fixture
def builds(tmp_path: Path) -> dict[str, Path]:
    _need_latex()
    api.write_sty(tmp_path)
    return {
        "plain": _compile(tmp_path, "plain"),
        "inserted": _compile(tmp_path, "inserted", insert=True),
        "final": _compile(tmp_path, "final", final=True),
    }


def test_insert_leaves_later_plain_slides_pixel_identical(builds: dict[str, Path]) -> None:
    before, after = _pixmaps(builds["plain"]), _pixmaps(builds["inserted"])
    assert read_page_ids(builds["inserted"]) == ["one", "ins", "two", "three"]
    # one → one, two → two (shifted by one), three → three (shifted by one)
    for old, new in ((0, 0), (1, 2), (2, 3)):
        assert before[old].samples == after[new].samples, f"page {old + 1} changed"


def test_final_build_has_same_layout_plus_decorations(builds: dict[str, Path]) -> None:
    plain_words, final_words = _word_boxes(builds["plain"]), _word_boxes(builds["final"])
    for plain_page, final_page in zip(plain_words, final_words, strict=True):
        # every plain word sits at the same spot in the final build...
        assert set(plain_page) <= set(final_page)
        # ...and the final build adds only the page counter
        extra = [w for w in final_page if w not in plain_page]
        assert extra and all(w[2].replace("/", "").isdigit() or w[2] == "/" for w in extra)


def test_build_kind_is_detectable(builds: dict[str, Path]) -> None:
    assert is_final_build(builds["plain"]) is False and is_plain_build(builds["plain"])
    assert is_final_build(builds["final"]) is True and not is_plain_build(builds["final"])
    assert read_page_ids(builds["final"]) == ["one", "two", "three"]
