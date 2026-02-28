"""Tests for Beamer parser."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slidesonnet.exceptions import ParserError
from slidesonnet.models import SlideAnnotation
from slidesonnet.parsers.beamer import (
    BeamerParser,
    _count_pauses,
    _extract_braced,
    _extract_frames,
    _find_say_commands,
    _parse_frame,
    _parse_say_params,
    _strip_latex,
    compile_pdf,
    extract_images,
    extract_images_from_pdf,
)


@pytest.fixture
def simple_tex():
    return Path(__file__).parent / "fixtures" / "simple.tex"


def test_extract_frames(simple_tex):
    text = simple_tex.read_text()
    frames = _extract_frames(text)
    assert len(frames) == 11


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


def test_parse_unannotated(simple_tex, caplog):
    parser = BeamerParser()
    slides = parser.parse(simple_tex, Path("/tmp/build"))

    # Frame 6 (index 5) is unannotated
    assert slides[5].annotation == SlideAnnotation.NONE
    assert "no annotation" in caplog.text


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


def test_strip_latex_nested():
    """Nested markup like \\textbf{This has \\emph{nested} markup} should be fully stripped."""
    result = _strip_latex(r"\textbf{This has \emph{nested} markup}")
    assert "This has" in result
    assert "nested" in result
    assert "markup" in result
    assert "\\" not in result
    assert "{" not in result


def test_strip_latex_deeply_nested():
    """Deeply nested: \\textbf{a \\emph{b \\underline{c} d} e}."""
    result = _strip_latex(r"\textbf{a \emph{b \underline{c} d} e}")
    assert "a" in result
    assert "b" in result
    assert "c" in result
    assert "d" in result
    assert "e" in result
    assert "\\" not in result
    assert "{" not in result


def test_empty_say_warns(caplog):
    slides, _ = _parse_frame(1, r"\say{}", Path("test.tex"), 1)
    assert len(slides) == 1
    assert slides[0].annotation == SlideAnnotation.SILENT
    assert "did you mean" in caplog.text


# ---- Mocked tests for extract_images and edge cases ----


class TestExtractImages:
    """Mocked tests for extract_images()."""

    @patch("slidesonnet.parsers.beamer.subprocess.run")
    def test_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text(r"\documentclass{beamer}")
        output_dir = tmp_path / "out"

        # After pdflatex + pdftoppm, create fake PNGs
        def side_effect(cmd, **kwargs):
            if cmd[0] == "pdftoppm":
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "slide-1.png").touch()
                (output_dir / "slide-2.png").touch()
            return MagicMock()

        mock_run.side_effect = side_effect

        result = extract_images(source, output_dir)

        assert mock_run.call_count == 2
        # First call: pdflatex
        assert mock_run.call_args_list[0][0][0][0] == "pdflatex"
        # Second call: pdftoppm
        assert mock_run.call_args_list[1][0][0][0] == "pdftoppm"
        assert len(result) == 2

    @patch(
        "slidesonnet.parsers.beamer.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_pdflatex_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text("dummy")
        with pytest.raises(ParserError):
            extract_images(source, tmp_path / "out")

    @patch(
        "slidesonnet.parsers.beamer.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "pdflatex", stderr="latex error log"),
    )
    def test_pdflatex_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text("dummy")
        with pytest.raises(ParserError, match="latex error log"):
            extract_images(source, tmp_path / "out")

    @patch("slidesonnet.parsers.beamer.subprocess.run")
    def test_pdflatex_error_with_pdf_warns(
        self, mock_run: MagicMock, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When pdflatex fails but a PDF was produced, warn with stderr."""
        source = tmp_path / "slides.tex"
        source.write_text("dummy")
        output_dir = tmp_path / "out"

        def side_effect(cmd, **kwargs):
            if cmd[0] == "pdflatex":
                # Create a partial PDF before raising
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / f"{source.stem}.pdf").touch()
                raise subprocess.CalledProcessError(1, "pdflatex", stderr="Overfull hbox")
            if cmd[0] == "pdftoppm":
                (output_dir / "slide-1.png").touch()
            return MagicMock()

        mock_run.side_effect = side_effect

        result = extract_images(source, output_dir)

        assert len(result) == 1
        assert "WARNING" in caplog.text
        assert "Overfull hbox" in caplog.text

    @patch("slidesonnet.parsers.beamer.subprocess.run")
    def test_pdftoppm_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text("dummy")

        def side_effect(cmd, **kwargs):
            if cmd[0] == "pdftoppm":
                raise FileNotFoundError
            return MagicMock()

        mock_run.side_effect = side_effect

        with pytest.raises(ParserError):
            extract_images(source, tmp_path / "out")

    @patch("slidesonnet.parsers.beamer.subprocess.run")
    def test_pdftoppm_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text("dummy")

        def side_effect(cmd, **kwargs):
            if cmd[0] == "pdftoppm":
                raise subprocess.CalledProcessError(1, "pdftoppm", stderr="convert failed")
            return MagicMock()

        mock_run.side_effect = side_effect

        with pytest.raises(ParserError):
            extract_images(source, tmp_path / "out")


class TestCompilePdf:
    """Mocked tests for compile_pdf()."""

    @patch("slidesonnet.parsers.beamer.subprocess.run")
    def test_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text(r"\documentclass{beamer}")
        output_dir = tmp_path / "out"

        result = compile_pdf(source, output_dir)

        assert result == output_dir / "slides.pdf"
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][0] == "pdflatex"

    @patch(
        "slidesonnet.parsers.beamer.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_pdflatex_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text("dummy")
        with pytest.raises(ParserError, match="pdflatex"):
            compile_pdf(source, tmp_path / "out")

    @patch(
        "slidesonnet.parsers.beamer.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "pdflatex", stderr="latex error"),
    )
    def test_pdflatex_error_no_pdf(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text("dummy")
        with pytest.raises(ParserError, match="latex error"):
            compile_pdf(source, tmp_path / "out")

    @patch("slidesonnet.parsers.beamer.subprocess.run")
    def test_pdflatex_error_with_pdf_warns(
        self, mock_run: MagicMock, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        source = tmp_path / "slides.tex"
        source.write_text("dummy")
        output_dir = tmp_path / "out"

        def side_effect(cmd, **kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "slides.pdf").touch()
            raise subprocess.CalledProcessError(1, "pdflatex", stderr="Overfull hbox")

        mock_run.side_effect = side_effect

        result = compile_pdf(source, output_dir)

        assert result == output_dir / "slides.pdf"
        assert "Overfull hbox" in caplog.text

    @patch("slidesonnet.parsers.beamer.subprocess.run")
    def test_creates_output_dir(self, mock_run: MagicMock, tmp_path: Path) -> None:
        source = tmp_path / "slides.tex"
        source.write_text("dummy")
        output_dir = tmp_path / "deep" / "nested" / "out"

        compile_pdf(source, output_dir)

        assert output_dir.exists()


class TestExtractImagesFromPdf:
    """Mocked tests for extract_images_from_pdf()."""

    @patch("slidesonnet.parsers.beamer.subprocess.run")
    def test_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        pdf_path = tmp_path / "slides.pdf"
        pdf_path.touch()
        output_dir = tmp_path / "out"

        def side_effect(cmd, **kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "slide-1.png").touch()
            (output_dir / "slide-2.png").touch()
            return MagicMock()

        mock_run.side_effect = side_effect

        result = extract_images_from_pdf(pdf_path, output_dir)

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][0] == "pdftoppm"
        assert len(result) == 2

    @patch(
        "slidesonnet.parsers.beamer.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_pdftoppm_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        pdf_path = tmp_path / "slides.pdf"
        pdf_path.touch()
        with pytest.raises(ParserError, match="pdftoppm"):
            extract_images_from_pdf(pdf_path, tmp_path / "out")

    @patch(
        "slidesonnet.parsers.beamer.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "pdftoppm", stderr="convert failed"),
    )
    def test_pdftoppm_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        pdf_path = tmp_path / "slides.pdf"
        pdf_path.touch()
        with pytest.raises(ParserError, match="convert failed"):
            extract_images_from_pdf(pdf_path, tmp_path / "out")

    @patch("slidesonnet.parsers.beamer.subprocess.run")
    def test_creates_output_dir(self, mock_run: MagicMock, tmp_path: Path) -> None:
        pdf_path = tmp_path / "slides.pdf"
        pdf_path.touch()
        output_dir = tmp_path / "deep" / "nested" / "out"

        extract_images_from_pdf(pdf_path, output_dir)

        assert output_dir.exists()


class TestExtractBracedEdgeCases:
    """Edge case tests for _extract_braced()."""

    def test_start_not_at_brace(self) -> None:
        content, pos = _extract_braced("hello", 0)
        assert content is None
        assert pos == 0

    def test_unmatched_braces(self) -> None:
        content, pos = _extract_braced("{unclosed", 0)
        assert content is None
        assert pos == 0

    def test_start_past_end(self) -> None:
        content, pos = _extract_braced("abc", 5)
        assert content is None
        assert pos == 5

    def test_empty_braces(self) -> None:
        content, pos = _extract_braced("{}", 0)
        assert content == ""
        assert pos == 2

    def test_escaped_braces_symmetric(self) -> None:
        """Escaped \\{ and \\} in matching pairs should not affect depth."""
        text = r"{The set \{1, 2\} is finite}"
        content, pos = _extract_braced(text, 0)
        assert content == r"The set \{1, 2\} is finite"
        assert pos == len(text)

    def test_escaped_brace_asymmetric(self) -> None:
        """A lone escaped brace should not unbalance the counter."""
        text = r"{Open bracket: \{}"
        content, pos = _extract_braced(text, 0)
        assert content == r"Open bracket: \{"
        assert pos == len(text)


# ---- Tests for overlay / sub-slide parsing ----


class TestParseSayParams:
    """Tests for _parse_say_params()."""

    def test_empty_params(self) -> None:
        sub, voice, pace = _parse_say_params("")
        assert sub == 1
        assert voice is None
        assert pace is None

    def test_bare_number(self) -> None:
        sub, voice, pace = _parse_say_params("2")
        assert sub == 2
        assert voice is None
        assert pace is None

    def test_explicit_slide_key(self) -> None:
        sub, voice, pace = _parse_say_params("slide=2")
        assert sub == 2

    def test_bare_number_with_voice(self) -> None:
        sub, voice, pace = _parse_say_params("2, voice=alice")
        assert sub == 2
        assert voice == "alice"
        assert pace is None

    def test_slide_key_with_pace(self) -> None:
        sub, voice, pace = _parse_say_params("slide=3, pace=slow")
        assert sub == 3
        assert pace == "slow"

    def test_voice_only(self) -> None:
        sub, voice, pace = _parse_say_params("voice=bob")
        assert sub == 1
        assert voice == "bob"

    def test_voice_and_pace(self) -> None:
        sub, voice, pace = _parse_say_params("voice=alice, pace=slow")
        assert sub == 1
        assert voice == "alice"
        assert pace == "slow"


class TestCountPauses:
    """Tests for _count_pauses()."""

    def test_no_pauses(self) -> None:
        assert _count_pauses(r"\say{Hello}") == 0

    def test_one_pause(self) -> None:
        assert _count_pauses(r"First \pause Second") == 1

    def test_multiple_pauses(self) -> None:
        assert _count_pauses(r"A \pause B \pause C") == 2


class TestOverlayParsing:
    """Tests for per-slide narration in overlay frames."""

    def test_pause_with_per_slide_say(self) -> None:
        """Frame with \\pause and \\say targeting each sub-slide."""
        text = r"""
        First point.
        \say{First sub-slide narration.}
        \pause
        Second point.
        \say[2]{Second sub-slide narration.}
        """
        slides, n_vis = _parse_frame(1, text, Path("test.tex"), 1)
        assert len(slides) == 2
        assert n_vis == 2  # 1 pause → 2 PDF pages
        assert slides[0].index == 1
        assert slides[0].image_index == 1
        assert slides[0].annotation == SlideAnnotation.SAY
        assert "First sub-slide" in slides[0].narration_raw
        assert slides[1].index == 2
        assert slides[1].image_index == 2
        assert slides[1].annotation == SlideAnnotation.SAY
        assert "Second sub-slide" in slides[1].narration_raw

    def test_bare_number_syntax(self) -> None:
        """\\say[2]{text} bare number targets sub-slide 2."""
        text = r"""
        \say{First.}
        \pause
        \say[2]{Second.}
        """
        slides, _ = _parse_frame(1, text, Path("test.tex"), 1)
        assert len(slides) == 2
        assert slides[1].narration_raw == "Second."

    def test_explicit_slide_key_syntax(self) -> None:
        """\\say[slide=2]{text} explicit key targets sub-slide 2."""
        text = r"""
        \say{First.}
        \pause
        \say[slide=2]{Second.}
        """
        slides, _ = _parse_frame(1, text, Path("test.tex"), 1)
        assert len(slides) == 2
        assert slides[1].narration_raw == "Second."

    def test_combined_syntax_with_voice(self) -> None:
        """\\say[2, voice=alice]{text} targets sub-slide 2 with voice."""
        text = r"""
        \say{Intro.}
        \pause
        \say[2, voice=alice]{Alice speaks.}
        """
        slides, _ = _parse_frame(1, text, Path("test.tex"), 1)
        assert len(slides) == 2
        assert slides[1].voice == "alice"
        assert slides[1].narration_raw == "Alice speaks."

    def test_missing_sub_slide_narration_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """Sub-slide with no \\say → SILENT + warning."""
        text = r"""
        \say{Only first sub-slide.}
        \pause
        Nothing for second.
        """
        slides, _ = _parse_frame(1, text, Path("test.tex"), 1)
        assert len(slides) == 2
        assert slides[0].annotation == SlideAnnotation.SAY
        assert slides[1].annotation == SlideAnnotation.SILENT
        assert "no narration" in caplog.text

    def test_say_target_beyond_pause_count_extends(self, caplog: pytest.LogCaptureFixture) -> None:
        """\\say targeting beyond \\pause count extends sub-slide count + warns."""
        text = r"""
        \say{First.}
        \say[3]{Third.}
        """
        # No \pause → n_sub would be 1, but \say[3] extends to 3
        slides, n_vis = _parse_frame(1, text, Path("test.tex"), 1)
        assert len(slides) == 3
        assert n_vis == 1  # actual PDF pages: 0 pauses → 1 page
        assert slides[0].annotation == SlideAnnotation.SAY
        assert slides[1].annotation == SlideAnnotation.SILENT
        assert slides[2].annotation == SlideAnnotation.SAY
        # Extended sub-slides clamp to last available image
        assert slides[2].image_index == 1
        assert "extending" in caplog.text

    def test_backward_compat_no_pause_multiple_say_concatenate(self) -> None:
        """Without \\pause, multiple \\say still concatenate on sub-slide 1."""
        text = r"""
        \say{First sentence.}
        \say{Second sentence.}
        """
        slides, _ = _parse_frame(1, text, Path("test.tex"), 1)
        assert len(slides) == 1
        assert slides[0].annotation == SlideAnnotation.SAY
        assert "First sentence." in slides[0].narration_raw
        assert "Second sentence." in slides[0].narration_raw

    def test_skip_on_overlay_frame(self) -> None:
        """\\skip on a frame with \\pause → all sub-slides are SKIP."""
        text = r"""
        \skip
        \pause
        Content.
        """
        slides, _ = _parse_frame(1, text, Path("test.tex"), 1)
        assert len(slides) == 2
        assert all(s.annotation == SlideAnnotation.SKIP for s in slides)

    def test_silent_on_overlay_frame(self) -> None:
        """\\silent (without \\say) on a frame with \\pause → all sub-slides SILENT."""
        text = r"""
        \silent
        \pause
        Content.
        """
        slides, _ = _parse_frame(1, text, Path("test.tex"), 1)
        assert len(slides) == 2
        assert all(s.annotation == SlideAnnotation.SILENT for s in slides)

    def test_sequential_indices_across_frames(self) -> None:
        """Indices are sequential across frames, including overlay frames."""
        parser = BeamerParser()
        # Build a small document: frame1 (1 sub), frame2 (2 subs), frame3 (1 sub)
        tex = r"""
        \begin{frame}
          \say{Frame one.}
        \end{frame}
        \begin{frame}
          \say{Frame two, slide one.}
          \pause
          \say[2]{Frame two, slide two.}
        \end{frame}
        \begin{frame}
          \say{Frame three.}
        \end{frame}
        """
        from unittest.mock import patch

        tmp = Path("/tmp/test_seq.tex")
        with patch.object(Path, "read_text", return_value=tex):
            slides = parser.parse(tmp, Path("/tmp/build"))

        assert len(slides) == 4
        assert [s.index for s in slides] == [1, 2, 3, 4]

    def test_three_pauses_three_say(self) -> None:
        """Frame with two \\pause producing three sub-slides, all narrated."""
        text = r"""
        \say{First.}
        \pause
        \say[2]{Second.}
        \pause
        \say[slide=3]{Third.}
        """
        slides, _ = _parse_frame(1, text, Path("test.tex"), 1)
        assert len(slides) == 3
        assert all(s.annotation == SlideAnnotation.SAY for s in slides)
        assert slides[0].narration_raw == "First."
        assert slides[1].narration_raw == "Second."
        assert slides[2].narration_raw == "Third."

    def test_fixture_overlay_frame(self, simple_tex: Path) -> None:
        """Test the overlay frame from simple.tex fixture (frame 7)."""
        parser = BeamerParser()
        slides = parser.parse(simple_tex, Path("/tmp/build"))

        # Frames 1-6: original frames (6 narrations, one each)
        # Frame 7: "Overlay Frame" with 2 pauses → 3 sub-slides (indices 7, 8, 9)
        assert slides[6].annotation == SlideAnnotation.SAY
        assert "first sub-slide" in slides[6].narration_raw
        assert slides[6].index == 7

        assert slides[7].annotation == SlideAnnotation.SAY
        assert "second sub-slide" in slides[7].narration_raw
        assert slides[7].index == 8

        assert slides[8].annotation == SlideAnnotation.SAY
        assert "third sub-slide" in slides[8].narration_raw
        assert slides[8].index == 9

    def test_fixture_overlay_with_voice(self, simple_tex: Path) -> None:
        """Frame 8: overlay with voice=alice on sub-slide 2."""
        parser = BeamerParser()
        slides = parser.parse(simple_tex, Path("/tmp/build"))

        # Frame 8: "Overlay Bare Number with Voice" → indices 10, 11
        assert slides[9].annotation == SlideAnnotation.SAY
        assert "Introduction to overlays" in slides[9].narration_raw
        assert slides[9].index == 10

        assert slides[10].annotation == SlideAnnotation.SAY
        assert slides[10].voice == "alice"
        assert slides[10].index == 11

    def test_fixture_overlay_silent_sub_slide(
        self, simple_tex: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Frame 9: only sub-slide 1 narrated, sub-slide 2 silent."""
        parser = BeamerParser()
        slides = parser.parse(simple_tex, Path("/tmp/build"))

        # Frame 9: "Overlay Silent Sub-slide" → indices 12, 13
        assert slides[11].annotation == SlideAnnotation.SAY
        assert slides[11].index == 12
        assert slides[12].annotation == SlideAnnotation.SILENT
        assert slides[12].index == 13

    def test_fixture_overlay_skip(self, simple_tex: Path) -> None:
        """Frame 10: \\skip with \\pause → both sub-slides are SKIP."""
        parser = BeamerParser()
        slides = parser.parse(simple_tex, Path("/tmp/build"))

        # Frame 10: "Overlay Skip" → indices 14, 15
        assert slides[13].annotation == SlideAnnotation.SKIP
        assert slides[13].index == 14
        assert slides[14].annotation == SlideAnnotation.SKIP
        assert slides[14].index == 15

    def test_fixture_overlay_silent(self, simple_tex: Path) -> None:
        """Frame 11: \\silent with \\pause → both sub-slides are SILENT."""
        parser = BeamerParser()
        slides = parser.parse(simple_tex, Path("/tmp/build"))

        # Frame 11: "Overlay Silent" → indices 16, 17
        assert slides[15].annotation == SlideAnnotation.SILENT
        assert slides[15].index == 16
        assert slides[16].annotation == SlideAnnotation.SILENT
        assert slides[16].index == 17
