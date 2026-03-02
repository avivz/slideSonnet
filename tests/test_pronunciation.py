"""Tests for pronunciation loading and substitution."""

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
