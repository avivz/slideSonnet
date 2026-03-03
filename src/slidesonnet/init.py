"""Project scaffolding for `slidesonnet init`."""

from __future__ import annotations

import importlib.resources
import shutil
from pathlib import Path

import yaml

_TEMPLATES = importlib.resources.files("slidesonnet.templates")


def _load_template(name: str) -> str:
    """Read a template file from the templates package."""
    return (_TEMPLATES / name).read_text(encoding="utf-8")


def init_blank(target_dir: Path) -> None:
    """Create a blank project scaffold with documented config."""
    target_dir.mkdir(parents=True, exist_ok=True)

    _write(target_dir / "lecture01.yaml", _load_template("blank_playlist.yaml"))
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

    # Read source playlist as YAML (filter // comments)
    text = source_playlist.read_text(encoding="utf-8")
    lines = [ln for ln in text.split("\n") if not ln.lstrip().startswith("//")]
    config_dict = yaml.safe_load("\n".join(lines)) or {}
    if isinstance(config_dict, dict):
        config_dict.pop("modules", None)
    else:
        config_dict = {}

    # Create playlist with copied config but starter module list
    config_dict["modules"] = ["01-intro/slides.md"]
    yaml_text = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
    _write(target_dir / "lecture01.yaml", yaml_text)

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

    _write(target_dir / "lecture01.yaml", _load_template("example_playlist.yaml"))
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
