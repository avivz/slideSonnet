"""Project scaffolding for `slidesonnet init`."""

from __future__ import annotations

import importlib.resources
import shutil
from pathlib import Path

import yaml

from slidesonnet.playlist import split_front_matter

_TEMPLATES = importlib.resources.files("slidesonnet.templates")


def _load_template(name: str) -> str:
    """Read a template file from the templates package."""
    return (_TEMPLATES / name).read_text(encoding="utf-8")


def init_blank(target_dir: Path) -> None:
    """Create a blank project scaffold with documented config."""
    target_dir.mkdir(parents=True, exist_ok=True)

    _write(target_dir / "lecture01.md", _load_template("blank_playlist.md"))
    _write(target_dir / ".gitignore", _load_template("gitignore.txt"))
    _write(target_dir / ".env", _load_template("env.txt"))

    pron_dir = target_dir / "pronunciation"
    pron_dir.mkdir(exist_ok=True)
    _write(pron_dir / "terms.md", _load_template("blank_pronunciation.md"))

    slides_dir = target_dir / "01-intro"
    slides_dir.mkdir(exist_ok=True)
    _write(slides_dir / "slides.md", _load_template("blank_slides.md"))


def init_from(target_dir: Path, source_playlist: Path) -> None:
    """Copy config from an existing project."""
    target_dir.mkdir(parents=True, exist_ok=True)

    # Read and copy front matter
    text = source_playlist.read_text(encoding="utf-8")
    config_dict, _ = split_front_matter(text)

    # Create playlist with copied config but empty module list
    yaml_text = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
    playlist_content = (
        f"---\n{yaml_text}---\n\n# My Presentation\n\n1. [Introduction](01-intro/slides.md)\n"
    )
    _write(target_dir / "lecture01.md", playlist_content)

    # Copy pronunciation files
    source_dir = source_playlist.parent
    pron_raw = config_dict.get("pronunciation", [])
    if isinstance(pron_raw, list):
        pron_all_paths = list(pron_raw)
    elif isinstance(pron_raw, dict):
        pron_all_paths = [p for paths in pron_raw.values() for p in paths]
    else:
        pron_all_paths = []
    for pron_rel in pron_all_paths:
        src = source_dir / pron_rel
        dst = target_dir / pron_rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # Create .env with blanked values
    source_env = source_dir / ".env"
    if source_env.exists():
        blanked = []
        for line in source_env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key = line.split("=", 1)[0]
                blanked.append(f"{key}=your_value_here")
            else:
                blanked.append(line)
        _write(target_dir / ".env", "\n".join(blanked) + "\n")
    else:
        _write(target_dir / ".env", _load_template("env.txt"))

    _write(target_dir / ".gitignore", _load_template("gitignore.txt"))

    # Create starter slides
    slides_dir = target_dir / "01-intro"
    slides_dir.mkdir(exist_ok=True)
    _write(slides_dir / "slides.md", _load_template("blank_slides.md"))


def init_example(target_dir: Path) -> None:
    """Create a full working example project."""
    target_dir.mkdir(parents=True, exist_ok=True)

    _write(target_dir / "lecture01.md", _load_template("example_playlist.md"))
    _write(target_dir / ".gitignore", _load_template("gitignore.txt"))
    _write(target_dir / ".env", _load_template("env.txt"))

    pron_dir = target_dir / "pronunciation"
    pron_dir.mkdir(exist_ok=True)
    _write(pron_dir / "cs-terms.md", _load_template("example_pronunciation.md"))

    intro_dir = target_dir / "01-intro"
    intro_dir.mkdir(exist_ok=True)
    _write(intro_dir / "slides.md", _load_template("example_slides_intro.md"))

    defs_dir = target_dir / "02-definitions"
    defs_dir.mkdir(exist_ok=True)
    _write(defs_dir / "slides.md", _load_template("example_slides_defs.md"))


def _write(path: Path, content: str) -> None:
    """Write file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
