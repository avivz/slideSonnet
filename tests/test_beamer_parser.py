"""Tests for Beamer parser."""

from pathlib import Path

import pytest

from slidesonnet.models import SlideAnnotation
from slidesonnet.parsers.beamer import (
    BeamerParser,
    _extract_braced,
    _extract_frames,
    _find_say_commands,
    _parse_frame,
    _strip_latex,
)


@pytest.fixture
def simple_tex():
    return Path(__file__).parent / "fixtures" / "simple.tex"


def test_extract_frames(simple_tex):
    text = simple_tex.read_text()
    frames = _extract_frames(text)
    assert len(frames) == 6


def test_parse_basic_say(simple_tex):
    parser = BeamerParser()
    slides = parser.parse(simple_tex, Path("/tmp/build"))

    assert slides[0].annotation == SlideAnnotation.SAY
    assert "Welcome to this lecture" in slides[0].narration_raw
    assert slides[0].voice is None


def test_parse_say_with_params(simple_tex):
    parser = BeamerParser()
    slides = parser.parse(simple_tex, Path("/tmp/build"))

    assert slides[1].annotation == SlideAnnotation.SAY
    assert "handshaking theorem" in slides[1].narration_raw
    assert slides[1].voice == "alice"
    assert slides[1].pace == "slow"


def test_nested_braces(simple_tex):
    parser = BeamerParser()
    slides = parser.parse(simple_tex, Path("/tmp/build"))

    # Frame 3 has nested braces
    assert slides[2].annotation == SlideAnnotation.SAY
    assert "bold" in slides[2].narration_raw
    assert "nested braces" in slides[2].narration_raw


def test_parse_silent(simple_tex):
    parser = BeamerParser()
    slides = parser.parse(simple_tex, Path("/tmp/build"))

    assert slides[3].annotation == SlideAnnotation.SILENT


def test_parse_skip(simple_tex):
    parser = BeamerParser()
    slides = parser.parse(simple_tex, Path("/tmp/build"))

    # Frame 5 (index 4) has \slidesonnetskip
    assert slides[4].annotation == SlideAnnotation.SKIP


def test_parse_unannotated(simple_tex, capsys):
    parser = BeamerParser()
    slides = parser.parse(simple_tex, Path("/tmp/build"))

    # Frame 6 (index 5) is unannotated
    assert slides[5].annotation == SlideAnnotation.NONE
    captured = capsys.readouterr()
    assert "no annotation" in captured.err


def test_extract_braced_simple():
    text = "{hello world}"
    content, end = _extract_braced(text, 0)
    assert content == "hello world"
    assert end == len(text)


def test_extract_braced_nested():
    text = "{outer {inner} more}"
    content, end = _extract_braced(text, 0)
    assert content == "outer {inner} more"


def test_extract_braced_deeply_nested():
    text = "{a {b {c} d} e}"
    content, end = _extract_braced(text, 0)
    assert content == "a {b {c} d} e"


def test_find_say_commands():
    text = r"\say{Hello} and \say[voice=bob]{World}"
    matches = _find_say_commands(text)
    assert len(matches) == 2
    assert matches[0] == ("", "Hello")
    assert matches[1] == ("voice=bob", "World")


def test_strip_latex():
    assert _strip_latex(r"\textbf{bold}") == "bold"
    assert "hello" in _strip_latex(r"\emph{hello}")
    # Simple commands removed
    result = _strip_latex(r"\item First point")
    assert "First point" in result


def test_empty_say_warns(capsys):
    slide = _parse_frame(1, r"\say{}", Path("test.tex"))
    assert slide.annotation == SlideAnnotation.SILENT
    captured = capsys.readouterr()
    assert "did you mean" in captured.err
