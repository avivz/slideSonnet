"""Project scaffolding for `slidesonnet init`."""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import Literal

from slidesonnet.exceptions import SlideSonnetError

_TEMPLATES = importlib.resources.files("slidesonnet.templates")


def _load_template(name: str) -> str:
    """Read a template file from the templates package."""
    return (_TEMPLATES / name).read_text(encoding="utf-8")


def _check_no_conflicts(paths: list[Path]) -> None:
    """Raise if any of *paths* already exist."""
    conflicts = [p for p in paths if p.exists()]
    if conflicts:
        listed = "\n  ".join(str(p) for p in conflicts)
        raise SlideSonnetError(f"Refusing to overwrite existing files:\n  {listed}")


def _write(path: Path, content: str) -> None:
    """Write file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def init_project(target_dir: Path, fmt: Literal["md", "tex"]) -> None:
    """Create a new slideSonnet project in *target_dir*.

    *fmt* selects MARP Markdown (``"md"``) or Beamer LaTeX (``"tex"``).
    """
    ext = fmt  # "md" or "tex"
    targets = [
        target_dir / "slidesonnet.yaml",
        target_dir / ".gitignore",
        target_dir / ".env",
        target_dir / "pronunciation" / "cs-terms.md",
        target_dir / "01-intro" / f"slides.{ext}",
        target_dir / "02-definitions" / f"slides.{ext}",
    ]
    _check_no_conflicts(targets)

    target_dir.mkdir(parents=True, exist_ok=True)

    playlist_template = "example_playlist_tex.yaml" if fmt == "tex" else "example_playlist.yaml"
    _write(target_dir / "slidesonnet.yaml", _load_template(playlist_template))
    _write(target_dir / ".gitignore", _load_template("gitignore.txt"))
    _write(target_dir / ".env", _load_template("env.txt"))

    pron_dir = target_dir / "pronunciation"
    pron_dir.mkdir(exist_ok=True)
    _write(pron_dir / "cs-terms.md", _load_template("example_pronunciation.md"))

    intro_template = f"example_slides_intro.{ext}"
    defs_template = f"example_slides_defs.{ext}"

    intro_dir = target_dir / "01-intro"
    intro_dir.mkdir(exist_ok=True)
    _write(intro_dir / f"slides.{ext}", _load_template(intro_template))

    defs_dir = target_dir / "02-definitions"
    defs_dir.mkdir(exist_ok=True)
    _write(defs_dir / f"slides.{ext}", _load_template(defs_template))
