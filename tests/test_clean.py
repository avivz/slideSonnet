"""Tests for cache cleanup preservation levels."""

from __future__ import annotations

from pathlib import Path

from slidesonnet.cache import audio_dir, cache_root, render_dir
from slidesonnet.clean import clean


def _seed(tmp_path: Path) -> Path:
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    ad = audio_dir(pdf)
    ad.mkdir(parents=True)
    # valid 3-part names: {text_hash}.{backend}.{config_hash}.{ext}
    (ad / "aaaa.kokoro.bbbb.wav").write_bytes(b"x")
    (ad / "cccc.elevenlabs.dddd.mp3").write_bytes(b"y")
    rd = render_dir(pdf)
    rd.mkdir(parents=True)
    (rd / "page-0001.png").write_bytes(b"img")
    return pdf


def test_keep_api_drops_kokoro_keeps_cloud(tmp_path: Path) -> None:
    pdf = _seed(tmp_path)
    clean(pdf, keep="api")
    ad = audio_dir(pdf)
    assert not (ad / "aaaa.kokoro.bbbb.wav").exists()
    assert (ad / "cccc.elevenlabs.dddd.mp3").exists()
    assert not render_dir(pdf).exists()  # renders always removed


def test_keep_nothing_removes_all(tmp_path: Path) -> None:
    pdf = _seed(tmp_path)
    result = clean(pdf, keep="nothing")
    assert not cache_root(pdf).exists()
    assert result.removed_files >= 3


def test_clean_no_cache(tmp_path: Path) -> None:
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    result = clean(pdf, keep="api")
    assert result.removed_files == 0
