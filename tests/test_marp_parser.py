"""Tests for MARP parser."""

import textwrap
from pathlib import Path

from slidesonnet.models import SlideAnnotation
from slidesonnet.parsers.marp import MarpParser, _split_slides, _parse_slide


def test_split_slides(simple_md):
    text = simple_md.read_text()
    slides = _split_slides(text)
    assert len(slides) == 6  # 3 say + 1 silent + 1 skip + 1 unannotated


def test_parse_say_directive(simple_md):
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 1: basic say
    assert slides[0].annotation == SlideAnnotation.SAY
    assert "Welcome to this lecture" in slides[0].narration_raw
    assert slides[0].voice is None
    assert slides[0].pace is None


def test_parse_say_with_params(simple_md):
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 2: say with voice and pace
    assert slides[1].annotation == SlideAnnotation.SAY
    assert "graph is a mathematical structure" in slides[1].narration_raw
    assert slides[1].voice == "alice"
    assert slides[1].pace == "slow"


def test_parse_silent(simple_md):
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 4: silent
    assert slides[3].annotation == SlideAnnotation.SILENT


def test_parse_skip(simple_md):
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 5: skip
    assert slides[4].annotation == SlideAnnotation.SKIP
    assert slides[4].is_skip


def test_parse_unannotated(simple_md, capsys):
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 6: unannotated
    assert slides[5].annotation == SlideAnnotation.NONE
    captured = capsys.readouterr()
    assert "no annotation" in captured.err


def test_multiline_say():
    text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide 1

        <!-- say: This is a long narration
             that spans multiple lines
             in the source file. -->
    """)
    slides = _split_slides(text)
    slide = _parse_slide(1, slides[0], Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "long narration" in slide.narration_raw
    assert "multiple lines" in slide.narration_raw
    # Whitespace should be normalized
    assert "\n" not in slide.narration_raw


def test_multiple_say_blocks():
    text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide 1

        <!-- say: First paragraph. -->

        Some content.

        <!-- say: Second paragraph. -->
    """)
    slides = _split_slides(text)
    slide = _parse_slide(1, slides[0], Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "First paragraph." in slide.narration_raw
    assert "Second paragraph." in slide.narration_raw


def test_regular_comment_ignored():
    text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide 1

        <!-- This is just a regular comment -->

        <!-- say: Actual narration. -->
    """)
    slides = _split_slides(text)
    slide = _parse_slide(1, slides[0], Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "Actual narration." in slide.narration_raw
    assert "regular comment" not in slide.narration_raw


def test_empty_say_warns(capsys):
    slide = _parse_slide(1, "<!-- say: -->", Path("test.md"))
    assert slide.annotation == SlideAnnotation.SILENT
    captured = capsys.readouterr()
    assert "did you mean <!-- silent -->" in captured.err


def test_has_narration_property():
    from slidesonnet.models import SlideNarration

    s = SlideNarration(index=1, annotation=SlideAnnotation.SAY, narration_raw="Hello")
    assert s.has_narration

    s2 = SlideNarration(index=2, annotation=SlideAnnotation.SAY, narration_raw="")
    assert not s2.has_narration

    s3 = SlideNarration(index=3, annotation=SlideAnnotation.SILENT)
    assert not s3.has_narration
