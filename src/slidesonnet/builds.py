"""A deck's two builds, and which one each job reads.

A deck compiles two ways (see ``is_plain_build`` / ``is_final_build``): a *plain*
build hides the page counter and progress bar, so inserting a slide doesn't make
every later page look changed; a *final* build shows them, for the video and for
handing out. They can live side by side:

* ``X.pdf`` — the deck's own PDF (the final build, when both exist): the one that
  is published, exported to video, and committed.
* ``X.plain.pdf`` — the *working build*, written by every ordinary compile.

Both are deck ``X``: one ``X.narration``, one ``X.review`` and review base. The
editor and review read the working build (the plain one when it exists), so an
agent may keep passing ``X.pdf``. Export reads whatever it is given, and refuses a
plain build. Page renders stay per file: the two builds' pictures differ.
"""

from __future__ import annotations

from pathlib import Path

#: The working build's name: ``<deck>.plain.pdf`` beside ``<deck>.pdf``.
PLAIN_SUFFIX = ".plain.pdf"


def deck_pdf(pdf_path: Path) -> Path:
    """The deck's own PDF (``X.pdf``) for either of its builds."""
    name = pdf_path.name
    if name.lower().endswith(PLAIN_SUFFIX):
        return pdf_path.with_name(name[: -len(PLAIN_SUFFIX)] + ".pdf")
    return pdf_path


def plain_pdf(pdf_path: Path) -> Path:
    """Where the deck's plain (working) build lives: ``X.plain.pdf``."""
    deck = deck_pdf(pdf_path)
    return deck.with_name(deck.stem + PLAIN_SUFFIX)


def working_pdf(pdf_path: Path) -> Path:
    """The build the editor and review work on: the plain one if it exists, else the deck's."""
    plain = plain_pdf(pdf_path)
    return plain if plain.is_file() else deck_pdf(pdf_path)
