"""Integration tests for export/subs (ffmpeg, pdftoppm, and Piper).

Never uses ElevenLabs. Marked integration so CI's unit-only run skips them.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from slidesonnet import api
from slidesonnet.video.composer import get_duration

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"

_SIDECAR = """\
@intro-title
Welcome to the demo. [pause 0.5]

@euler-setup
Here is the setup.
"""


def _prep(tmp_path: Path) -> Path:
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    (tmp_path / "marked.narration").write_text(_SIDECAR, encoding="utf-8")
    return pdf


pytestmark = pytest.mark.integration


def test_export_silent(tmp_path: Path) -> None:
    pdf = _prep(tmp_path)
    out = tmp_path / "out.mp4"
    result = api.export(pdf, out, silent=True, subtitles="both")
    assert out.exists() and out.stat().st_size > 0
    assert result.silent is True
    assert get_duration(out) > 0
    assert {p.suffix for p in result.subtitles} == {".srt", ".vtt"}


def test_subs_estimate_no_render(tmp_path: Path) -> None:
    pdf = _prep(tmp_path)
    out = tmp_path / "out.srt"
    api.write_subs(pdf, out, timing="estimate")
    text = out.read_text(encoding="utf-8")
    assert "Welcome to the demo." in text
    assert "-->" in text


@pytest.mark.skipif(
    shutil.which("piper") is None
    and not (Path(__file__).resolve().parents[1] / ".venv/bin/piper").exists(),
    reason="piper not installed",
)
def test_export_tts_piper(tmp_path: Path) -> None:
    pdf = _prep(tmp_path)
    out = tmp_path / "out.mp4"
    result = api.export(pdf, out, engine="piper", subtitles="srt")
    assert out.exists() and out.stat().st_size > 0
    assert result.silent is False
    assert result.duration > 0
    # the cached audio makes a second export cheap (cache hit)
    n_new = api.synthesize_deck(pdf, engine="piper")
    assert n_new == 0
