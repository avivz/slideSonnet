"""``slidesonnet review …`` — conversations about slides, diffs against the base.

Registered on the main CLI group in :mod:`slidesonnet.cli`. Agents use these
commands instead of editing ``<deck>.review`` by hand, so every write is a
validated, locked append.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

import click

from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.review.log import Author, Conversation

_PDF = click.argument("pdf", type=click.Path(exists=True, path_type=Path))
_AS = click.option(
    "--as",
    "author",
    type=click.Choice(["agent", "author"]),
    help="Who is writing (default: agent for reply/comment, author for accept/reopen/send)",
)
#: ``review wait`` exit status when --timeout runs out (2 is Click's usage error).
WAIT_TIMED_OUT = 3

_JSON = click.option("--json", "as_json", is_flag=True, help="Machine-readable output")


def _errors() -> Any:
    from slidesonnet.cli import _cli_errors

    return _cli_errors()


def _conv_json(conv: Conversation) -> dict[str, Any]:
    return {
        "id": conv.id,
        "title": conv.title,
        "slides": list(conv.slides),
        "origin": conv.origin,
        "status": conv.status,
        "turn": conv.turn,
        "messages": [{"author": m.author, "at": m.at, "text": m.text} for m in conv.messages],
    }


def _turn_label(conv: Conversation) -> str:
    if conv.status == "closed":
        return "closed"
    return "your turn" if conv.turn == "author" else "agent's turn"


@click.group()
def review() -> None:
    """Review agent changes: per-slide conversations and diffs against the base.

    \b
    The base is the last-cleared version of every slide (taken automatically
    on first use). A conversation covers one or more slides; "deck" is the
    permanent deck-wide conversation. Accept closes a conversation; "clear"
    drops closed ones and moves their slides' base forward.

    \b
    Agent loop:
      slidesonnet review wait deck.pdf --since N --json   # block until "send"
      slidesonnet review list deck.pdf --mine --json      # what needs you
      slidesonnet review reply deck.pdf c3 --add-slides @x "Split into two."
      slidesonnet review status deck.pdf                  # no unfiled changes
    """


@review.command("snapshot")
@_PDF
def snapshot_cmd(pdf: Path) -> None:
    """Mark everything as seen: the base becomes the deck as it is now.

    The editor takes a base by itself the first time it opens a deck; this
    resets it (and creates <deck>.review if needed).
    """
    from slidesonnet.review import ops

    with _errors():
        version = ops.start(pdf)
    click.echo(f"Base taken: {len(version.order)} slides. Review is on.")


@review.command("status")
@_PDF
@_JSON
def status_cmd(pdf: Path, as_json: bool) -> None:
    """Changed slides, conversations and whose turn it is, unfiled changes."""
    from slidesonnet.review import ops

    with _errors():
        st = ops.status(pdf)
    in_conv: dict[str, list[str]] = {}
    for conv in st.state.slide_conversations():
        for sid in conv.slides:
            in_conv.setdefault(sid, []).append(conv.id)
    titles = {}
    for version in (st.base, st.current):
        if version is not None:
            titles.update({sid: s.title for sid, s in version.slides.items()})
    if as_json:
        click.echo(
            json.dumps(
                {
                    "final_build": st.final_build,
                    "changes": [
                        {
                            "id": c.slide_id,
                            "title": titles.get(c.slide_id, ""),
                            "kinds": list(c.kinds),
                            "image": c.image,
                            "narration": c.narration,
                            "base_index": c.base_index,
                            "current_index": c.current_index,
                            "conversations": in_conv.get(c.slide_id, []),
                        }
                        for c in st.changes
                    ],
                    "unfiled": st.unfiled,
                    "pending": st.pending,
                    "conversations": [_conv_json(c) for c in st.state.conversations.values()],
                },
                indent=1,
                ensure_ascii=False,
            )
        )
        return
    if st.final_build:
        click.echo("Final build — comparison paused. Recompile normally to review changes.")
    elif not st.changes:
        click.echo("No changes since the base.")
    else:
        click.echo(f"Changed slides ({len(st.changes)}):")
        for c in st.changes:
            detail = [k for k, on in (("slide", c.image), ("narration", c.narration)) if on]
            kinds = ", ".join(c.kinds) + (f" ({', '.join(detail)})" if detail else "")
            where = ", ".join(in_conv.get(c.slide_id, [])) or "UNFILED"
            click.echo(f"  @{c.slide_id:<24} {kinds:<32} {where}  {titles.get(c.slide_id, '')}")
    if st.unfiled:
        click.echo(
            "Unfiled (changed, in no conversation): "
            + " ".join(f"@{s}" for s in st.unfiled)
            + "\n  → add them to the conversation they belong to: review reply … --add-slides"
        )
    if st.pending:
        click.echo(
            "Not in the PDF yet (declared — compile, or fix the id): "
            + " ".join(f"@{sid} ({', '.join(cids)})" for sid, cids in st.pending.items())
        )
    convs = [c for c in st.state.conversations.values() if c.messages or not c.is_deck]
    if convs:
        click.echo("Conversations:")
        for conv in convs:
            scope = " ".join(f"@{s}" for s in conv.slides) or "(whole deck)"
            click.echo(f"  {conv.id:<5} {_turn_label(conv):<13} {scope}")


@review.command("list")
@_PDF
@_JSON
@click.option("--mine", is_flag=True, help="Only open conversations where it's the agent's turn")
@click.option("--all", "show_all", is_flag=True, help="Include closed (accepted) conversations")
def list_cmd(pdf: Path, as_json: bool, mine: bool, show_all: bool) -> None:
    """Open conversations with their messages (JSON adds each slide's page text)."""
    from slidesonnet.review import ops

    with _errors():
        st = ops.status(pdf)
    convs = list(st.state.conversations.values())
    if not show_all or mine:
        convs = [c for c in convs if c.status == "open"]
    if mine:
        convs = [c for c in convs if c.turn == "agent"]
    if as_json:
        out = []
        for conv in convs:
            data = _conv_json(conv)
            pages: dict[str, dict[str, str]] = {}
            for sid in conv.slides:
                base = st.base.slides.get(sid) if st.base else None
                cur = st.current.slides.get(sid) if st.current else None
                either = cur or base
                pages[sid] = {
                    "title": either.title if either is not None else "",
                    "base_text": base.text if base else "",
                    "current_text": cur.text if cur else "",
                }
            data["pages"] = pages
            out.append(data)
        click.echo(json.dumps({"conversations": out}, indent=1, ensure_ascii=False))
        return
    for conv in convs:
        if conv.is_deck and not conv.messages:
            continue
        scope = " ".join(f"@{s}" for s in conv.slides) or "(whole deck)"
        name = f"  {conv.title}" if conv.title else ""
        click.echo(f"── {conv.id}{name}  {_turn_label(conv)}  {scope}")
        for msg in conv.messages:
            click.echo(f"   {msg.author} {msg.at[11:16]}: {msg.text}")


def _note_uncompiled(slide_ids: list[str]) -> None:
    if slide_ids:
        click.echo(
            "note: " + " ".join(f"@{s}" for s in slide_ids) + " not in the PDF yet — fine if "
            "you're about to compile it; `review status` lists it until it appears",
            err=True,  # stdout stays just the conversation id, for scripts
        )


@review.command("comment")
@_PDF
@click.argument("slides", nargs=-1, required=True)
@click.option("-m", "--text", required=True, help="The message")
@click.option("--title", default="", help="A short name for the conversation")
@_AS
def comment_cmd(
    pdf: Path, slides: tuple[str, ...], text: str, title: str, author: str | None
) -> None:
    """Open a conversation about SLIDES (e.g. @euler-trick @euler-result)."""
    from slidesonnet.review import ops

    if any(s.lstrip("@") == "deck" for s in slides):
        raise click.UsageError(
            "the deck conversation always exists — write to it with "
            '`slidesonnet review reply <pdf> deck -m "…"`'
        )
    with _errors():
        cid = ops.comment(
            pdf, list(slides), text, author=cast(Author, author or "agent"), title=title
        )
        _note_uncompiled(ops.not_in_deck(pdf, list(slides)))
    click.echo(cid)


@review.command("reply")
@_PDF
@click.argument("conversation")
@click.argument("text", required=False)
@click.option("-m", "--text", "text_opt", help="The message (or give it as TEXT)")
@click.option(
    "--add-slides",
    multiple=True,
    help="Widen the conversation to this slide (repeatable, or space-separated)",
)
@click.option("--title", default="", help="Rename the conversation (a short name)")
@_AS
def reply_cmd(
    pdf: Path,
    conversation: str,
    text: str | None,
    text_opt: str | None,
    add_slides: tuple[str, ...],
    title: str,
    author: str | None,
) -> None:
    """Add a message to CONVERSATION ("deck" = the deck-wide conversation)."""
    from slidesonnet.review import ops

    message = text_opt if text_opt is not None else text
    if not message:
        raise click.UsageError("give the message as TEXT or with -m")
    slides = [s for group in add_slides for s in group.split()]
    with _errors():
        _note_uncompiled(ops.not_in_deck(pdf, slides))
        ops.reply(
            pdf,
            conversation,
            message,
            author=cast(Author, author or "agent"),
            add_slides=slides,
            title=title,
        )


@review.command("title")
@_PDF
@click.argument("conversation")
@click.argument("title")
@_AS
def title_cmd(pdf: Path, conversation: str, title: str, author: str | None) -> None:
    """Name CONVERSATION (the id stays its identifier)."""
    from slidesonnet.review import ops

    with _errors():
        ops.retitle(pdf, conversation, title, author=cast(Author, author or "agent"))


@review.command("accept")
@_PDF
@click.argument("conversation")
def accept_cmd(pdf: Path, conversation: str) -> None:
    """Close CONVERSATION — its changes are tentatively accepted until "clear"."""
    from slidesonnet.review import ops

    with _errors():
        ops.accept(pdf, conversation)


@review.command("reopen")
@_PDF
@click.argument("conversation")
def reopen_cmd(pdf: Path, conversation: str) -> None:
    """Reopen a closed (not yet cleared) conversation."""
    from slidesonnet.review import ops

    with _errors():
        ops.reopen(pdf, conversation)


@review.command("clear")
@_PDF
def clear_cmd(pdf: Path) -> None:
    """Drop closed conversations and move their slides' base forward."""
    from slidesonnet.review import ops

    with _errors():
        result = ops.clear(pdf)
    if not result.cleared:
        click.echo("Nothing to clear — no closed conversations.")
        return
    click.echo(
        f"Cleared {len(result.cleared)} conversation(s); base moved forward for "
        f"{len(result.advanced)} slide(s)."
    )
    if result.skipped:
        click.echo(
            "Kept the old base for "
            + " ".join(f"@{s}" for s in result.skipped)
            + " — still in an open conversation."
        )


@review.command("show")
@_PDF
@click.argument("slide")
@click.option(
    "--base", is_flag=True, expose_value=False, help="Show the base version (the default)"
)
@_JSON
def show_cmd(pdf: Path, slide: str, as_json: bool) -> None:
    """The base version of SLIDE: narration block, page text, page image path."""
    from slidesonnet.review.base import base_image, load_base

    sid = slide.removeprefix("@")
    base = load_base(pdf)
    if base is None or sid not in base.slides:
        raise click.ClickException(f"no base version of @{sid}")
    version = base.slides[sid]
    image = base_image(pdf, sid)
    if as_json:
        data = {
            "id": sid,
            "narration": version.narration,
            "text": version.text,
            "image": str(image) if image else None,
        }
        click.echo(json.dumps(data, indent=1, ensure_ascii=False))
        return
    click.echo(f"# base version of @{sid}")
    click.echo(f"# page image: {image}")
    click.echo("# page text:")
    click.echo("\n".join(f"#   {line}" for line in version.text.splitlines()))
    click.echo(version.narration or "(no narration)")


@review.command("send")
@_PDF
def send_cmd(pdf: Path) -> None:
    """Release anyone waiting in "review wait" (the editor's Send button)."""
    from slidesonnet.review import ops

    with _errors():
        ops.send(pdf)


@review.command("wait")
@_PDF
@click.option("--since", type=int, default=0, show_default=True, help="Cursor from the last wait")
@click.option("--timeout", type=float, help="Give up after this many seconds (exit code 3)")
@_JSON
def wait_cmd(pdf: Path, since: int, timeout: float | None, as_json: bool) -> None:
    """Block until the author presses Send; print what awaits the agent.

    \b
    Exit codes:
      0  the author pressed Send
      1  an error (e.g. not a slideSonnet deck)
      2  a usage error (a bad option)
      3  --timeout ran out first
    """
    from slidesonnet.review import ops

    try:
        result = ops.wait(pdf, since=since, timeout=timeout)
    except SlideSonnetError as exc:
        raise click.ClickException(str(exc)) from exc
    if result is None:
        click.echo("timed out", err=True)
        sys.exit(WAIT_TIMED_OUT)
    if as_json:
        data = {
            "cursor": result.cursor,
            "awaiting_agent": [_conv_json(c) for c in result.awaiting_agent],
        }
        click.echo(json.dumps(data, indent=1, ensure_ascii=False))
        return
    click.echo(f"cursor {result.cursor}")
    for conv in result.awaiting_agent:
        click.echo(f"  {conv.id}  {' '.join('@' + s for s in conv.slides) or '(whole deck)'}")
