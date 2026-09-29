"""The ``/api/v1`` contract, exercised through FastAPI's test client (no browser, no NiceGUI).

What these pin: revision-checked writes (409, never a silent overwrite), the
session/origin/host guard on mutations, stable error bodies, paid-synthesis
approval, backend-owned jobs, immutable preview artifacts (B4), and ranged media.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slidesonnet.api import Preview
from slidesonnet.audio.track import Cue
from slidesonnet.exceptions import UnapprovedClips
from slidesonnet.server.app import create_api_app
from slidesonnet.server.context import SESSION_HEADER
from slidesonnet.server.library import DeckRegistry
from tests.conftest import _StubTTS, simple_narration, write_pdf

SIDECAR = "@intro\nHello there.\n@middle\nIn the middle.\n@gone\nFrom a dropped slide.\n"


@pytest.fixture
def deck(tmp_path: Path) -> Path:
    (tmp_path / "course" / "week1").mkdir(parents=True)
    pdf = write_pdf(tmp_path / "course" / "week1" / "talk.pdf", ["intro", "middle", "outro"])
    (pdf.parent / "talk.narration").write_text(simple_narration(SIDECAR), encoding="utf-8")
    return pdf


@pytest.fixture
def client(deck: Path) -> Iterator[TestClient]:
    registry = DeckRegistry(deck.parent.parent)
    registry.rescan()
    with TestClient(create_api_app(registry)) as c:
        c.headers[SESSION_HEADER] = c.get("/api/v1/session").json()["token"]
        yield c


def _token(client: TestClient) -> str:
    lib = client.get("/api/v1/library").json()
    return str(lib["sections"][0]["decks"][0]["token"])


def _snapshot(client: TestClient, token: str) -> dict[str, Any]:
    r = client.get(f"/api/v1/decks/{token}")
    assert r.status_code == 200, r.text
    return dict(r.json())


def _speech(text: str) -> dict[str, Any]:
    return {"kind": "speech", "text": text}


def _wait(client: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(500):
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return dict(job)
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


# ---- reading -------------------------------------------------------------------------
def test_library_and_snapshot_describe_the_deck_without_leaking_paths(
    client: TestClient, deck: Path
) -> None:
    lib = client.get("/api/v1/library").json()
    assert [s["title"] for s in lib["sections"]] == ["week1"]
    (entry,) = lib["sections"][0]["decks"]
    assert entry["name"] == "talk" and entry["url"] == f"/d/{entry['token']}"

    snap = _snapshot(client, entry["token"])
    assert [p["slide_id"] for p in snap["pages"]] == ["intro", "middle", "outro"]
    assert snap["orphans"] == ["gone"]  # narration whose slide the PDF no longer has
    assert "gone" in snap["narration"]  # …still addressable by id
    assert [p["status"] for p in snap["pages"]] == ["ready", "ready", "empty"]
    assert snap["revisions"]["narration"] not in ("", "absent")
    assert str(deck.parent) not in str(lib) + str(snap)  # no absolute paths on the wire


def test_deck_stats_count_what_is_left_to_narrate(client: TestClient) -> None:
    """The library card's numbers: slides in the PDF and how many have narration."""
    token = _token(client)
    stats = client.get(f"/api/v1/decks/{token}/stats").json()
    # the unattached "gone" block is an error; "outro" without narration a warning
    assert stats == {"token": token, "slides": 3, "narrated": 2, "errors": 1, "warnings": 1}


@pytest.mark.parametrize(
    ("method", "url", "status", "code"),
    [
        ("get", "/api/v1/decks/nope", 404, "unknown_deck"),
        ("get", "/api/v1/jobs/nope", 404, "unknown_job"),
        ("patch", "/api/v1/decks/{t}/slides/intro", 422, "invalid_input"),  # empty body
    ],
)
def test_errors_have_stable_codes(
    client: TestClient, method: str, url: str, status: int, code: str
) -> None:
    r = client.request(method, url.format(t=_token(client)), json={})
    assert r.status_code == status
    assert r.json()["error"]["code"] == code
    assert r.json()["error"]["message"]


# ---- writing ----------------------------------------------------------------------------
def test_edit_saves_atomically_and_moves_the_incoming_boundary(
    client: TestClient, deck: Path
) -> None:
    token = _token(client)
    rev = _snapshot(client, token)["revisions"]["narration"]
    body = {
        "expected_revision": rev,
        "segments": [_speech("Rewritten middle.")],
        "transition_in": {"kind": "fade", "seconds": 0.5},
    }
    r = client.patch(f"/api/v1/decks/{token}/slides/middle", json=body)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["changed"] is True and saved["revision"] != rev

    snap = _snapshot(client, token)
    assert snap["revisions"]["narration"] == saved["revision"]
    assert snap["narration"]["middle"]["segments"] == [
        {"kind": "speech", "text": "Rewritten middle.", "voice": None, "pace": None,
         "direction": None}
    ]  # fmt: skip
    # the boundary is stored once, on the earlier slide's out
    assert snap["narration"]["intro"]["transition_out"] == {"kind": "fade", "seconds": 0.5}
    assert snap["pages"][1]["incoming"] == {"kind": "fade", "seconds": 0.5}
    assert "Rewritten middle." in (deck.parent / "talk.narration").read_text(encoding="utf-8")

    # the same values again: nothing to write
    again = client.patch(
        f"/api/v1/decks/{token}/slides/middle",
        json={**body, "expected_revision": saved["revision"]},
    )
    assert again.json() == {"changed": False, "revision": saved["revision"]}


def test_stale_revision_is_a_conflict_and_the_outside_edit_survives(
    client: TestClient, deck: Path
) -> None:
    token = _token(client)
    stale = _snapshot(client, token)["revisions"]["narration"]
    sidecar = deck.parent / "talk.narration"
    sidecar.write_text(simple_narration("@intro\nAn agent's edit.\n"), encoding="utf-8")

    r = client.patch(
        f"/api/v1/decks/{token}/slides/intro",
        json={"expected_revision": stale, "segments": [_speech("Mine.")]},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "revision_conflict"
    assert "An agent's edit." in sidecar.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({SESSION_HEADER: "wrong"}, "bad_session"),
        ({"Origin": "https://evil.example"}, "cross_origin"),
        ({"Host": "evil.example"}, "bad_host"),
    ],
)
def test_mutations_need_same_origin_session_and_host(
    client: TestClient, headers: dict[str, str], code: str
) -> None:
    token = _token(client)
    rev = _snapshot(client, token)["revisions"]["narration"]
    r = client.patch(
        f"/api/v1/decks/{token}/slides/intro",
        json={"expected_revision": rev, "segments": [_speech("x")]},
        headers=headers,
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == code


@pytest.mark.parametrize(
    "edit",
    [
        {"segments": [{"kind": "pause", "seconds": -1}]},
        {"segments": [{"kind": "pause", "seconds": float("nan")}]},
        {"segments": [{"kind": "pause", "seconds": float("inf")}]},
        {"segments": [{"kind": "shout", "text": "x"}]},
        {"segments": [{"kind": "speech", "text": "x", "voice": "a\nvoice: b"}]},
        {"segments": [{"kind": "speech", "text": "x", "direction": "warm\r\npause: 3"}]},
        {"segments": [], "transition_in": {"kind": "fade", "seconds": float("inf")}},
        {"segments": [], "transition_out": {"kind": "fade", "seconds": float("nan")}},
    ],
)
def test_invalid_segments_are_rejected(client: TestClient, edit: dict[str, Any]) -> None:
    token = _token(client)
    rev = _snapshot(client, token)["revisions"]["narration"]
    r = client.patch(  # json.dumps writes NaN/Infinity, as a lax client could
        f"/api/v1/decks/{token}/slides/intro",
        content=json.dumps({"expected_revision": rev, **edit}),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"


@pytest.mark.parametrize(
    ("voices", "default_voice"),
    [
        ({"my voice": {"kokoro": "am_echo"}}, None),  # the preamble can't hold a space
        ({"2nd": {"kokoro": "am_echo"}}, None),
        ({"narrator": {"kokoro": "am_echo\nguest:"}}, None),
        ({"narrator": {"kokoro": "am_echo # warm"}}, None),  # would read back as a comment
        ({"narrator": {"kokoro": "  "}}, None),
        ({"narrator": {"kokoro": "am_echo"}}, "narrator\nvoices:"),
    ],
)
def test_voice_maps_the_sidecar_cannot_hold_are_rejected(
    client: TestClient, voices: dict[str, dict[str, str]], default_voice: str | None
) -> None:
    token = _token(client)
    rev = _snapshot(client, token)["revisions"]["narration"]
    r = client.post(
        f"/api/v1/decks/{token}/commands",
        json={"type": "edit_voices", "expected_revision": rev, "voices": voices,
              "default_voice": default_voice},
    )  # fmt: skip
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input", r.text


def test_commands_attach_orphans_and_rename_voices(client: TestClient) -> None:
    token = _token(client)
    rev = _snapshot(client, token)["revisions"]["narration"]
    r = client.post(
        f"/api/v1/decks/{token}/commands",
        json={"type": "attach_orphan", "expected_revision": rev, "orphan_id": "gone",
              "target_id": "outro"},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    snap = _snapshot(client, token)
    assert snap["orphans"] == [] and "outro" in snap["narration"]

    r = client.post(
        f"/api/v1/decks/{token}/commands",
        json={"type": "edit_voices", "expected_revision": r.json()["revision"],
              "voices": {"narrator": {"kokoro": "am_echo"}}, "default_voice": "narrator"},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    snap = _snapshot(client, token)
    assert snap["voices"]["default_voice"] == "narrator"
    assert snap["voices"]["map"] == {"narrator": {"kokoro": "am_echo"}}

    bad = client.post(
        f"/api/v1/decks/{token}/commands",
        json={"type": "attach_orphan", "expected_revision": snap["revisions"]["narration"],
              "orphan_id": "nope", "target_id": "outro"},
    )  # fmt: skip
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_edit"
    on_page = client.post(
        f"/api/v1/decks/{token}/commands",
        json={"type": "delete_orphan", "expected_revision": snap["revisions"]["narration"],
              "orphan_id": "outro"},
    )  # fmt: skip
    assert on_page.status_code == 422 and "isn't unattached" in on_page.json()["error"]["message"]


# ---- jobs ------------------------------------------------------------------------------
def test_generate_job_runs_in_the_background(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.audio import synth as synth_mod

    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: _StubTTS(cfg.backend))
    token = _token(client)
    assert _snapshot(client, token)["missing_audio"] == 2  # the unattached block has no page
    r = client.post(f"/api/v1/decks/{token}/jobs", json={"kind": "generate"})
    assert r.status_code == 202, r.text
    job = _wait(client, r.json()["id"])
    assert job["status"] == "succeeded" and job["result"] == {"generated": 2}
    assert _snapshot(client, token)["missing_audio"] == 0


def test_paid_generation_needs_explicit_approval(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []
    monkeypatch.setattr("slidesonnet.api.synthesize_deck", lambda *a, **k: calls.append(k) or 0)
    token = _token(client)
    r = client.post(f"/api/v1/decks/{token}/jobs", json={"kind": "generate", "engine": "inworld"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "paid_confirmation_required"
    assert calls == []  # nothing was billed

    ok = client.post(
        f"/api/v1/decks/{token}/jobs",
        json={"kind": "generate", "engine": "inworld", "allow_paid": True},
    )
    assert ok.status_code == 202
    assert _wait(client, ok.json()["id"])["status"] == "succeeded" and len(calls) == 1


def test_forced_whole_deck_generation_on_a_cached_paid_deck_needs_approval(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forcing re-bills every clip, so a fully cached deck still costs credits."""
    from slidesonnet.audio import synth as synth_mod

    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: _StubTTS(cfg.backend))
    token = _token(client)
    paid = {"kind": "generate", "engine": "inworld"}
    made = client.post(f"/api/v1/decks/{token}/jobs", json={**paid, "allow_paid": True})
    assert _wait(client, made.json()["id"])["status"] == "succeeded"  # now fully cached

    forced = client.post(f"/api/v1/decks/{token}/jobs", json={**paid, "force": True})
    assert forced.status_code == 403
    assert forced.json()["error"]["code"] == "paid_confirmation_required"


_INTRO = {"slide_id": "intro", "speech_index": 0}


@pytest.mark.parametrize(
    "job",
    [
        {"kind": "generate"},
        {"kind": "generate", "targets": [_INTRO]},
        {"kind": "generate", "targets": [_INTRO], "force": True},
        {"kind": "preview", "slide_id": "intro"},
        {"kind": "export", "draft": True},
    ],
    ids=["deck", "clip", "force", "preview", "export"],
)
def test_paid_work_makes_only_what_was_approved(
    client: TestClient, deck: Path, monkeypatch: pytest.MonkeyPatch, job: dict[str, Any]
) -> None:
    """The narration changes while an approved job waits: it refuses rather than bill the edit."""
    from slidesonnet.audio import synth as synth_mod
    from slidesonnet.server.engines import engine_lock

    made: list[str] = []

    class Counting(_StubTTS):
        def synthesize(self, text: str, output_path: Path, voice: str | None = None) -> float:
            made.append(text)
            return super().synthesize(text, output_path, voice)

    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: Counting(cfg.backend))
    token = _token(client)
    paid = {"engine": "inworld", "allow_paid": True}
    if job.get("force"):  # regenerating needs the clip made first
        first = client.post(f"/api/v1/decks/{token}/jobs", json={"kind": "generate", **paid})
        assert _wait(client, first.json()["id"])["status"] == "succeeded"
        made.clear()
    with engine_lock("inworld"):  # the approved job waits its turn…
        r = client.post(f"/api/v1/decks/{token}/jobs", json={**job, **paid})
        assert r.status_code == 202, r.text
        edited = SIDECAR.replace("Hello there.", "Hello there, and a line nobody approved.")
        (deck.parent / "talk.narration").write_text(simple_narration(edited), encoding="utf-8")
    done = _wait(client, r.json()["id"])  # …and the sidecar changed meanwhile
    assert done["status"] == "failed" and made == []
    assert "approve again to generate" in done["error"]["message"]


def test_previews_are_immutable_per_build_and_served_with_ranges(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B4: a second preview never rewrites the first one's track under its URL."""

    def fake_build(pdf: Path, *, only_id: str | None = None, render_dir: Path, **_: Any) -> Preview:
        render_dir.mkdir(parents=True, exist_ok=True)
        track = render_dir / "track.wav"  # rewritten in place, like the real assembler
        track.write_bytes(f"RIFF-audio-for-{only_id}".encode() * 50)
        return Preview(track=track, cues=[Cue(0.0, only_id or "intro")], total_duration=2.0)

    monkeypatch.setattr("slidesonnet.api.build_preview", fake_build)
    token = _token(client)

    def preview(slide: str) -> dict[str, Any]:
        r = client.post(f"/api/v1/decks/{token}/jobs", json={"kind": "preview", "slide_id": slide})
        assert r.status_code == 202, r.text
        job = _wait(client, r.json()["id"])
        assert job["status"] == "succeeded", job
        return dict(job["result"])

    first, second = preview("intro"), preview("middle")
    assert first["media_url"] != second["media_url"]
    body = client.get(first["media_url"])
    assert body.content.startswith(b"RIFF-audio-for-intro")  # still the first slide's audio
    assert "immutable" in body.headers["cache-control"]
    assert first["cues"] == [{"start": 0.0, "slide_id": "intro"}]

    part = client.get(first["media_url"], headers={"Range": "bytes=0-3"})
    assert part.status_code == 206 and part.content == b"RIFF"
    beyond = client.get(first["media_url"], headers={"Range": "bytes=999999-"})
    assert beyond.status_code == 416


def test_cancel_endpoint_stops_a_running_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    started = threading.Event()

    def slow_synth(*_a: Any, progress: Any = None, **_k: Any) -> int:
        started.set()
        for i in range(500):
            progress("synthesize", i, 500, "")
            time.sleep(0.01)
        return 0

    monkeypatch.setattr("slidesonnet.api.synthesize_deck", slow_synth)
    token = _token(client)
    job_id = client.post(f"/api/v1/decks/{token}/jobs", json={"kind": "generate"}).json()["id"]
    assert started.wait(5)
    assert client.post(f"/api/v1/jobs/{job_id}/cancel").json()["status"] in (
        "cancelling",
        "cancelled",
    )
    assert _wait(client, job_id)["status"] == "cancelled"


# ---- media --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path", ["nope/pages/page-1.png", "{t}/../../../etc/passwd", "{t}/missing.png"]
)
def test_media_refuses_unknown_decks_and_escapes(client: TestClient, path: str) -> None:
    assert client.get("/ssmedia/" + path.format(t=_token(client))).status_code == 404


# ---- events --------------------------------------------------------------------------------
def test_events_replay_a_write_and_flag_a_gap(client: TestClient) -> None:
    from slidesonnet.server.context import context_of

    token = _token(client)
    rev = _snapshot(client, token)["revisions"]["narration"]
    client.patch(
        f"/api/v1/decks/{token}/slides/intro",
        json={"expected_revision": rev, "segments": [_speech("Changed.")]},
    )
    bus = context_of(client.app).bus  # type: ignore[arg-type]
    changed = [e for e in bus.since(0) or [] if e.type == "deck.changed"]
    assert changed and changed[-1].deck == token
    assert bus.since(changed[-1].seq - 1) == [changed[-1]]


async def test_event_stream_replays_resyncs_and_goes_live() -> None:
    """The SSE body: replay after Last-Event-ID, resync on a gap, then live events."""
    import asyncio

    from slidesonnet.server.events import EventBus
    from slidesonnet.server.routes import event_stream

    bus = EventBus(capacity=2)
    for i in range(3):
        bus.publish("deck.changed", deck="d", data={"i": i})
    polls = {"n": 0}

    async def gone_after_a_while() -> bool:
        polls["n"] += 1
        return polls["n"] > 3

    async def collect(last: str | None) -> list[str]:
        sub = bus.subscribe()
        out: list[str] = []
        stream = event_stream(bus, sub, last, gone_after_a_while, heartbeat=0.01)
        async for chunk in stream:
            out.append(chunk)
            if len(out) == 2 and last == "2":
                bus.publish("job.finished", deck="d", data={"job_id": "j1"})
        return out

    replayed = await collect("2")
    assert replayed[0].startswith("retry:")
    assert "id: 3\nevent: deck.changed" in replayed[1]
    assert any("event: job.finished" in c and '"job_id": "j1"' in c for c in replayed)
    polls["n"] = 0
    gap = await asyncio.wait_for(collect("0"), timeout=10)  # seq 1 fell out of the buffer
    assert "event: resync" in gap[1]


async def test_a_subscriber_that_falls_behind_is_told_to_resync_then_goes_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full backlog drops the stale events for one resync, not a partial history."""
    import asyncio

    from slidesonnet.server import events
    from slidesonnet.server.routes import event_stream

    monkeypatch.setattr(events, "_SUBSCRIBER_BACKLOG", 2)
    bus = events.EventBus()
    sub = bus.subscribe()
    for i in range(3):  # one more than the backlog holds
        bus.publish("deck.changed", deck="d", data={"i": i})
    await asyncio.sleep(0)  # deliveries hop onto this loop

    async def never_gone() -> bool:
        return False

    stream = event_stream(bus, sub, None, never_gone, heartbeat=5)
    assert (await anext(stream)).startswith("retry:")
    assert await anext(stream) == 'id: 3\nevent: resync\ndata: {"type": "resync"}\n\n'
    bus.publish("job.finished", deck="d", data={"job_id": "j1"})
    live = await asyncio.wait_for(anext(stream), timeout=5)
    assert live.startswith("id: 4\nevent: job.finished")  # not the dropped deck.changed
    await stream.aclose()


async def test_the_watcher_announces_an_outside_edit_once(
    deck: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each changed deck gets one deck.changed; a read error or a vanished deck can't stop it."""
    import asyncio

    from slidesonnet.server import decks
    from slidesonnet.server.context import ServerContext
    from slidesonnet.server.revisions import content_revision

    monkeypatch.setattr("slidesonnet.server.context.WATCH_INTERVAL_S", 0.01)
    real_service = decks.deck_service
    reads = {"n": 0}

    class FlakyOnce:
        def __init__(self, service: decks.DeckService) -> None:
            self.service = service

        def revisions(self) -> Any:
            reads["n"] += 1
            if reads["n"] == 1:
                raise OSError("the file is being replaced")
            return self.service.revisions()

    monkeypatch.setattr(
        decks, "deck_service", lambda pdf, sidecar: FlakyOnce(real_service(pdf, sidecar))
    )
    registry = DeckRegistry(deck.parent.parent)
    registry.rescan()
    ctx = ServerContext(registry)
    (entry,) = registry.entries()
    before = real_service(entry.pdf_path, entry.sidecar_path).revisions()
    ctx.watch(entry.token, before)
    ctx.watch("gone", before)  # a deck no longer in the library
    sidecar = deck.with_suffix(".narration")
    sidecar.write_text(simple_narration(SIDECAR.replace("Hello there.", "Hi.")), "utf-8")
    ctx.ensure_watcher()
    try:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if reads["n"] >= 5:  # several ticks past the first (failed) read
                break
    finally:
        ctx.shutdown()
    changed = [e for e in ctx.bus.since(0) or [] if e.type == "deck.changed"]
    assert [(e.deck, e.data["narration"]) for e in changed] == [
        (entry.token, content_revision(sidecar))
    ]
    assert "gone" not in ctx.watched


def test_export_explains_blockers_and_runs_a_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain build can't be exported as final; the draft export runs as a job."""
    from slidesonnet import api as api_mod

    (tmp_path / "d").mkdir()
    write_pdf(tmp_path / "d" / "d.pdf", ["intro"], plain=True)
    (tmp_path / "d" / "d.narration").write_text(simple_narration("@intro\nHi.\n"), "utf-8")
    seen: dict[str, Any] = {}

    def fake_export(pdf_path: Path, output: Path, **kw: Any) -> api_mod.ExportResult:
        seen.update(kw)
        return api_mod.ExportResult(video=output.with_suffix(".draft.mp4"), duration=3.0)

    monkeypatch.setattr("slidesonnet.api.export", fake_export)
    monkeypatch.setattr("slidesonnet.server.routes._uncached", lambda *a, **k: set())
    registry = DeckRegistry(tmp_path)
    registry.rescan()
    with TestClient(create_api_app(registry)) as c:
        c.headers[SESSION_HEADER] = c.get("/api/v1/session").json()["token"]
        token = c.get("/api/v1/library").json()["sections"][0]["decks"][0]["token"]
        final = c.post(f"/api/v1/decks/{token}/jobs", json={"kind": "export"})
        assert final.status_code == 409 and final.json()["error"]["code"] == "export_blocked"
        assert "plain build" in final.json()["error"]["message"]
        draft = c.post(f"/api/v1/decks/{token}/jobs", json={"kind": "export", "draft": True})
        job = _wait(c, draft.json()["id"])
    assert job["status"] == "succeeded"
    assert job["result"] == {"video": "d.draft.mp4", "duration": 3.0, "draft": True, "fast": False}
    assert seen["draft"] is True and seen["keep_scratch"] is True and seen["fast"] is False


def test_an_export_with_another_engine_is_not_merged_into_the_running_one(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet import api as api_mod

    gate = threading.Event()

    def slow_export(pdf_path: Path, output: Path, **kw: Any) -> api_mod.ExportResult:
        gate.wait(5)
        return api_mod.ExportResult(video=output, duration=1.0)

    monkeypatch.setattr("slidesonnet.api.export", slow_export)
    monkeypatch.setattr("slidesonnet.server.routes._uncached", lambda *a, **k: set())
    token = _token(client)
    url = f"/api/v1/decks/{token}/jobs"
    try:
        ids = [
            client.post(url, json={"kind": "export", "draft": True, "engine": e, "fast": f}).json()[
                "id"
            ]
            for e, f in (("kokoro", False), ("kokoro", False), ("qwen3", False), ("kokoro", True))
        ]
    finally:
        gate.set()
    assert ids[0] == ids[1] != ids[2]
    assert ids[3] not in ids[:3]  # a quick export is not the full-quality one


# ---- the per-deck generation queue ---------------------------------------------------------
def test_generation_queue_generates_and_reports_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.audio import synth as synth_mod

    monkeypatch.setattr(synth_mod, "create_tts", lambda cfg: _StubTTS(cfg.backend))
    token = _token(client)
    r = client.post(
        f"/api/v1/decks/{token}/generation",
        json={"targets": [{"slide_id": "intro", "speech_index": 0}], "owner": "tab-1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["queued"] == 1
    for _ in range(500):
        status = client.get(f"/api/v1/decks/{token}/generation").json()
        if status["total"] and status["done"] == status["total"] and not status["inflight"]:
            break
        time.sleep(0.02)
    assert status["done"] == 1
    clips = _snapshot(client, token)["pages"][0]["clips"]
    assert clips[0]["cached"] is True and clips[0]["bytes"] > 0


def test_generation_cancel_by_owner_and_paid_gate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = _token(client)
    paid = client.post(f"/api/v1/decks/{token}/generation", json={"engine": "inworld"})
    assert paid.status_code == 403
    assert paid.json()["error"]["code"] == "paid_confirmation_required"

    import threading

    gate = threading.Event()
    monkeypatch.setattr(
        "slidesonnet.server.generation.api.synthesize_deck", lambda *a, **k: gate.wait(5) and 0
    )
    client.post(f"/api/v1/decks/{token}/generation", json={"owner": "tab-1"})  # both clips
    dropped = client.post(
        f"/api/v1/decks/{token}/generation/cancel", json={"owner": "tab-1"}
    ).json()["count"]
    gate.set()
    assert dropped == 1  # the queued clip went; the running one finishes
    assert (
        client.post(f"/api/v1/decks/{token}/focus", json={"slide_id": "middle"}).status_code == 200
    )


def test_a_failed_clip_is_announced_with_its_line_and_a_plain_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slidesonnet.exceptions import TTSError
    from slidesonnet.server.context import context_of

    def broken(*a: Any, **k: Any) -> None:
        raise TTSError("Environment variable 'INWORLD_API_KEY' not set. Add it to your .env file.")

    monkeypatch.setattr("slidesonnet.server.generation.api.synthesize_deck", broken)
    token = _token(client)
    target = {"slide_id": "middle", "speech_index": 0}
    client.post(f"/api/v1/decks/{token}/generation", json={"targets": [target]})
    bus = context_of(client.app).bus  # type: ignore[arg-type]
    for _ in range(200):
        failed = [e for e in bus.since(0) or [] if e.type == "generation.failed"]
        if failed:
            break
        time.sleep(0.02)
    data = failed[-1].data
    assert data["code"] == "missing_api_key" and data["clips"] == [target]
    assert data["message"] == "The API key is missing: add INWORLD_API_KEY to your .env file."
    assert "not set" in data["detail"]  # the raw text, for the curious


@pytest.mark.parametrize(
    ("engine", "exc", "code", "words"),
    [
        ("inworld", RuntimeError("Inworld synthesis failed: voice 'Zed' not found"), "unknown_voice",
         "Inworld doesn't know the voice"),
        ("kokoro", AssertionError(), "unknown_voice", "Kokoro doesn't know the voice"),
        ("kokoro", ModuleNotFoundError("No module named 'kokoro'"), "engine_missing",
         "Kokoro isn't installed"),
        ("qwen3", RuntimeError("qwen-tts package not installed. Install with: pip install x"),
         "engine_missing", "Qwen3 isn't installed"),
        ("kokoro", RuntimeError("disk full"), "failed", "Couldn't generate this line"),
        ("inworld", UnapprovedClips(2), "narration_changed", "approve again to generate 2 new"),
    ],
)  # fmt: skip
def test_generation_failures_are_explained_in_plain_words(
    engine: str, exc: BaseException, code: str, words: str
) -> None:
    from slidesonnet.server.generation import explain_failure

    got_code, message = explain_failure(engine, exc)
    assert got_code == code and words in message


def test_meta_voices_pages_and_snapshot_extras(client: TestClient) -> None:
    meta = client.get("/api/v1/meta").json()
    wipe = next(f for f in meta["transitions"] if f["key"] == "wipe")
    assert ["Left", "wipeleft"] in wipe["options"] and meta["aliases"] == {"crossfade": "fade"}
    voices = client.get("/api/v1/engines/kokoro/voices").json()
    assert voices["default"] in voices["voices"]
    token = _token(client)
    pages = client.get(f"/api/v1/decks/{token}/pages").json()
    assert len(pages["images"]) == 3
    snap = _snapshot(client, token)
    assert snap["silence"]["start"] >= 0 and snap["silence"]["end"] >= 0
    assert snap["neighbours"] == {"prev": None, "next": None}  # a one-deck library
    assert snap["pages"][0]["clips"] == [{"cached": False, "seconds": None, "bytes": None}]


def test_a_pdf_caught_mid_recompile_is_a_readable_retry(client: TestClient, deck: Path) -> None:
    """While the PDF is missing or half-written, the editor keeps its last good view."""
    token = _token(client)
    good = deck.read_bytes()
    deck.write_bytes(b"%PDF-1.5 garbage truncated")  # pdflatex mid-write
    r = client.get(f"/api/v1/decks/{token}")
    assert r.status_code == 503 and r.json()["error"]["code"] == "deck_unavailable"
    deck.unlink()
    assert client.get(f"/api/v1/decks/{token}").status_code == 503
    deck.write_bytes(good)
    assert client.get(f"/api/v1/decks/{token}").status_code == 200


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("GET", "/api/v1/decks/{t}", None),
        ("GET", "/api/v1/decks/{t}/stats", None),
        ("GET", "/api/v1/decks/{t}/generation", None),
        ("POST", "/api/v1/decks/{t}/generation", {}),
    ],
)
def test_a_broken_config_is_a_readable_error_everywhere(
    client: TestClient, deck: Path, method: str, url: str, body: dict[str, Any] | None
) -> None:
    (deck.parent / "slidesonnet.toml").write_text("[tts\n", encoding="utf-8")
    r = client.request(method, url.format(t=_token(client)), json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "deck_file_error"


@pytest.mark.parametrize("url", ["/api/v1/decks/{t}/pages", "/api/v1/decks/{t}/export-blockers"])
def test_a_missing_pdf_is_a_readable_retry_everywhere(
    client: TestClient, deck: Path, url: str
) -> None:
    token = _token(client)
    deck.unlink()
    r = client.get(url.format(t=token))
    assert r.status_code == 503 and r.json()["error"]["code"] == "deck_unavailable"


def test_edit_refusals_are_slidesonnet_errors() -> None:
    from slidesonnet.exceptions import SlideSonnetError
    from slidesonnet.server.decks import RevisionConflict
    from slidesonnet.server.editing import EditError

    assert issubclass(RevisionConflict, SlideSonnetError)
    assert issubclass(EditError, SlideSonnetError) and issubclass(EditError, ValueError)


def test_a_bug_is_not_reported_as_a_pdf_being_rewritten(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("a genuine bug")

    monkeypatch.setattr("slidesonnet.server.snapshots.deck_stats", broken)
    with pytest.raises(RuntimeError, match="genuine bug"):  # a 500, not "deck_unavailable"
        client.get(f"/api/v1/decks/{_token(client)}/stats")


def test_the_editor_starts_on_inworld_unless_the_deck_chooses(
    client: TestClient, deck: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inworld is the editor's starting engine (conftest pins Kokoro for the rest
    of the suite); a deck whose slidesonnet.toml names an engine keeps it. The
    CLI is unaffected: its default stays the free Kokoro."""
    from slidesonnet.server import engines

    monkeypatch.setattr(engines, "EDITOR_DEFAULT_ENGINE", "inworld")
    token = _token(client)
    snap = client.get(f"/api/v1/decks/{token}").json()
    assert snap["engine"] == "inworld"
    # a job naming no engine runs on the same one — so it asks before billing
    r = client.post(f"/api/v1/decks/{token}/jobs", json={"kind": "generate"})
    assert r.json()["error"]["code"] == "paid_confirmation_required"

    (deck.parent / "slidesonnet.toml").write_text('[tts]\nbackend = "kokoro"\n', encoding="utf-8")
    snap = client.get(f"/api/v1/decks/{token}").json()
    assert snap["engine"] == "kokoro"


def test_the_api_schema_is_written_to_its_file_not_through_stdout(tmp_path: Path) -> None:
    """A library printing to stdout at import (PyMuPDF 1.28 warns about ``fitz``)
    must not end up inside the schema the TypeScript types are generated from."""
    import json

    from slidesonnet.server import openapi

    out = tmp_path / "openapi.json"
    print("warning: some library chatter")
    openapi.main([str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["openapi"].startswith("3.")
