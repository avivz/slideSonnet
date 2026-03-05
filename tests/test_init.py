"""Tests for the init command."""

import pytest

from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.init import init_project


def test_md_creates_structure(tmp_path):
    target = tmp_path / "myproject"
    init_project(target, "md")

    assert (target / "slidesonnet.yaml").exists()
    assert (target / ".gitignore").exists()
    assert (target / ".env").exists()
    assert (target / "pronunciation" / "cs-terms.md").exists()
    assert (target / "01-intro" / "slides.md").exists()
    assert (target / "02-definitions" / "slides.md").exists()


def test_tex_creates_structure(tmp_path):
    target = tmp_path / "myproject"
    init_project(target, "tex")

    assert (target / "slidesonnet.yaml").exists()
    assert (target / ".gitignore").exists()
    assert (target / ".env").exists()
    assert (target / "pronunciation" / "cs-terms.md").exists()
    assert (target / "01-intro" / "slides.tex").exists()
    assert (target / "02-definitions" / "slides.tex").exists()


def test_playlist_name(tmp_path):
    """Playlist is named slidesonnet.yaml, not lecture.yaml."""
    target = tmp_path / "myproject"
    init_project(target, "md")

    assert (target / "slidesonnet.yaml").exists()
    assert not (target / "lecture.yaml").exists()


def test_md_slides_have_say(tmp_path):
    target = tmp_path / "myproject"
    init_project(target, "md")

    intro = (target / "01-intro" / "slides.md").read_text()
    defs = (target / "02-definitions" / "slides.md").read_text()
    assert "<!-- say:" in intro
    assert "<!-- say:" in defs


def test_tex_slides_have_say(tmp_path):
    target = tmp_path / "myproject"
    init_project(target, "tex")

    intro = (target / "01-intro" / "slides.tex").read_text()
    defs = (target / "02-definitions" / "slides.tex").read_text()
    assert "\\say{" in intro
    assert "\\say{" in defs


def test_pronunciation_has_entries(tmp_path):
    target = tmp_path / "myproject"
    init_project(target, "md")

    pron = (target / "pronunciation" / "cs-terms.md").read_text()
    assert "**Dijkstra**" in pron
    assert "DYKE-struh" in pron


def test_gitignore_protects_env(tmp_path):
    target = tmp_path / "myproject"
    init_project(target, "md")

    gitignore = (target / ".gitignore").read_text()
    assert ".env" in gitignore
    assert "cache/" in gitignore


def test_env_has_placeholder(tmp_path):
    target = tmp_path / "myproject"
    init_project(target, "md")

    env = (target / ".env").read_text()
    assert "your_api_key_here" in env


def test_tex_playlist_references_tex_modules(tmp_path):
    target = tmp_path / "myproject"
    init_project(target, "tex")

    playlist = (target / "slidesonnet.yaml").read_text()
    assert "slides.tex" in playlist
    assert "slides.md" not in playlist


def test_md_playlist_references_md_modules(tmp_path):
    target = tmp_path / "myproject"
    init_project(target, "md")

    playlist = (target / "slidesonnet.yaml").read_text()
    assert "slides.md" in playlist


# ---- Overwrite safety tests ----


def test_refuses_existing_playlist(tmp_path):
    """init_project refuses if slidesonnet.yaml already exists."""
    target = tmp_path / "myproject"
    target.mkdir()
    (target / "slidesonnet.yaml").write_text("existing")

    with pytest.raises(SlideSonnetError, match="Refusing to overwrite"):
        init_project(target, "md")


def test_refuses_existing_slides(tmp_path):
    """init_project refuses if a nested file already exists."""
    target = tmp_path / "myproject"
    slides_dir = target / "01-intro"
    slides_dir.mkdir(parents=True)
    (slides_dir / "slides.md").write_text("existing")

    with pytest.raises(SlideSonnetError, match="Refusing to overwrite"):
        init_project(target, "md")


def test_refuses_existing_gitignore(tmp_path):
    """init_project refuses if .gitignore already exists."""
    target = tmp_path / "myproject"
    target.mkdir()
    (target / ".gitignore").write_text("existing")

    with pytest.raises(SlideSonnetError, match="Refusing to overwrite"):
        init_project(target, "md")


def test_error_lists_conflicting_files(tmp_path):
    """Error message includes the paths of conflicting files."""
    target = tmp_path / "myproject"
    target.mkdir()
    (target / "slidesonnet.yaml").write_text("existing")
    (target / ".env").write_text("existing")

    with pytest.raises(SlideSonnetError, match="slidesonnet.yaml"):
        init_project(target, "md")
