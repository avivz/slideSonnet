"""Slide-transition taxonomy: the curated xfade gallery.

A transition is stored as a single flat name (``wipeleft``) on the model and in
the sidecar — the same shape as the legacy ``cut``/``crossfade``. The editor,
however, presents it as a short *family* picker (Wipe) plus an optional
*direction* (Left), so an author scans ~8 families instead of ~50 raw xfade
names. This module is the one place that knows:

* the full set of valid stored names (:data:`TRANSITION_NAMES`),
* the curated families the editor's picker shows (:data:`FAMILIES`, served
  by ``/meta``), and
* how a stored name maps to FFmpeg's xfade ``transition=`` value
  (:func:`xfade_name`).

``cut`` is the default (no transition). ``crossfade`` is a legacy alias kept so
older decks round-trip byte-identically; it renders, and shows in the picker,
as a plain *Fade*.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    """One entry in the picker's Type dropdown.

    ``options`` is a tuple of ``(direction_label, stored_name)`` pairs. An empty
    ``options`` marks a non-directional family whose stored name *is* its
    :attr:`key` (Cut / Fade / Dissolve); the picker hides the direction control
    for it.
    """

    key: str
    label: str
    options: tuple[tuple[str, str], ...] = ()


def _lrud(prefix: str) -> tuple[tuple[str, str], ...]:
    return (
        ("Left", f"{prefix}left"),
        ("Right", f"{prefix}right"),
        ("Up", f"{prefix}up"),
        ("Down", f"{prefix}down"),
    )


# The curated gallery, in picker order. Cut first (the default); then the two
# non-directional dissolve-likes; then the four directional families; then the
# circular iris.
FAMILIES: tuple[Family, ...] = (
    Family("cut", "Cut"),
    Family("fade", "Fade"),
    Family("fadeblack", "Fade through black"),
    Family("fadewhite", "Fade through white"),
    Family("dissolve", "Dissolve"),
    Family("wipe", "Wipe", _lrud("wipe")),
    Family("slide", "Slide", _lrud("slide")),
    Family("cover", "Cover", _lrud("cover")),
    Family("reveal", "Reveal", _lrud("reveal")),
    Family("circle", "Circle", (("Open", "circleopen"), ("Close", "circleclose"))),
)

# Legacy alias → the family it presents and renders as.
_ALIASES: dict[str, str] = {"crossfade": "fade"}


def _gallery_names() -> frozenset[str]:
    names: set[str] = set(_ALIASES)
    for fam in FAMILIES:
        if fam.options:
            names.update(name for _label, name in fam.options)
        else:
            names.add(fam.key)
    return frozenset(names)


#: Every valid stored transition name (incl. ``cut`` and the ``crossfade`` alias).
TRANSITION_NAMES: frozenset[str] = _gallery_names()


def xfade_name(kind: str) -> str | None:
    """The FFmpeg xfade ``transition=`` value for a stored *kind*.

    ``None`` for ``cut`` (a hard cut, no xfade). ``crossfade`` resolves to its
    alias target (``fade``); every other gallery name passes straight through —
    they are already valid xfade transition names.
    """
    if kind == "cut":
        return None
    return _ALIASES.get(kind, kind)
