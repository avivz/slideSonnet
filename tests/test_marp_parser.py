"""Tests for MARP parser."""

import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import ParserError
from slidesonnet.models import SlideAnnotation
from slidesonnet.parsers.marp import MarpParser, _split_slides, _parse_slide, extract_images


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


def test_parse_unannotated(simple_md, caplog):
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 6: unannotated
    assert slides[5].annotation == SlideAnnotation.NONE
    assert "no annotation" in caplog.text


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


def test_triple_dash_inside_code_fence_not_a_separator():
    """D4: --- inside a fenced code block should not split slides."""
    text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide 1

        ```markdown
        ---
        title: example
        ---
        ```

        <!-- say: This slide has a code fence with dashes. -->

        ---

        # Slide 2

        <!-- say: Second slide. -->
    """)
    slides = _split_slides(text)
    assert len(slides) == 2
    assert "code fence with dashes" in slides[0]
    assert "Second slide" in slides[1]


def test_tilde_code_fence_not_a_separator():
    """--- inside a ~~~ fenced code block should not split slides."""
    text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide 1

        ~~~yaml
        ---
        key: value
        ---
        ~~~

        <!-- say: Tilde fence test. -->
    """)
    slides = _split_slides(text)
    assert len(slides) == 1
    assert "Tilde fence test" in slides[0]


def test_say_inside_code_fence_ignored():
    """D5: <!-- say: --> inside a fenced code block should not be parsed as narration."""
    slide_text = textwrap.dedent("""\
        # Example Slide

        ```html
        <!-- say: This is example code, not narration. -->
        ```

        <!-- say: Real narration outside the fence. -->
    """)
    slide = _parse_slide(1, slide_text, Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "Real narration" in slide.narration_raw
    assert "example code" not in slide.narration_raw


def test_silent_inside_code_fence_ignored():
    """<!-- silent --> inside a fenced code block should not mark the slide silent."""
    slide_text = textwrap.dedent("""\
        # Example Slide

        ```markdown
        <!-- silent -->
        ```

        <!-- say: This slide is narrated. -->
    """)
    slide = _parse_slide(1, slide_text, Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "narrated" in slide.narration_raw


def test_skip_inside_code_fence_ignored():
    """<!-- skip --> inside a fenced code block should not mark the slide as skipped."""
    slide_text = textwrap.dedent("""\
        # Example Slide

        ~~~html
        <!-- skip -->
        ~~~

        <!-- say: Not skipped. -->
    """)
    slide = _parse_slide(1, slide_text, Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "Not skipped" in slide.narration_raw


def test_only_say_inside_code_fence_no_annotation(caplog):
    """If the only say directive is inside a code block, slide has no annotation."""
    slide_text = textwrap.dedent("""\
        # Example Slide

        ```html
        <!-- say: This is inside a code block. -->
        ```
    """)
    slide = _parse_slide(1, slide_text, Path("test.md"))
    assert slide.annotation == SlideAnnotation.NONE
    assert "no annotation" in caplog.text


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


def test_empty_say_warns(caplog):
    slide = _parse_slide(1, "<!-- say: -->", Path("test.md"))
    assert slide.annotation == SlideAnnotation.SILENT
    assert "did you mean <!-- silent -->" in caplog.text


def test_has_narration_property():
    from slidesonnet.models import SlideNarration

    s = SlideNarration(index=1, annotation=SlideAnnotation.SAY, narration_raw="Hello")
    assert s.has_narration

    s2 = SlideNarration(index=2, annotation=SlideAnnotation.SAY, narration_raw="")
    assert not s2.has_narration

    s3 = SlideNarration(index=3, annotation=SlideAnnotation.SILENT)
    assert not s3.has_narration


# ---- Mocked tests for extract_images ----


class TestExtractImages:
    """Mocked tests for extract_images()."""

    @patch("slidesonnet.parsers.marp.subprocess.run")
    def test_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.md"
        source.write_text("---\nmarp: true\n---\n# Hi")
        output_dir = tmp_path / "out"

        def side_effect(cmd, **kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "slides.001.png").touch()
            (output_dir / "slides.002.png").touch()
            return MagicMock()

        mock_run.side_effect = side_effect

        result = extract_images(source, output_dir)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "marp"
        assert "--images" in cmd
        assert "png" in cmd
        assert len(result) == 2

    @patch("slidesonnet.parsers.marp.subprocess.run", side_effect=FileNotFoundError)
    def test_marp_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.md"
        source.write_text("dummy")
        with pytest.raises(ParserError):
            extract_images(source, tmp_path / "out")

    @patch(
        "slidesonnet.parsers.marp.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "marp", stderr="marp error"),
    )
    def test_marp_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.md"
        source.write_text("dummy")
        with pytest.raises(ParserError):
            extract_images(source, tmp_path / "out")

    @patch("slidesonnet.parsers.marp.subprocess.run")
    def test_extensionless_glob_pattern(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """When .png pattern finds nothing, falls back to extensionless numbered files."""
        source = tmp_path / "slides.md"
        source.write_text("dummy")
        output_dir = tmp_path / "out"

        def side_effect(cmd, **kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            # Newer marp produces extensionless numbered files
            (output_dir / "slides.001").touch()
            (output_dir / "slides.002").touch()
            return MagicMock()

        mock_run.side_effect = side_effect

        result = extract_images(source, output_dir)
        assert len(result) == 2
