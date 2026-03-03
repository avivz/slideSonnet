"""Tests for annotation stripping and visual hashing in MARP and Beamer parsers."""

from slidesonnet.parsers.marp import (
    strip_annotations as marp_strip,
    visual_hash as marp_hash,
)
from slidesonnet.parsers.beamer import (
    strip_annotations as beamer_strip,
    visual_hash as beamer_hash,
)


# ---- MARP strip_annotations ----


def test_marp_strip_say() -> None:
    text = "# Title\n<!-- say: Hello world. -->\nContent"
    assert "say" not in marp_strip(text)
    assert "# Title" in marp_strip(text)
    assert "Content" in marp_strip(text)


def test_marp_strip_say_with_params() -> None:
    text = "<!-- say(voice=alice, pace=slow): Welcome. -->"
    assert marp_strip(text).strip() == ""


def test_marp_strip_multiline_say() -> None:
    text = "<!-- say: This is\na multiline\nnarration. -->"
    assert marp_strip(text).strip() == ""


def test_marp_strip_nonarration() -> None:
    text = "# Slide\n<!-- nonarration -->\nMore content"
    assert "nonarration" not in marp_strip(text)
    assert "# Slide" in marp_strip(text)


def test_marp_strip_nonarration_with_duration() -> None:
    text = "<!-- nonarration(3.5) -->"
    assert marp_strip(text).strip() == ""


def test_marp_strip_skip() -> None:
    text = "# Hidden\n<!-- skip -->"
    assert "skip" not in marp_strip(text)
    assert "# Hidden" in marp_strip(text)


def test_marp_preserves_regular_html_comments() -> None:
    text = "<!-- This is a regular comment -->\n# Title"
    result = marp_strip(text)
    assert "<!-- This is a regular comment -->" in result


def test_marp_preserves_slide_content() -> None:
    text = "# Title\n\n- Bullet one\n- Bullet two\n\n<!-- say: Narration. -->"
    result = marp_strip(text)
    assert "# Title" in result
    assert "- Bullet one" in result
    assert "- Bullet two" in result


# ---- MARP visual_hash ----


def test_marp_visual_hash_same_for_annotation_only_diffs() -> None:
    base = "---\nmarp: true\n---\n# Title\n<!-- say: Original. -->"
    modified = "---\nmarp: true\n---\n# Title\n<!-- say: Completely different text. -->"
    assert marp_hash(base) == marp_hash(modified)


def test_marp_visual_hash_different_for_content_diffs() -> None:
    v1 = "---\nmarp: true\n---\n# Title A\n<!-- say: Hello. -->"
    v2 = "---\nmarp: true\n---\n# Title B\n<!-- say: Hello. -->"
    assert marp_hash(v1) != marp_hash(v2)


# ---- Beamer strip_annotations ----


def test_beamer_strip_say() -> None:
    text = r"\begin{frame}" + "\n" + r"\say{Hello world.}" + "\n" + r"\end{frame}"
    result = beamer_strip(text)
    assert r"\say" not in result
    assert r"\begin{frame}" in result


def test_beamer_strip_say_with_params() -> None:
    text = r"\say[voice=alice]{Welcome.}"
    assert beamer_strip(text).strip() == ""


def test_beamer_strip_say_with_nested_braces() -> None:
    text = r"\say{This has \textbf{bold} text.}"
    assert beamer_strip(text).strip() == ""


def test_beamer_strip_nonarration() -> None:
    text = "\\nonarration\n"
    assert "nonarration" not in beamer_strip(text)


def test_beamer_strip_nonarration_with_duration() -> None:
    text = "\\nonarration[2.5]\n"
    assert "nonarration" not in beamer_strip(text)


def test_beamer_strip_skip() -> None:
    text = r"\slidesonnetskip"
    assert "slidesonnetskip" not in beamer_strip(text)


def test_beamer_preserves_frame_content() -> None:
    text = (
        "\\begin{frame}\n"
        "\\frametitle{My Title}\n"
        "\\begin{itemize}\n"
        "\\item First\n"
        "\\end{itemize}\n"
        "\\say{Narration here.}\n"
        "\\end{frame}"
    )
    result = beamer_strip(text)
    assert r"\frametitle{My Title}" in result
    assert r"\item First" in result
    assert r"\say" not in result


# ---- Beamer visual_hash ----


def test_beamer_visual_hash_same_for_annotation_only_diffs() -> None:
    base = r"\begin{frame}\frametitle{Title}\say{Original.}\end{frame}"
    modified = r"\begin{frame}\frametitle{Title}\say{Different text.}\end{frame}"
    assert beamer_hash(base) == beamer_hash(modified)


def test_beamer_visual_hash_different_for_content_diffs() -> None:
    v1 = r"\begin{frame}\frametitle{Title A}\say{Hello.}\end{frame}"
    v2 = r"\begin{frame}\frametitle{Title B}\say{Hello.}\end{frame}"
    assert beamer_hash(v1) != beamer_hash(v2)
