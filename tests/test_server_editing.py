"""The editing rules, on real files: boundaries, orphans, voices, statuses, bookkeeping.

(Ported from test_gui_state.py when the NiceGUI editor state was retired: the
rules live in ``server.editing`` and ``server.decks`` now, addressed by slide
id; the same assertions, fewer tests.)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from slidesonnet.narration.model import Deck, Segment, Transition
from slidesonnet.server import editing
from slidesonnet.server.decks import deck_service
from slidesonnet.server.library import DeckEntry, DeckRegistry
from slidesonnet.server.snapshots import deck_snapshot
from tests.conftest import prep_marked_deck, simple_narration, write_pdf

HAND_EDITED = """\
# lecture notes — keep the pacing relaxed

@a
  utterance:
    text: Hello from slide a,
      wrapped by hand.

# slide b is the punchline
@b
  utterance:
    text: Bye.
"""


def _deck(tmp_path: Path, ids: list[str], sidecar: str = "", *, raw: bool = False) -> Path:
    pdf = write_pdf(tmp_path / "deck.pdf", ids)
    if sidecar:
        text = sidecar if raw else simple_narration(sidecar)
        (tmp_path / "deck.narration").write_text(text, encoding="utf-8")
    return pdf


def _edit(pdf: Path, mutate: Callable[[Deck], bool]) -> tuple[bool, Deck]:
    svc = deck_service(pdf)
    result = svc.edit(svc.narration_revision(), mutate)
    return result.changed, svc.load().deck


def _sidecar(pdf: Path) -> str:
    return pdf.with_suffix(".narration").read_text(encoding="utf-8")


# ---- one boundary, two faces ---------------------------------------------------------
def test_boundary_transitions_are_stored_once(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b", "c"], "@a\nHi.\n\n@b\nBye.\n")

    def set_in(slide: str, tr: Transition) -> Callable[[Deck], bool]:
        return lambda d: editing.apply_block_edit(
            d, slide, list(d.page_narration(slide).segments),
            transition_in=tr, transition_out=d.page_narration(slide).transition_out,
        )  # fmt: skip

    # editing b's "in" edits the boundary — stored on a's "out"; b stays a cut
    changed, deck = _edit(pdf, set_in("b", Transition("fade", 0.7)))
    assert changed
    assert deck.page_narration("a").transition_out == Transition("fade", 0.7)
    assert deck.page_narration("b").transition_in == Transition()
    assert editing.incoming_transition(deck, "b") == Transition("fade", 0.7)
    # re-saving with the same effective incoming value writes nothing
    before = _sidecar(pdf)
    assert _edit(pdf, set_in("b", Transition("fade", 0.7)))[0] is False
    assert _sidecar(pdf) == before
    # the deck's first slide has no previous: its "in" is its own (the deck open)
    changed, deck = _edit(pdf, set_in("a", Transition("fadeblack", 0.6)))
    assert deck.page_narration("a").transition_in == Transition("fadeblack", 0.6)


def test_a_non_cut_out_clears_the_next_slides_in(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"], "@a\nHi.\n\n@b\nBye.\n")
    deck = deck_service(pdf).load().deck
    deck.narration["b"] = deck.page_narration("b").with_content(
        list(deck.page_narration("b").segments), transition_in=Transition("crossfade", 0.4)
    )
    deck_service(pdf).write(deck, expected_revision=deck_service(pdf).narration_revision())
    _, deck = _edit(
        pdf,
        lambda d: editing.apply_block_edit(
            d, "a", [Segment.speech("Hi.")], transition_out=Transition("crossfade", 0.5)
        ),
    )
    assert deck.page_narration("a").transition_out == Transition("crossfade", 0.5)
    assert deck.page_narration("b").transition_in == Transition()  # normalized away


# ---- block edits ------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("segments", "expect_block"),
    [
        ([Segment.speech("One."), Segment.pause(1.5), Segment.speech("Two.")], True),
        ([], False),  # emptying a slide drops its block entirely
    ],
)
def test_replacing_a_block(tmp_path: Path, segments: list[Segment], expect_block: bool) -> None:
    pdf = _deck(tmp_path, ["a", "b"], "@a\nOld text.\n")
    changed, deck = _edit(pdf, lambda d: editing.apply_block_edit(d, "a", segments))
    assert changed
    assert ("a" in deck.narration) is expect_block
    if expect_block:
        assert deck.narration["a"].segments == segments
    assert ("Old text." in _sidecar(pdf)) is False


def test_edits_leave_hand_written_blocks_byte_stable(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"], HAND_EDITED, raw=True)
    same = deck_service(pdf).load().deck.page_narration("a")
    # an edit that changes nothing reports so, and leaves the file byte-identical
    assert _edit(pdf, lambda d: editing.apply_block_edit(d, "a", list(same.segments)))[0] is False
    assert _sidecar(pdf) == HAND_EDITED
    _edit(pdf, lambda d: editing.apply_block_edit(d, "b", [Segment.speech("Goodbye, rewritten.")]))
    text = _sidecar(pdf)
    assert "# lecture notes — keep the pacing relaxed\n" in text  # the header comment
    assert "    text: Hello from slide a,\n      wrapped by hand.\n" in text  # a untouched
    assert "# slide b is the punchline\n@b\n  utterance:\n    text: Goodbye, rewritten.\n" in text


def test_duplicate_blocks_are_disambiguated_and_both_kept(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"], "@a\nFirst.\n\n@a\nSecond.\n\n@b\nBye.\n")
    changed, deck = _edit(
        pdf, lambda d: editing.apply_block_edit(d, "b", [Segment.speech("edited b")])
    )
    assert changed and "a-2" in deck.narration
    assert all(t in _sidecar(pdf) for t in ("First.", "Second.", "edited b"))


def test_a_page_without_an_id_cannot_be_edited(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "", "b"], "@a\nHi.\n")
    deck = deck_service(pdf).load().deck
    with pytest.raises(editing.EditError):
        editing.apply_block_edit(deck, "", [Segment.speech("x")])
    with pytest.raises(editing.EditError):
        editing.append_orphan(deck, "a", "")


def test_block_differs_only_for_a_real_edit(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b"], "@a\nHi.\n")
    deck = deck_service(pdf).load().deck
    here = deck.page_narration("b")
    kw = {
        "transition_in": editing.incoming_transition(deck, "b"),
        "transition_out": here.transition_out,
    }
    assert not editing.block_differs(deck, "b", list(here.segments), **kw)
    assert editing.block_differs(deck, "b", [Segment.speech("new")], **kw)


# ---- unattached narration ----------------------------------------------------------------
def test_orphans_listed_attached_appended_and_deleted(tmp_path: Path) -> None:
    pdf = _deck(tmp_path, ["a", "b", "c"], "@a\nKept.\n\n@gone\nLost text.\n\n@old\nMore.\n")
    deck = deck_service(pdf).load().deck
    assert [b.slide_id for b in editing.orphan_blocks(deck)] == ["gone", "old"]
    assert editing.unnarrated_pages(deck) == ["b", "c"]
    with pytest.raises(editing.EditError):
        editing.attach_orphan(deck, "gone", "a")  # a already has narration
    _, deck = _edit(pdf, lambda d: editing.attach_orphan(d, "gone", "b") or True)
    assert deck.narration["b"].speech_text == "Lost text." and "gone" not in deck.narration
    _, deck = _edit(pdf, lambda d: editing.append_orphan(d, "old", "a") or True)
    assert deck.narration["a"].speech_text == "Kept. More."
    assert editing.orphan_blocks(deck) == []
    other = tmp_path / "other"
    other.mkdir()
    pdf2 = _deck(other, ["a"], "@a\nA.\n\n@z\nZ.\n")
    _, deck = _edit(pdf2, lambda d: editing.delete_orphan(d, "z") or True)
    assert "z" not in deck.narration and "Z." not in _sidecar(pdf2)


# ---- the voice layer (through the API command, as the editor sends it) ----------------------
VOICES = """\
# slidesonnet-format: 2
default-voice: guest
voices:
  guest:
    kokoro: af_bella

@intro-title
  utterance:
    voice: guest
    text: Hello.
"""


@pytest.fixture
def api(tmp_path: Path):
    from fastapi.testclient import TestClient

    from slidesonnet.server.app import create_api_app
    from slidesonnet.server.context import SESSION_HEADER

    pdf = prep_marked_deck(tmp_path)
    pdf.with_suffix(".narration").write_text(VOICES, encoding="utf-8")
    registry = DeckRegistry(tmp_path)
    registry.rescan()
    with TestClient(create_api_app(registry)) as c:
        c.headers[SESSION_HEADER] = c.get("/api/v1/session").json()["token"]
        c.token = c.get("/api/v1/library").json()["sections"][0]["decks"][0]["token"]  # type: ignore[attr-defined]
        c.pdf = pdf  # type: ignore[attr-defined]
        yield c


def _voices(c, **body: object) -> dict:  # type: ignore[no-untyped-def, type-arg]
    snap = c.get(f"/api/v1/decks/{c.token}").json()
    r = c.post(
        f"/api/v1/decks/{c.token}/commands",
        json={"type": "edit_voices", "expected_revision": snap["revisions"]["narration"], **body},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_voices_unchanged_rename_and_file_paths(api, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    before = _sidecar(api.pdf)
    assert (
        _voices(api, voices={"guest": {"kokoro": "af_bella"}}, default_voice="guest")["changed"]
        is False
    )
    assert _sidecar(api.pdf) == before  # re-applying the shown map is byte-stable
    # a rename follows every reference: utterances and the deck default
    _voices(
        api,
        voices={"host": {"kokoro": "af_bella"}},
        default_voice="host",
        renames={"guest": "host"},
    )
    text = _sidecar(api.pdf)
    assert "guest" not in text and "voice: host" in text and "default-voice: host" in text
    snap = api.get(f"/api/v1/decks/{api.token}").json()
    assert snap["voices"]["names"] == ["host"] and snap["voices"]["resolved"] == {
        "host": "af_bella"
    }
    # a Qwen3 voice file is stored relative (portable) and shown relative again
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "lecturer.pt").write_bytes(b"fake-clone")
    _voices(api, voices={"lecturer": {"qwen3": "prompts/lecturer.pt"}}, default_voice="lecturer")
    assert "qwen3: prompts/lecturer.pt" in _sidecar(api.pdf)
    snap = api.get(f"/api/v1/decks/{api.token}").json()
    assert snap["voices"]["map"]["lecturer"] == {"qwen3": "prompts/lecturer.pt"}
    assert _voices(api, voices={"lecturer": {"qwen3": "prompts/lecturer.pt"}},
                   default_voice="lecturer")["changed"] is False  # fmt: skip


def test_a_voice_unmapped_for_the_engine_is_flagged_per_engine(api) -> None:  # type: ignore[no-untyped-def]
    kokoro = api.get(f"/api/v1/decks/{api.token}").json()
    qwen = api.get(f"/api/v1/decks/{api.token}?engine=qwen3").json()
    assert not any(d["code"] == "voice-unmapped" for d in kokoro["diagnostics"])
    assert any(d["code"] == "voice-unmapped" for d in qwen["diagnostics"])
    assert qwen["voices"]["resolved"] == {"guest": None}


# ---- statuses --------------------------------------------------------------------------------
def test_slide_status_per_page(tmp_path: Path) -> None:
    pdf = prep_marked_deck(tmp_path, "@intro-title\nHello.\n\n@nowhere\nOrphaned.\n")
    registry = DeckRegistry(tmp_path)
    registry.rescan()
    entry: DeckEntry = registry.entries()[0]
    pages = {p.slide_id: p.status for p in deck_snapshot(entry).pages}
    assert pages["intro-title"] == "ready"
    assert any(sid.startswith("auto-") and s == "warning" for sid, s in pages.items())
    assert "empty" in pages.values()  # pages without narration
    orphan = [d for d in deck_snapshot(entry).diagnostics if d.code == "orphan-narration"]
    assert [(d.slide_id, d.severity) for d in orphan] == [("nowhere", "error")]
    assert pdf.exists()


# ---- bookkeeping after a save ---------------------------------------------------------------
def test_saves_are_noted_in_review_and_prune_local_audio(tmp_path: Path) -> None:
    from slidesonnet.cache import audio_dir
    from slidesonnet.hashing import audio_filename
    from slidesonnet.review import ops

    pdf = prep_marked_deck(tmp_path, "@intro-title\nOriginal narration line.\n")
    ad = audio_dir(pdf)
    ad.mkdir(parents=True, exist_ok=True)
    stale = audio_filename("Original narration line.", "kokoro", "kokoro:am_echo")
    paid = audio_filename("Original narration line.", "inworld", "inworld:v")
    (ad / stale).write_bytes(b"a")
    (ad / paid).write_bytes(b"b")

    # outside review: a save writes nothing but the narration
    _edit(pdf, lambda d: editing.apply_block_edit(d, "intro-title", [Segment.speech("Take one.")]))
    assert not ops.review_path(pdf).exists()
    deck_service(pdf).flush_prune()  # the sweep is debounced off the save path
    assert not (ad / stale).exists() and (ad / paid).exists()  # paid audio is never swept

    # under review: the author's own edit is filed, not flagged later as unrequested
    ops.start(pdf)
    _edit(pdf, lambda d: editing.apply_block_edit(d, "intro-title", [Segment.speech("Take two.")]))
    convs = ops.load(pdf).slide_conversations()
    assert [(c.origin, c.slides) for c in convs] == [("author-edits", ["intro-title"])]
