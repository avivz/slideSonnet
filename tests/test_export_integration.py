"""Integration tests for export/subs (ffmpeg, pdftoppm, and Kokoro).

Never uses ElevenLabs. Marked integration so CI's unit-only run skips them.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from slidesonnet import api
from slidesonnet.video.composer import get_duration
from tests.conftest import prep_marked_deck

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"

_SIDECAR = """\
@intro-title
Welcome to the demo. [pause 0.5]

@euler-setup
Here is the setup.
"""


def _prep(tmp_path: Path) -> Path:
    return prep_marked_deck(tmp_path, _SIDECAR)


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
    importlib.util.find_spec("kokoro") is None,
    reason="kokoro not installed",
)
def test_export_tts_kokoro(tmp_path: Path) -> None:
    pdf = _prep(tmp_path)
    out = tmp_path / "out.mp4"
    result = api.export(pdf, out, engine="kokoro", subtitles="srt")
    assert out.exists() and out.stat().st_size > 0
    assert result.silent is False
    assert result.duration > 0
    # the cached audio makes a second export cheap (cache hit)
    n_new = api.synthesize_deck(pdf, engine="kokoro")
    assert n_new == 0


@pytest.mark.skipif(
    importlib.util.find_spec("kokoro") is None,
    reason="kokoro not installed",
)
def test_multi_voice_within_one_slide(tmp_path: Path) -> None:
    """Two utterances on one slide in different voices = two distinct Kokoro calls."""
    pdf = tmp_path / "marked.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    (tmp_path / "marked.narration").write_text(
        "@intro-title\n"
        "  utterance:\n"
        "    voice: af_heart\n"
        "    text: This line is in one voice.\n"
        "  utterance:\n"
        "    voice: am_michael\n"
        "    text: And this line answers in another.\n",
        encoding="utf-8",
    )
    n_new = api.synthesize_deck(pdf, engine="kokoro")
    assert n_new == 2  # two separate synthesis calls, one per voice
    from slidesonnet.cache import audio_dir

    clips = sorted(audio_dir(pdf).glob("*.wav"))
    assert len(clips) == 2
    # distinct content (different voice ids) -> distinct content-addressed filenames
    assert clips[0].stem != clips[1].stem
    # a re-run is fully cached
    assert api.synthesize_deck(pdf, engine="kokoro") == 0
