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

from slidesonnet.cli_options import EXISTING_NARRATION_OPT
from slidesonnet.exceptions import SlideSonnetError
from slidesonnet.review.log import Author, Conversation


def _working_build(_ctx: click.Context, _param: click.Parameter, pdf: Path) -> Path:
    """Review compares the deck's working build: ``X.plain.pdf`` when it's beside ``X.pdf``."""
    from slidesonnet.builds import working_pdf

    return working_pdf(pdf)


_PDF = click.argument("pdf", type=click.Path(exists=True, path_type=Path), callback=_working_build)
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
    on first use). A conversation covers one or more slides, or none: then it
    is about the whole deck. Accept closes a conversation; "clear" drops closed
    ones and moves their slides' base forward.

    \b
    Agent loop:
      slidesonnet review wait --since CURSOR --json       # block until "send" in any deck here
      slidesonnet review list deck.pdf --mine --json      # what needs you
      slidesonnet review reply deck.pdf c3 --add-slides @x "Split into two."
      slidesonnet review status deck.pdf                  # no unfiled changes

    \b
    Scripts that only need conversation states (fast, never reads the PDF):
      slidesonnet review summary --root COURSE --json
    """


@review.command("snapshot")
@_PDF
@EXISTING_NARRATION_OPT
def snapshot_cmd(pdf: Path, narration: Path | None) -> None:
    """Mark everything as seen: the base becomes the deck as it is now.

    The editor takes a base by itself the first time it opens a deck; this
    resets it (and creates <deck>.review if needed).
    """
    from slidesonnet.review import ops

    with _errors():
        version = ops.start(pdf, sidecar_path=narration)
    click.echo(f"Base taken: {len(version.order)} slides. Review is on.")


@review.command("status")
@_PDF
@_JSON
@EXISTING_NARRATION_OPT
def status_cmd(pdf: Path, as_json: bool, narration: Path | None) -> None:
    """Changed slides, conversations and whose turn it is, unfiled changes.

    Slow (seconds per deck): it reads every page of the PDF to compare it with
    the base, and takes the base on first use. For a quick, read-only look at
    the conversations (scripts, publish gates) use "review summary".
    """
    from slidesonnet.review import ops

    with _errors():
        st = ops.status(pdf, sidecar_path=narration)
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
    convs = list(st.state.conversations.values())
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
@EXISTING_NARRATION_OPT
def list_cmd(pdf: Path, as_json: bool, mine: bool, show_all: bool, narration: Path | None) -> None:
    """Open conversations with their messages (JSON adds each slide's page text).

    Slow (seconds per deck): it reads every page of the PDF, and takes the base
    on first use. For just each conversation's id, status, turn and slides,
    across many decks at once, use "review summary" (reads only the review log).
    """
    from slidesonnet.review import ops

    with _errors():
        st = ops.status(pdf, sidecar_path=narration)
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
        scope = " ".join(f"@{s}" for s in conv.slides) or "(whole deck)"
        name = f"  {conv.title}" if conv.title else ""
        click.echo(f"── {conv.id}{name}  {_turn_label(conv)}  {scope}")
        for msg in conv.messages:
            click.echo(f"   {msg.author} {msg.at[11:16]}: {msg.text}")


@review.command("summary")
@click.argument("pdfs", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="With no PDF: every deck under this folder (default: the current one)",
)
@_JSON
def summary_cmd(pdfs: tuple[Path, ...], root: Path | None, as_json: bool) -> None:
    """Each deck's conversations — id, status, whose turn, slides, title — fast.

    \b
    Reads only the review log (<deck>.review): never the PDF or the base, and it
    changes nothing, so it takes well under a second for a whole course. For
    scripts and publish gates; "list" and "status" read every page (seconds per
    deck) to show page text and changed slides.

    \b
    One or more decks: review summary a.pdf b.pdf
    A whole course:    review summary [--root DIR]   (every deck under it)

    A deck without a review log is reported as "no review" (not an error).

    \b
    --json prints {"decks": [{"pdf", "review", "conversations": [...]}, ...]}:
      pdf            the deck, as you'd type it from here
      review         false when the deck has no review log
      conversations  each {"id", "title", "slides", "status", "turn"}:
                     slides [] = about the whole deck; status "open" | "closed";
                     turn "author" | "agent" (who acts next, if it's open)
    """
    from slidesonnet.builds import deck_pdf
    from slidesonnet.review.log import read_state, review_path

    if pdfs and root is not None:
        raise click.UsageError("give PDFs or --root, not both")
    if pdfs:
        decks = [deck_pdf(p.resolve()) for p in pdfs]
    else:
        from slidesonnet.server.library import discover_decks

        decks = [deck_pdf(entry.pdf_path) for entry in discover_decks(root or Path.cwd()).decks]
    out = []
    for pdf in dict.fromkeys(decks):  # a deck named by both of its builds: once
        log = review_path(pdf)
        with _errors():
            convs = list(read_state(log).conversations.values()) if log.exists() else []
        out.append((pdf, log.exists(), convs))
    if as_json:
        data = {
            "decks": [
                {
                    "pdf": _shown(pdf),
                    "review": has_log,
                    "conversations": [
                        {
                            "id": c.id,
                            "title": c.title,
                            "slides": list(c.slides),
                            "status": c.status,
                            "turn": c.turn,
                        }
                        for c in convs
                    ],
                }
                for pdf, has_log, convs in out
            ]
        }
        click.echo(json.dumps(data, indent=1, ensure_ascii=False))
        return
    for pdf, has_log, convs in out:
        if not convs:
            click.echo(f"{_shown(pdf)}  {'no conversations' if has_log else 'no review'}")
            continue
        click.echo(_shown(pdf))
        for conv in convs:
            scope = " ".join(f"@{s}" for s in conv.slides) or "(whole deck)"
            name = f"  {conv.title}" if conv.title else ""
            click.echo(f"  {conv.id:<3} {_turn_label(conv):<13} {scope}{name}")


def _note_uncompiled(slide_ids: list[str]) -> None:
    if slide_ids:
        click.echo(
            "note: " + " ".join(f"@{s}" for s in slide_ids) + " not in the PDF yet — fine if "
            "you're about to compile it; `review status` lists it until it appears",
            err=True,  # stdout stays just the conversation id, for scripts
        )


@review.command("comment")
@_PDF
@click.argument("slides", nargs=-1)
@click.option("-m", "--text", help="The message (or give it last, after the slides)")
@click.option("--title", default="", help="A short name for the conversation")
@_AS
def comment_cmd(
    pdf: Path, slides: tuple[str, ...], text: str | None, title: str, author: str | None
) -> None:
    """Open a conversation about SLIDES (e.g. @euler-trick @euler-result).

    With no slides it is about the whole deck — standing instructions ("British
    spelling everywhere") can stay in one left open.
    """
    from slidesonnet.review import ops

    ids = list(slides)
    if text is None and ids and not ids[-1].startswith("@"):
        text = ids.pop()  # the message, given last
    if not text:
        raise click.UsageError("give the message with -m (or last, after the slides)")
    with _errors():
        cid = ops.comment(pdf, ids, text, author=cast(Author, author or "agent"), title=title)
        _note_uncompiled(ops.not_in_deck(pdf, ids))
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
@click.option(
    "--remove-slides",
    multiple=True,
    help="Take this slide out of the conversation (repeatable, or space-separated)",
)
@click.option("--title", default="", help="Rename the conversation (a short name)")
@_AS
def reply_cmd(
    pdf: Path,
    conversation: str,
    text: str | None,
    text_opt: str | None,
    add_slides: tuple[str, ...],
    remove_slides: tuple[str, ...],
    title: str,
    author: str | None,
) -> None:
    """Add a message to CONVERSATION (an id like c3)."""
    from slidesonnet.review import ops

    message = text_opt if text_opt is not None else text
    if not message:
        raise click.UsageError("give the message as TEXT or with -m")
    slides = [s for group in add_slides for s in group.split()]
    removed = [s for group in remove_slides for s in group.split()]
    with _errors():
        _note_uncompiled(ops.not_in_deck(pdf, slides))
        ops.reply(
            pdf,
            conversation,
            message,
            author=cast(Author, author or "agent"),
            add_slides=slides,
            remove_slides=removed,
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
@EXISTING_NARRATION_OPT
def clear_cmd(pdf: Path, narration: Path | None) -> None:
    """Drop closed conversations and move their slides' base forward."""
    from slidesonnet.review import ops

    with _errors():
        result = ops.clear(pdf, sidecar_path=narration)
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


#: How often a wait on a whole folder looks for new decks, in seconds.
WAIT_RESCAN_SECONDS = 30.0


def _conv_line(conv: Conversation) -> str:
    return f"  {conv.id}  {' '.join('@' + s for s in conv.slides) or '(whole deck)'}"


def _shown(pdf: Path) -> str:
    """*pdf* relative to the current directory when it's under it (what you'd type)."""
    try:
        return pdf.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(pdf)


@review.command("wait")
@click.argument("pdfs", nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="With no PDF: watch every deck under this folder (default: the current one)",
)
@click.option(
    "--since",
    default="0",
    show_default=True,
    help="Cursor from the last wait (a number for one deck, a d:… token for several)",
)
@click.option("--timeout", type=float, help="Give up after this many seconds (exit code 3)")
@_JSON
def wait_cmd(
    pdfs: tuple[Path, ...], root: Path | None, since: str, timeout: float | None, as_json: bool
) -> None:
    """Block until the author presses Send; print what awaits the agent.

    \b
    One deck:      review wait deck.pdf --since N
    A whole course (every deck under the current folder, or --root):
                   review wait --since CURSOR
    Several decks: review wait a.pdf b.pdf --since CURSOR

    With more than one deck it prints each deck that has news, with its
    conversations waiting for you, then the cursor to pass back. With no
    cursor (a first wait) it returns at once for any deck whose author
    already sent something you haven't answered.

    \b
    Exit codes:
      0  the author pressed Send
      1  an error (e.g. not a slideSonnet deck)
      2  a usage error (a bad option)
      3  --timeout ran out first
    """
    from slidesonnet.builds import working_pdf

    if pdfs and root is not None:
        raise click.UsageError("give PDFs or --root, not both")
    if len(pdfs) == 1:
        _wait_one(working_pdf(pdfs[0]), since, timeout, as_json)
        return
    _wait_many(pdfs, root or Path.cwd(), since, timeout, as_json)


def _wait_one(pdf: Path, since: str, timeout: float | None, as_json: bool) -> None:
    from slidesonnet.review import ops

    try:
        cursor = int(since)
    except ValueError:
        raise click.BadParameter(
            "with one deck the cursor is the number the last wait printed", param_hint="--since"
        ) from None
    try:
        result = ops.wait(pdf, since=cursor, timeout=timeout)
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
        click.echo(_conv_line(conv))


def _wait_many(
    pdfs: tuple[Path, ...], root: Path, since: str, timeout: float | None, as_json: bool
) -> None:
    from slidesonnet.builds import working_pdf
    from slidesonnet.review import ops
    from slidesonnet.server.library import discover_decks

    try:
        cursor = ops.parse_cursor(since)
    except SlideSonnetError as exc:
        raise click.BadParameter(str(exc), param_hint="--since") from exc

    explicit = [working_pdf(p.resolve()) for p in pdfs]
    noted = False

    def find_decks() -> list[Path]:
        nonlocal noted
        if explicit:
            return explicit
        scan = discover_decks(root)
        if scan.truncated and not noted:
            click.echo(
                f"note: the deck scan stopped after {scan.visited} folders (at "
                f"{scan.stopped_at}); watching the {len(scan.decks)} decks found — "
                "pass a narrower --root to watch them all",
                err=True,
            )
        noted = True
        return [entry.pdf_path for entry in scan.decks]

    result = ops.wait_many(find_decks, since=cursor, timeout=timeout, rescan=WAIT_RESCAN_SECONDS)
    if result is None:
        click.echo("timed out", err=True)
        sys.exit(WAIT_TIMED_OUT)
    if as_json:
        data = {
            "cursor": result.cursor,
            "decks": [
                {
                    "pdf": _shown(news.pdf),
                    "awaiting_agent": [_conv_json(c) for c in news.awaiting_agent],
                }
                for news in result.decks
            ],
        }
        click.echo(json.dumps(data, indent=1, ensure_ascii=False))
        return
    for news in result.decks:
        click.echo(_shown(news.pdf))
        for conv in news.awaiting_agent:
            click.echo(_conv_line(conv))
    click.echo(f"cursor {result.cursor}")
