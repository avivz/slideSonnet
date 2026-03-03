"""Tests for pronunciation loading and substitution."""

import re

import pytest

from slidesonnet.tts.pronunciation import (
    apply_pronunciation,
    load_pronunciation_dict,
    load_pronunciation_file,
    load_pronunciation_files,
)


def test_load_pronunciation_file(pronunciation_cs):
    entries = load_pronunciation_file(pronunciation_cs)
    assert entries["Dijkstra"] == "DYKE-struh"
    assert entries["Euler"] == "OY-ler"
    assert entries["Knuth"] == "kuh-NOOTH"
    assert entries["adjacency"] == "uh-JAY-suhn-see"
    assert entries["isomorphism"] == "eye-so-MOR-fizm"


def test_missing_file_raises_error(tmp_path):
    from slidesonnet.exceptions import ConfigError

    with pytest.raises(ConfigError, match="not found"):
        load_pronunciation_file(tmp_path / "nonexistent.md")


def test_empty_file_returns_empty(tmp_path):
    f = tmp_path / "empty.md"
    f.write_text("# Empty\n\nNo entries here.\n")
    entries = load_pronunciation_file(f)
    assert entries == {}


def test_merge_files(tmp_path):
    f1 = tmp_path / "a.md"
    f1.write_text("**alpha**: AL-fuh\n")
    f2 = tmp_path / "b.md"
    f2.write_text("**beta**: BAY-tuh\n")

    merged = load_pronunciation_files([f1, f2])
    assert merged["alpha"] == "AL-fuh"
    assert merged["beta"] == "BAY-tuh"


def test_apply_word_boundary():
    d = {"Euler": "OY-ler"}
    assert apply_pronunciation("Euler proved this.", d) == "OY-ler proved this."


def test_no_substring_replacement():
    d = {"Euler": "OY-ler"}
    result = apply_pronunciation("Eulerian path", d)
    # "Eulerian" should NOT be affected — only whole-word "Euler"
    assert "Eulerian" in result


def test_case_insensitive():
    d = {"euler": "OY-ler"}
    assert "OY-ler" in apply_pronunciation("Euler said hello.", d)
    assert "OY-ler" in apply_pronunciation("EULER said hello.", d)


def test_multiple_replacements():
    d = {"Euler": "OY-ler", "Dijkstra": "DYKE-struh"}
    result = apply_pronunciation("Euler and Dijkstra worked on graphs.", d)
    assert "OY-ler" in result
    assert "DYKE-struh" in result


def test_no_double_substitution():
    """If replacement A produces text matching word B, it should not be substituted again."""
    d = {"foo": "bar", "bar": "baz"}
    result = apply_pronunciation("foo is here", d)
    # "foo" -> "bar", but "bar" should NOT then become "baz"
    assert result == "bar is here"


def test_empty_dictionary():
    text = "No changes here."
    assert apply_pronunciation(text, {}) == text


def test_load_pronunciation_dict(tmp_path):
    shared = tmp_path / "shared.md"
    shared.write_text("**Euler**: OY-ler\n")
    piper = tmp_path / "piper.md"
    piper.write_text("**Euler**: OY-lur\n**Knuth**: kuh-NOOTH\n")

    result = load_pronunciation_dict(
        {
            "shared": [shared],
            "piper": [piper],
        }
    )
    assert result["shared"] == {"Euler": "OY-ler"}
    assert result["piper"] == {"Euler": "OY-lur", "Knuth": "kuh-NOOTH"}


def test_load_pronunciation_dict_empty():
    result = load_pronunciation_dict({})
    assert result == {}


class TestHebrewPronunciation:
    """Tests for Hebrew text in pronunciation substitution.

    Hebrew letters (Unicode category Lo) are part of \\w, so \\b word
    boundaries work for plain Hebrew words. However, niqqud (vowel points,
    category Mn — combining marks) are NOT \\w, which causes \\b boundaries
    to fragment niqqud-bearing words.
    """

    def test_plain_hebrew_replacement(self) -> None:
        """Basic Hebrew word replaced in a Hebrew sentence."""
        d = {"שלום": "shalom"}
        result = apply_pronunciation("אמרתי שלום לכולם", d)
        assert result == "אמרתי shalom לכולם"

    def test_niqqud_in_text_plain_key(self) -> None:
        """Known limitation: plain key won't match niqqud-bearing text.

        The dictionary key שלום (plain) does not match שָׁלוֹם (with niqqud)
        in the text because the codepoint sequences differ. The niqqud
        combining marks also break \\b boundaries inside the word.
        """
        d = {"שלום": "shalom"}
        text = "אמרתי שָׁלוֹם לכולם"
        result = apply_pronunciation(text, d)
        # No replacement occurs — the plain key cannot match niqqud text
        assert result == text

    def test_niqqud_in_key_plain_text(self) -> None:
        """Known limitation: niqqud key won't match plain text.

        The inverse of the previous test: a niqqud-bearing dictionary key
        does not match plain text because the codepoint sequences differ.
        """
        d = {"שָׁלוֹם": "shalom"}
        text = "אמרתי שלום לכולם"
        result = apply_pronunciation(text, d)
        # No replacement occurs — the niqqud key cannot match plain text
        assert result == text

    def test_niqqud_fragments_word_boundaries(self) -> None:
        r"""Explanatory test: \\w+ splits niqqud text into fragments.

        Hebrew niqqud (combining marks, category Mn) are not \\w characters.
        This means re.findall(r'\\w+', ...) fragments a niqqud-bearing word
        into multiple pieces — which is the root cause of the matching
        failures documented in the niqqud tests above.
        """
        plain = "שלום"
        niqqud = "שָׁלוֹם"  # shin-qamats-shin_dot-lamed-holam-vav-mem

        # Plain Hebrew: \w+ captures the whole word as one token
        plain_tokens = re.findall(r"\w+", plain)
        assert plain_tokens == ["שלום"]

        # Niqqud Hebrew: \w+ fragments it because combining marks aren't \w
        niqqud_tokens = re.findall(r"\w+", niqqud)
        assert len(niqqud_tokens) > 1  # fragmented — not a single token
