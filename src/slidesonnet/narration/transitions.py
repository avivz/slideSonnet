"""Slide-transition taxonomy: the curated xfade gallery.

A transition is stored as a single flat name (``wipeleft``) on the model and in
the sidecar — the same shape as the legacy ``cut``/``crossfade``. The editor,
however, presents it as a short *family* picker (Wipe) plus an optional
*direction* (Left), so an author scans ~8 families instead of ~50 raw xfade
names. This module is the one place that knows:

* the full set of valid stored names (:data:`TRANSITION_NAMES`),
* the family ↔ name decomposition the picker uses
  (:func:`decompose` / :func:`compose`), and
* how a stored name maps to FFmpeg's xfade ``transition=`` value
  (:func:`xfade_name`).

``cut`` is the default (no transition). ``crossfade`` is a legacy alias kept so
older decks round-trip byte-identically; it renders, and decomposes in the
picker, as a plain *Fade*.
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

    @property
    def directional(self) -> bool:
        return bool(self.options)

    @property
    def name(self) -> str:
        """Stored name for a non-directional family (its key)."""
        return self.key


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
    Family("dissolve", "Dissolve"),
    Family("wipe", "Wipe", _lrud("wipe")),
    Family("slide", "Slide", _lrud("slide")),
    Family("cover", "Cover", _lrud("cover")),
    Family("reveal", "Reveal", _lrud("reveal")),
    Family("circle", "Circle", (("Open", "circleopen"), ("Close", "circleclose"))),
)

_FAMILY_BY_KEY: dict[str, Family] = {f.key: f for f in FAMILIES}

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


def is_valid(name: str) -> bool:
    return name in TRANSITION_NAMES


def xfade_name(kind: str) -> str | None:
    """The FFmpeg xfade ``transition=`` value for a stored *kind*.

    ``None`` for ``cut`` (a hard cut, no xfade). ``crossfade`` resolves to its
    alias target (``fade``); every other gallery name passes straight through —
    they are already valid xfade transition names.
    """
    if kind == "cut":
        return None
    return _ALIASES.get(kind, kind)


def _label_for(family: Family, name: str) -> str | None:
    for label, opt_name in family.options:
        if opt_name == name:
            return label
    return None


def decompose(kind: str) -> tuple[str, str | None]:
    """Split a stored *kind* into ``(family_key, direction_label)`` for the picker.

    Non-directional families (and the ``crossfade`` alias, shown as Fade) return
    a ``None`` direction. Raises ``KeyError`` for an unknown name — callers
    validate first via :data:`TRANSITION_NAMES`.
    """
    resolved = _ALIASES.get(kind, kind)
    for fam in FAMILIES:
        if not fam.options:
            if fam.key == resolved:
                return fam.key, None
        else:
            label = _label_for(fam, resolved)
            if label is not None:
                return fam.key, label
    raise KeyError(kind)


def compose(family_key: str, direction_label: str | None) -> str:
    """Build a stored name from a picker selection.

    For a non-directional family the *direction_label* is ignored. For a
    directional family a missing or unrecognized label falls back to the first
    option, so the picker always yields a valid name.
    """
    fam = _FAMILY_BY_KEY[family_key]
    if not fam.options:
        return fam.key
    if direction_label is not None:
        for label, name in fam.options:
            if label == direction_label:
                return name
    return fam.options[0][1]


def family_labels() -> list[str]:
    """Display labels for the Type dropdown, in picker order."""
    return [f.label for f in FAMILIES]


def directions_for(family_key: str) -> list[str]:
    """Direction labels for a family's Direction dropdown (empty if none)."""
    fam = _FAMILY_BY_KEY[family_key]
    return [label for label, _name in fam.options]
