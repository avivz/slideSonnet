"""Preview artifacts: immutable per-slide tracks and the manifest a browser player follows."""

from __future__ import annotations

import os
from pathlib import Path

from slidesonnet.api import SpeechSpan
from slidesonnet.server.previews import (
    PreviewArtifact,
    _publish,
    preview_manifest,
    previews_dir,
    prune_previews,
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


def test_manifest_names_the_slide_its_track_and_where_each_line_plays() -> None:
    art = PreviewArtifact(
        id="abc", path=Path("abc.wav"), duration=4.0, slide_id="b",
        narration_revision="n1", pdf_revision="p1", engine="kokoro",
        speech=[SpeechSpan("b", 0, 0.3, 2.1)], silences=[[(1.5, 2.1)]],
    )  # fmt: skip
    m = preview_manifest(art, track_url="/t/abc.wav").to_json()
    assert m == {
        "artifact_id": "abc", "slide_id": "b", "narration_revision": "n1", "pdf_revision": "p1",
        "engine": "kokoro", "media_url": "/t/abc.wav", "duration": 4.0,
        "speech": [{"slide_id": "b", "index": 0, "start": 0.3, "end": 2.1, "silences": [[1.5, 2.1]]}],
    }  # fmt: skip


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
