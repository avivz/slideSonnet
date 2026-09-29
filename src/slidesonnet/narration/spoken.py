"""Inline pronunciation fixes: what the captions show vs. what an engine says.

A narration line may carry a fix for one word (or a few), written like a
markdown link — the display form in square brackets, the spoken form right
after it in parentheses::

    the work of [Mengoli](/menˈɡoːli/) in 1650      # IPA, between slashes
    [Leonhard Euler](/ˈleɪɒnhɑːrt/ /ˈɔɪlər/)        # one IPA pair per word
    ask [Dijkstra](DYKE-struh)                      # a respelling

The fix is stored verbatim on the ``text:`` line (the sidecar grammar is
untouched), and resolved here per reader:

* captions (SRT/VTT) and the editor's word marking: the display form;
* Inworld (``ipa=True``): the spoken form, IPA or respelling;
* Kokoro/Qwen3 (``ipa=False``): a respelling, else the display form — never IPA.

The ``(`` must follow the ``]`` immediately, so ``[pause 2]`` and ordinary
brackets are never read as a fix. A blank spoken form is no fix.

The global pronunciation dictionary (``pronunciation/*.md``) applies to the
words outside the fixes, the same way: a respelling reaches every engine, a
``/…/`` IPA value only Inworld (Kokoro/Qwen3 say the plain word). Inworld's
text is exactly what it always was, so no paid clip changes name.
"""

from __future__ import annotations

import re

from slidesonnet.tts.pronunciation import apply_pronunciation

#: ``[display](spoken)`` — no brackets/parens or line breaks inside either part.
FIX_RE = re.compile(r"\[(?P<display>[^\[\]\n]+)\]\((?P<spoken>[^()\n]+)\)")

#: Sound tags Inworld's newer voices perform (``[sigh]``): kept as written.
SOUND_TAGS = frozenset({"laugh", "sigh", "breathe", "cough", "clear_throat", "yawn"})
_BRACKETED_RE = re.compile(r"\[([^\[\]]*)\]")

# One or more slash-delimited IPA words, space-separated: ``/a/`` or ``/a/ /b/``.
_IPA_RE = re.compile(r"/[^/\s]+/(?:\s+/[^/\s]+/)*")


def is_ipa(form: str) -> bool:
    """True when *form* is written as IPA between slashes (``/kriːt/``)."""
    return _IPA_RE.fullmatch(form.strip()) is not None


def round_brackets(text: str) -> str:
    """Every ``[``/``]`` as ``(``/``)``, except around a sound tag like ``[sigh]``.

    Run it on text whose fixes are already resolved (see :func:`engine_text`).
    """
    out: list[str] = []
    pos = 0
    for m in _BRACKETED_RE.finditer(text):
        out.append(text[pos : m.start()].replace("[", "(").replace("]", ")"))
        inner = m.group(1)
        out.append(m.group(0) if inner.strip().lower() in SOUND_TAGS else f"({inner})")
        pos = m.end()
    out.append(text[pos:].replace("[", "(").replace("]", ")"))
    return "".join(out)


def has_stray_brackets(text: str) -> bool:
    """True when *text* has square brackets besides its fixes and sound tags."""
    shown = display_text(text)
    return round_brackets(shown) != shown


def display_text(text: str) -> str:
    """*text* as the captions show it: each fix replaced by its display form."""
    return FIX_RE.sub(lambda m: m.group("display"), text)


def engine_text(text: str, *, ipa: bool, dictionary: dict[str, str]) -> str:
    """*text* as an engine should receive it.

    *ipa* says whether the engine reads IPA (Inworld). Fixes resolve to their
    spoken form where the engine can say it, else to the display form — which
    the dictionary may still respell. The dictionary's IPA values, like IPA
    fixes, reach only an engine that reads IPA. For Inworld, text without fixes
    comes out exactly as ``apply_pronunciation`` gives it, so its paid clips
    keep their cache keys.
    """
    if not ipa:
        dictionary = {word: form for word, form in dictionary.items() if not is_ipa(form)}
    out: list[str] = []
    plain = ""  # the run the dictionary still applies to
    pos = 0
    for m in FIX_RE.finditer(text):
        spoken = m.group("spoken").strip()
        plain += text[pos : m.start()]
        if spoken and (ipa or not is_ipa(spoken)):
            out.append(apply_pronunciation(plain, dictionary))
            out.append(spoken)
            plain = ""
        else:
            plain += m.group("display")
        pos = m.end()
    plain += text[pos:]
    out.append(apply_pronunciation(plain, dictionary))
    return "".join(out)
