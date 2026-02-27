"""Tests for MARP parser."""

import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import ParserError
from slidesonnet.models import SlideAnnotation
from slidesonnet.parsers.marp import (
    MarpParser,
    _parse_slide,
    _split_slides,
    extract_images,
)


def test_split_slides(simple_md: Path) -> None:
    text = simple_md.read_text()
    slides = _split_slides(text)
    assert len(slides) == 7  # 3 say + 1 silent + 1 skip + 1 unannotated + 1 fragment


def test_parse_say_directive(simple_md: Path) -> None:
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 1: basic say
    assert slides[0].annotation == SlideAnnotation.SAY
    assert "Welcome to this lecture" in slides[0].narration_raw
    assert slides[0].voice is None
    assert slides[0].pace is None


def test_parse_say_with_params(simple_md: Path) -> None:
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 2: say with voice and pace
    assert slides[1].annotation == SlideAnnotation.SAY
    assert "graph is a mathematical structure" in slides[1].narration_raw
    assert slides[1].voice == "alice"
    assert slides[1].pace == "slow"


def test_parse_silent(simple_md: Path) -> None:
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 4: silent
    assert slides[3].annotation == SlideAnnotation.SILENT


def test_parse_skip(simple_md: Path) -> None:
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 5: skip
    assert slides[4].annotation == SlideAnnotation.SKIP
    assert slides[4].is_skip


def test_parse_unannotated(simple_md: Path, caplog: pytest.LogCaptureFixture) -> None:
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slide 6: unannotated
    assert slides[5].annotation == SlideAnnotation.NONE
    assert "no annotation" in caplog.text


def test_parse_fragment_slide(simple_md: Path) -> None:
    """Fragmented slide in fixture expands into 2 sub-slides."""
    parser = MarpParser()
    slides = parser.parse(simple_md, Path("/tmp/build"))

    # Slides 7-8: fragment slide expands to 2 sub-slides (indices 7, 8)
    assert len(slides) == 8  # 6 single + 2 from fragment
    assert slides[6].annotation == SlideAnnotation.SAY
    assert slides[6].narration_raw == "Here is point A."
    assert slides[6].index == 7
    assert slides[7].annotation == SlideAnnotation.SAY
    assert slides[7].narration_raw == "And now point B."
    assert slides[7].index == 8


def test_multiline_say() -> None:
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
    [slide] = _parse_slide(1, slides[0], Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "long narration" in slide.narration_raw
    assert "multiple lines" in slide.narration_raw
    # Whitespace should be normalized
    assert "\n" not in slide.narration_raw


def test_multiple_say_blocks() -> None:
    """Two says produce two sub-slides with sequential indices."""
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
    result = _parse_slide(1, slides[0], Path("test.md"))
    assert len(result) == 2
    assert result[0].annotation == SlideAnnotation.SAY
    assert result[0].narration_raw == "First paragraph."
    assert result[0].index == 1
    assert result[1].annotation == SlideAnnotation.SAY
    assert result[1].narration_raw == "Second paragraph."
    assert result[1].index == 2


def test_triple_dash_inside_code_fence_not_a_separator() -> None:
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


def test_tilde_code_fence_not_a_separator() -> None:
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


def test_say_inside_code_fence_ignored() -> None:
    """D5: <!-- say: --> inside a fenced code block should not be parsed as narration."""
    slide_text = textwrap.dedent("""\
        # Example Slide

        ```html
        <!-- say: This is example code, not narration. -->
        ```

        <!-- say: Real narration outside the fence. -->
    """)
    [slide] = _parse_slide(1, slide_text, Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "Real narration" in slide.narration_raw
    assert "example code" not in slide.narration_raw


def test_silent_inside_code_fence_ignored() -> None:
    """<!-- silent --> inside a fenced code block should not mark the slide silent."""
    slide_text = textwrap.dedent("""\
        # Example Slide

        ```markdown
        <!-- silent -->
        ```

        <!-- say: This slide is narrated. -->
    """)
    [slide] = _parse_slide(1, slide_text, Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "narrated" in slide.narration_raw


def test_skip_inside_code_fence_ignored() -> None:
    """<!-- skip --> inside a fenced code block should not mark the slide as skipped."""
    slide_text = textwrap.dedent("""\
        # Example Slide

        ~~~html
        <!-- skip -->
        ~~~

        <!-- say: Not skipped. -->
    """)
    [slide] = _parse_slide(1, slide_text, Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "Not skipped" in slide.narration_raw


def test_only_say_inside_code_fence_no_annotation(caplog: pytest.LogCaptureFixture) -> None:
    """If the only say directive is inside a code block, slide has no annotation."""
    slide_text = textwrap.dedent("""\
        # Example Slide

        ```html
        <!-- say: This is inside a code block. -->
        ```
    """)
    [slide] = _parse_slide(1, slide_text, Path("test.md"))
    assert slide.annotation == SlideAnnotation.NONE
    assert "no annotation" in caplog.text


def test_regular_comment_ignored() -> None:
    text = textwrap.dedent("""\
        ---
        marp: true
        ---

        # Slide 1

        <!-- This is just a regular comment -->

        <!-- say: Actual narration. -->
    """)
    slides = _split_slides(text)
    [slide] = _parse_slide(1, slides[0], Path("test.md"))
    assert slide.annotation == SlideAnnotation.SAY
    assert "Actual narration." in slide.narration_raw
    assert "regular comment" not in slide.narration_raw


def test_empty_say_warns(caplog: pytest.LogCaptureFixture) -> None:
    [slide] = _parse_slide(1, "<!-- say: -->", Path("test.md"))
    assert slide.annotation == SlideAnnotation.SILENT
    assert "did you mean <!-- silent -->" in caplog.text


def test_has_narration_property() -> None:
    from slidesonnet.models import SlideNarration

    s = SlideNarration(index=1, annotation=SlideAnnotation.SAY, narration_raw="Hello")
    assert s.has_narration

    s2 = SlideNarration(index=2, annotation=SlideAnnotation.SAY, narration_raw="")
    assert not s2.has_narration

    s3 = SlideNarration(index=3, annotation=SlideAnnotation.SILENT)
    assert not s3.has_narration


def test_parse_slide_positional_says() -> None:
    """Multiple says without explicit targeting get positional indices."""
    text = (
        "# Slide\n\n* A\n<!-- say: First -->\n* B\n<!-- say: Second -->\n* C\n<!-- say: Third -->"
    )
    result = _parse_slide(1, text, Path("test.md"))
    assert len(result) == 3
    assert result[0].index == 1
    assert result[0].narration_raw == "First"
    assert result[1].index == 2
    assert result[1].narration_raw == "Second"
    assert result[2].index == 3
    assert result[2].narration_raw == "Third"


def test_parse_slide_explicit_targeting() -> None:
    """Says with explicit slide= targeting."""
    text = "# Slide\n\n* A\n* B\n<!-- say(slide=2): Both points -->"
    result = _parse_slide(1, text, Path("test.md"))
    assert len(result) == 2
    assert result[0].annotation == SlideAnnotation.SILENT  # no say targets sub-slide 1
    assert result[1].annotation == SlideAnnotation.SAY
    assert result[1].narration_raw == "Both points"
    assert result[1].index == 2


def test_parse_slide_explicit_bare_number() -> None:
    """Say with bare number targeting: <!-- say(2): text -->."""
    text = "# Slide\n\n* A\n* B\n* C\n<!-- say(1): First -->\n<!-- say(3): All three -->"
    result = _parse_slide(1, text, Path("test.md"))
    assert len(result) == 3
    assert result[0].narration_raw == "First"
    assert result[1].annotation == SlideAnnotation.SILENT
    assert result[2].narration_raw == "All three"


def test_parse_slide_single_say_no_expansion() -> None:
    """Single say returns single-element list (backward compat)."""
    text = "# Slide\n\n- Regular bullet\n\n<!-- say: Just one say. -->"
    result = _parse_slide(1, text, Path("test.md"))
    assert len(result) == 1
    assert result[0].narration_raw == "Just one say."
    assert result[0].index == 1


def test_sequential_indices_across_slides(tmp_path: Path) -> None:
    """Indices are sequential across regular and expanded slides."""
    source = tmp_path / "test.md"
    source.write_text(
        textwrap.dedent("""\
        ---
        marp: true
        ---

        # Regular Slide

        <!-- say: First. -->

        ---

        # Fragment Slide

        * A
        <!-- say: A narration. -->
        * B
        <!-- say: B narration. -->

        ---

        # Another Regular

        <!-- say: Third. -->
    """)
    )
    parser = MarpParser()
    slides = parser.parse(source, Path("/tmp/build"))
    assert len(slides) == 4  # 1 + 2 (expanded) + 1
    assert slides[0].index == 1
    assert slides[1].index == 2
    assert slides[2].index == 3
    assert slides[3].index == 4


def test_skip_overrides_multiple_says() -> None:
    """Skip annotation takes priority over multiple says."""
    text = "<!-- skip -->\n<!-- say: First -->\n<!-- say: Second -->"
    result = _parse_slide(1, text, Path("test.md"))
    assert len(result) == 1
    assert result[0].annotation == SlideAnnotation.SKIP


def test_parse_slide_voice_pace_in_multi_say() -> None:
    """Voice and pace from says are preserved in multi-say expansion."""
    text = "<!-- say(voice=alice): First -->\n<!-- say(voice=bob, pace=slow): Second -->"
    result = _parse_slide(1, text, Path("test.md"))
    assert len(result) == 2
    assert result[0].voice == "alice"
    assert result[0].pace is None
    assert result[1].voice == "bob"
    assert result[1].pace == "slow"


# ---- Mocked tests for extract_images ----


class TestExtractImages:
    """Tests for extract_images() (Playwright-based)."""

    @patch("slidesonnet.parsers.marp._screenshot_presentation")
    @patch("slidesonnet.parsers.marp.subprocess.run")
    def test_html_export_command(
        self, mock_run: MagicMock, mock_screenshot: MagicMock, tmp_path: Path
    ) -> None:
        """Marp is called with --output *.html (not --images png)."""
        source = tmp_path / "slides.md"
        source.write_text("---\nmarp: true\n---\n# Hi\n\n<!-- say: Hello. -->")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        html_path = output_dir / "_slides_presentation.html"

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            html_path.write_text("<html></html>")
            return MagicMock()

        mock_run.side_effect = run_side_effect
        mock_screenshot.return_value = [output_dir / "slides.001.png"]

        result = extract_images(source, output_dir)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "marp"
        assert "--output" in cmd
        output_idx = cmd.index("--output")
        assert cmd[output_idx + 1].endswith(".html")
        assert "--images" not in cmd
        assert result == [output_dir / "slides.001.png"]

    @patch("slidesonnet.parsers.marp._screenshot_presentation")
    @patch("slidesonnet.parsers.marp.subprocess.run")
    def test_screenshot_called_with_html_path(
        self, mock_run: MagicMock, mock_screenshot: MagicMock, tmp_path: Path
    ) -> None:
        """_screenshot_presentation receives the HTML path and output dir."""
        source = tmp_path / "slides.md"
        source.write_text("dummy")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        html_path = output_dir / "_slides_presentation.html"

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            html_path.write_text("<html></html>")
            return MagicMock()

        mock_run.side_effect = run_side_effect
        mock_screenshot.return_value = []

        extract_images(source, output_dir)

        mock_screenshot.assert_called_once_with(html_path, output_dir, "slides")

    @patch("slidesonnet.parsers.marp._screenshot_presentation")
    @patch("slidesonnet.parsers.marp.subprocess.run")
    def test_html_cleanup(
        self, mock_run: MagicMock, mock_screenshot: MagicMock, tmp_path: Path
    ) -> None:
        """Temp HTML file is deleted after extraction."""
        source = tmp_path / "slides.md"
        source.write_text("dummy")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        html_path = output_dir / "_slides_presentation.html"

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            html_path.write_text("<html></html>")
            return MagicMock()

        mock_run.side_effect = run_side_effect
        mock_screenshot.return_value = []

        extract_images(source, output_dir)

        assert not html_path.exists()

    @patch("slidesonnet.parsers.marp._screenshot_presentation")
    @patch("slidesonnet.parsers.marp.subprocess.run")
    def test_html_cleanup_on_error(
        self, mock_run: MagicMock, mock_screenshot: MagicMock, tmp_path: Path
    ) -> None:
        """Temp HTML file is cleaned up even when screenshot fails."""
        source = tmp_path / "slides.md"
        source.write_text("dummy")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        html_path = output_dir / "_slides_presentation.html"

        def run_side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
            html_path.write_text("<html></html>")
            return MagicMock()

        mock_run.side_effect = run_side_effect
        mock_screenshot.side_effect = RuntimeError("browser crash")

        with pytest.raises(RuntimeError, match="browser crash"):
            extract_images(source, output_dir)

        assert not html_path.exists()

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


class TestEnsureChromium:
    """Tests for the auto-install logic."""

    @patch("slidesonnet.parsers.marp.subprocess.run")
    def test_installs_chromium_on_launch_failure(self, mock_run: MagicMock) -> None:
        """When Chromium launch fails, playwright install chromium is called."""
        from slidesonnet.parsers.marp import _ensure_chromium

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch.side_effect = Exception("not installed")

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_pw_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)

        mock_sync_pw = MagicMock(return_value=mock_cm)

        with patch("slidesonnet.parsers.marp._import_sync_playwright", return_value=mock_sync_pw):
            _ensure_chromium()

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["playwright", "install", "--with-deps", "chromium"]

    def test_skips_install_when_chromium_present(self) -> None:
        """When Chromium launches successfully, no install is triggered."""
        from slidesonnet.parsers.marp import _ensure_chromium

        mock_browser = MagicMock()
        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_pw_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)

        mock_sync_pw = MagicMock(return_value=mock_cm)

        with (
            patch("slidesonnet.parsers.marp._import_sync_playwright", return_value=mock_sync_pw),
            patch("slidesonnet.parsers.marp.subprocess.run") as mock_run,
        ):
            _ensure_chromium()

        mock_run.assert_not_called()
        mock_browser.close.assert_called_once()
