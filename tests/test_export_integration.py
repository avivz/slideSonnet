"""Integration tests for export/subs (ffmpeg, pdftoppm, and Kokoro).

Never uses a paid cloud engine. Marked integration so CI's unit-only run skips them.
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


# Block grammar (indented), with a centered wipe on the intro→setup boundary.
_SIDECAR_WIPE = """\
@intro-title
  utterance:
    text: Welcome to the demo.
  transition-out: wipeleft 0.6

@euler-setup
  utterance:
    text: Here is the setup.
"""


def _prep_pair(tmp_path: Path) -> tuple[Path, Path]:
    """A cut deck and a wipe deck in sibling dirs, sharing the marked PDF."""
    cut_dir, wipe_dir = tmp_path / "cut", tmp_path / "wipe"
    cut_dir.mkdir()
    wipe_dir.mkdir()
    cut = prep_marked_deck(cut_dir, _SIDECAR)
    wipe = prep_marked_deck(wipe_dir)
    (wipe.parent / "marked.narration").write_text(_SIDECAR_WIPE, encoding="utf-8")
    return cut, wipe


def test_centered_transition_preserves_total_duration(tmp_path: Path) -> None:
    # A centered overlay transition is absorbed (D/2 from each side), so the
    # exported deck is the same length as the all-cut render — not longer.
    cut, wipe = _prep_pair(tmp_path)
    out_cut = tmp_path / "cut.mp4"
    out_wipe = tmp_path / "wipe.mp4"
    api.export(cut, out_cut, silent=True)
    api.export(wipe, out_wipe, silent=True)
    assert get_duration(out_wipe) == pytest.approx(get_duration(out_cut), abs=0.15)


@pytest.mark.skipif(
    importlib.util.find_spec("kokoro") is None,
    reason="kokoro not installed",
)
def test_centered_transition_with_audio_muxes_track(tmp_path: Path) -> None:
    # The audible path assembles a silent video and muxes the continuous track;
    # the result must carry an audio stream and stay ~as long as the all-cut deck.
    cut, wipe = _prep_pair(tmp_path)
    out_cut = tmp_path / "cut.mp4"
    out_wipe = tmp_path / "wipe.mp4"
    api.export(cut, out_cut, engine="kokoro")
    api.export(wipe, out_wipe, engine="kokoro")
    assert get_duration(out_wipe, stream="audio") > 0
    assert get_duration(out_wipe) == pytest.approx(get_duration(out_cut), abs=0.2)


@pytest.mark.skipif(
    importlib.util.find_spec("kokoro") is None,
    reason="kokoro not installed",
)
def test_export_and_subs_write_identical_subtitles(tmp_path: Path) -> None:
    """`export` and a follow-up `subs` must agree byte-for-byte on a warm cache.

    They reach the timeline by different routes — export from the synthesis
    results it is about to concatenate, subs by re-resolving each clip from the
    cache — and a recipe that runs both would otherwise overwrite the good file
    with a disagreeing one.
    """
    pdf = _prep(tmp_path)
    result = api.export(pdf, tmp_path / "out.mp4", engine="kokoro", subtitles="srt")
    exported = result.subtitles[0].read_text(encoding="utf-8")

    standalone = tmp_path / "standalone.srt"
    api.write_subs(pdf, standalone, engine="kokoro")
    assert standalone.read_text(encoding="utf-8") == exported


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
