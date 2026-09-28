"""Preview artifacts and the transition schedule a browser player follows.

(The morph-schedule tests moved here from test_gui.py with the functions.)
"""

from __future__ import annotations

import os
from pathlib import Path

from slidesonnet.api import SpeechSpan
from slidesonnet.audio.track import Cue
from slidesonnet.narration.model import Deck, PageNarration, Transition
from slidesonnet.server.previews import (
    PreviewArtifact,
    _publish,
    morph_schedule,
    preview_manifest,
    previews_dir,
    prune_previews,
    single_slide_morph,
)

IMAGES = [Path("a.png"), Path("b.png"), Path("c.png")]


def _deck(narration: dict[str, PageNarration]) -> Deck:
    return Deck(
        pdf_path=Path("d.pdf"), sidecar_path=Path("d.narration"), pages=["a", "b", "c"],
        narration=narration,
    )  # fmt: skip


def test_morph_schedule_plays_animated_boundaries_clamped_to_the_span() -> None:
    deck = _deck(
        {
            "a": PageNarration(slide_id="a", transition_out=Transition("wipeleft", 0.5)),
            "b": PageNarration(slide_id="b", transition_out=Transition("fade", 3.0)),
        }
    )
    cues = [Cue(0.0, "a"), Cue(4.0, "b"), Cue(5.0, "c")]
    wipe, fade = morph_schedule(cues, deck, IMAGES, lambda p: f"/u/{p.name}")
    # each morph *completes* at the destination's cue start, like the export
    assert wipe == {"at": 4.0, "dur": 0.5, "kind": "wipeleft", "from": "/u/a.png",
                    "to": "/u/b.png"}  # fmt: skip
    assert fade["at"] == 5.0 and fade["dur"] == 1.0  # clamped to b's 1s span
    assert morph_schedule(cues, _deck({}), IMAGES, str) == []  # plain cuts: nothing


def test_single_slide_morph_in_out_black_ends_and_toggle() -> None:
    block = PageNarration(slide_id="b", transition_out=Transition("wipeleft", 0.5))
    url = lambda p: p.name
    intro, outro = single_slide_morph(block, Transition("fade", 0.5), 1, IMAGES, 6.0, url)
    assert (intro["kind"], intro["at"], intro["from"], intro["to"]) == (
        "fade",
        0.5,
        "a.png",
        "b.png",
    )
    assert (outro["kind"], outro["at"], outro["from"], outro["to"]) == (
        "wipeleft",
        6.0,
        "b.png",
        "c.png",
    )
    # the deck's first slide morphs against black (no previous slide)
    (first,) = single_slide_morph(
        PageNarration("a"), Transition("fadeblack", 0.5), 0, IMAGES, 4.0, url
    )
    assert first["from"] is None and first["to"] == "a.png"
    # the "Play transitions in single-slide preview" toggle (off by default) gates it all
    assert (
        single_slide_morph(block, Transition("fade", 0.5), 1, IMAGES, 6.0, url, enabled=False) == []
    )


def test_published_tracks_are_immutable_and_pruned_oldest_first(tmp_path: Path) -> None:
    """B4: a rebuilt track.wav never rewrites an earlier preview's file."""
    track = tmp_path / "track.wav"
    dest = tmp_path / "previews"
    track.write_bytes(b"first")
    first_id, first = _publish(track, dest)
    track.write_bytes(b"second")  # the assembler rewrites in place
    second_id, second = _publish(track, dest)
    assert first_id != second_id and first.read_bytes() == b"first"
    assert _publish(track, dest) == (second_id, second)  # same content, same artifact

    pdf = tmp_path / "deck.pdf"
    folder = previews_dir(pdf)
    folder.mkdir(parents=True)
    for n in range(5):
        f = folder / f"{n}.wav"
        f.write_bytes(b"x")
        os.utime(f, (n, n))
    keep = folder / "0.wav"  # the oldest, but protected (it's playing)
    assert prune_previews(pdf, keep=2, protect=keep) == 2
    assert sorted(p.name for p in folder.iterdir()) == ["0.wav", "3.wav", "4.wav"]


def test_manifest_starts_a_deck_preview_at_the_current_slide() -> None:
    art = PreviewArtifact(
        id="abc", path=Path("abc.wav"), duration=9.0,
        cues=[Cue(0.0, "a"), Cue(4.0, "b"), Cue(7.0, "c")], slide_id=None,
        narration_revision="n1", pdf_revision="p1", engine="kokoro",
        speech=[SpeechSpan("b", 0, 4.3, 6.1)], silences=[[(5.5, 6.1)]],
    )  # fmt: skip
    m = preview_manifest(
        art, _deck({}), IMAGES, media_url=lambda p: f"/u/{p.name}", track_url="/t/abc.wav",
        start_slide="b",
    ).to_json()  # fmt: skip
    assert m["start_at"] == 4.0 and m["media_url"] == "/t/abc.wav"
    assert m["cues"][1] == {"start": 4.0, "slide_id": "b"}
    assert m["speech"] == [
        {"slide_id": "b", "index": 0, "start": 4.3, "end": 6.1, "silences": [[5.5, 6.1]]}
    ]
    assert m["pages"][2] == {"slide_id": "c", "image_url": "/u/c.png"}
    # a page not rendered yet keeps every later page on its own image
    gap = preview_manifest(
        art, _deck({}), [IMAGES[0], None, IMAGES[2]], media_url=lambda p: p.name, track_url="t"
    ).to_json()
    assert [pg["image_url"] for pg in gap["pages"]] == ["a.png", None, "c.png"]


def test_silences_inside_an_utterance_are_found_in_the_track(tmp_path: Path) -> None:
    """Clips carry their own silences (a comma's breath, ~0.5 s of tail on Inworld):
    the word-follower may only advance while the voice actually speaks."""
    import math
    import struct
    import wave

    from slidesonnet.server.voicing import silences_in

    rate = 16000
    samples = [
        int(8000 * math.sin(2 * math.pi * 220 * i / rate)) if i < rate or i >= 1.5 * rate else 0
        for i in range(2 * rate)
    ]  # speech 0-1 s, silence 1-1.5 s, speech 1.5-2 s
    track = tmp_path / "t.wav"
    with wave.open(str(track), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    (gaps,) = silences_in(track, [SpeechSpan("a", 0, 0.0, 2.0)])
    ((start, end),) = gaps
    assert abs(start - 1.0) < 0.03 and abs(end - 1.5) < 0.03
