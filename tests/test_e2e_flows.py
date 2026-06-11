"""End-to-end user journeys through the CLI, as a user would type them.

Unit-tier journeys cover scaffolding and id-reconciliation (no TTS/FFmpeg);
the full narrate→synthesize→export pipeline runs under the ``integration``
mark (kokoro + ffmpeg + pdftoppm) and is excluded from CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from slidesonnet.cli import main
from tests.conftest import write_pdf

FIXTURES = Path(__file__).parent / "fixtures"
MARKED = FIXTURES / "marked.pdf"


def _run(*args: str) -> Result:
    return CliRunner().invoke(main, list(args))


def test_journey_scaffold_recompile_merge(tmp_path: Path) -> None:
    """init → recompile adds a slide → check flags it → init --merge heals it."""
    pdf = write_pdf(tmp_path / "deck.pdf", ["alpha", "beta"])
    sidecar = tmp_path / "deck.narration"

    res = _run("init", str(pdf))
    assert res.exit_code == 0, res.output
    text = sidecar.read_text(encoding="utf-8")
    assert "@alpha" in text and "@beta" in text

    # a second init must refuse to clobber the user's narration
    res = _run("init", str(pdf))
    assert res.exit_code != 0
    assert "exists" in res.output

    # the user narrates, then recompiles the deck with a new slide
    sidecar.write_text("@alpha\nHello.\n\n@beta\nWorld.\n", encoding="utf-8")
    write_pdf(pdf, ["alpha", "beta", "gamma"])

    res = _run("check", str(pdf))
    assert res.exit_code == 0  # warnings don't fail the build
    assert "gamma" in res.output and "no narration" in res.output

    res = _run("init", str(pdf), "--merge")
    assert res.exit_code == 0, res.output
    text = sidecar.read_text(encoding="utf-8")
    assert "@gamma" in text
    assert "Hello." in text  # existing narration untouched

    res = _run("check", str(pdf))
    assert res.exit_code == 0
    assert "gamma" not in res.output or "no narration" not in res.output


def test_journey_rename_creates_orphan_error(tmp_path: Path) -> None:
    """Renaming a slide-id in the source orphans its narration: check must fail."""
    pdf = write_pdf(tmp_path / "deck.pdf", ["alpha", "beta"])
    (tmp_path / "deck.narration").write_text("@alpha\nHello.\n\n@beta\nWorld.\n", encoding="utf-8")
    write_pdf(pdf, ["alpha", "beta-v2"])  # recompile with a renamed id

    res = _run("check", str(pdf))
    assert res.exit_code != 0
    assert "beta" in res.output
    assert "no matching PDF page" in res.output


def test_journey_duplicate_ids_disambiguated(tmp_path: Path) -> None:
    """Duplicate \\ssid is auto-renamed (alpha, alpha-2) and warned, not fatal."""
    pdf = write_pdf(tmp_path / "deck.pdf", ["alpha", "alpha"])
    (tmp_path / "deck.narration").write_text("@alpha\nHello.\n", encoding="utf-8")
    res = _run("check", str(pdf))
    assert res.exit_code == 0  # warnings only
    assert "renamed to 'alpha-2'" in res.output

    # the renamed page is narratable under its new id, and init --merge offers it
    res = _run("init", str(pdf), "--merge")
    assert res.exit_code == 0
    assert "@alpha-2" in (tmp_path / "deck.narration").read_text(encoding="utf-8")


@pytest.mark.integration
def test_journey_narrate_synthesize_export_clean(tmp_path: Path) -> None:
    """The full happy path: init → narrate → tts → subs → export → clean."""
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(MARKED.read_bytes())

    assert _run("init", str(pdf)).exit_code == 0
    (tmp_path / "deck.narration").write_text(
        "@intro-title\nHello deck.\n\n@euler-setup\nOne more line. [pause 1]\n",
        encoding="utf-8",
    )

    res = _run("tts", str(pdf), "--engine", "kokoro")
    assert res.exit_code == 0, res.output
    cache = tmp_path / ".slidesonnet" / "audio"
    wavs = list(cache.glob("*.wav")) + list(cache.glob("*.mp3"))
    assert wavs, "synthesis must populate the content-addressed cache"

    srt = tmp_path / "deck.srt"
    res = _run("subs", str(pdf), "-o", str(srt))
    assert res.exit_code == 0, res.output
    assert "Hello deck." in srt.read_text(encoding="utf-8")

    mp4 = tmp_path / "deck.mp4"
    res = _run("export", str(pdf), "-o", str(mp4), "--engine", "kokoro")
    assert res.exit_code == 0, res.output
    assert mp4.exists() and mp4.stat().st_size > 10_000
    assert mp4.with_suffix(".srt").exists()  # default subtitles ride along

    # re-running tts is a no-op: everything already cached
    res = _run("tts", str(pdf), "--engine", "kokoro")
    assert res.exit_code == 0
    assert "0" in res.output

    res = _run("clean", str(pdf))
    assert res.exit_code == 0, res.output
    assert not (tmp_path / ".slidesonnet" / "render").exists()


@pytest.mark.integration
def test_journey_silent_export_needs_no_audio(tmp_path: Path) -> None:
    """A silent export works on a freshly scaffolded deck with zero synthesis."""
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(MARKED.read_bytes())
    assert _run("init", str(pdf)).exit_code == 0

    mp4 = tmp_path / "silent.mp4"
    res = _run("export", str(pdf), "-o", str(mp4), "--silent")
    assert res.exit_code == 0, res.output
    assert mp4.exists() and mp4.stat().st_size > 10_000
    assert not list((tmp_path / ".slidesonnet" / "audio").glob("*"))
