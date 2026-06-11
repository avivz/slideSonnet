"""Id-only reconciliation between a PDF's pages and a narration sidecar (§5).

The slide-id is the sole join key — no fingerprints. Checks for duplicate ids,
auto/unnamed ids, un-narrated pages, orphan narration, and order drift.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from slidesonnet.narration.model import PageNarration, Transition

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class Diagnostic:
    """One reconciliation finding."""

    severity: Severity
    code: str
    message: str
    slide_id: str | None = None


def diagnose(pages: list[str], blocks: list[PageNarration]) -> list[Diagnostic]:
    """Compare PDF page ids (*pages*, in order) with sidecar *blocks*.

    Returns findings ordered errors-first then by appearance.
    """
    diags: list[Diagnostic] = []

    real_pages = [p for p in pages if p]
    sidecar_ids = [b.slide_id for b in blocks]
    sidecar_counts = Counter(sidecar_ids)
    sidecar_set = set(sidecar_ids)
    page_set = set(real_pages)

    # Pages with no marker at all. slide_id "" keys them to the unmarked pages
    # themselves, so the editor can show the finding on the page it belongs to.
    for i, pid in enumerate(pages, start=1):
        if not pid:
            diags.append(
                Diagnostic(
                    "warning",
                    "unmarked-page",
                    f"page {i} has no slide-id marker (missing \\ssid)",
                    "",
                )
            )

    # Duplicate ids across PDF pages are disambiguated (renamed) upstream by
    # deck.dedupe_page_ids, which emits its own warnings — not re-checked here.

    # Duplicate id within the sidecar.
    for sid, n in sidecar_counts.items():
        if n >= 2:
            diags.append(
                Diagnostic(
                    "error",
                    "duplicate-block",
                    f"slide-id '{sid}' has {n} narration blocks in the sidecar",
                    sid,
                )
            )

    # auto-* ids on pages.
    for pid in dict.fromkeys(real_pages):
        if pid.startswith("auto-"):
            diags.append(
                Diagnostic(
                    "warning",
                    "auto-id",
                    f"slide-id '{pid}' is an auto-generated default — give it a real name",
                    pid,
                )
            )

    # Page id present, no sidecar block.
    for pid in dict.fromkeys(real_pages):
        if pid not in sidecar_set:
            diags.append(
                Diagnostic(
                    "warning",
                    "missing-narration",
                    f"slide '{pid}' has no narration block",
                    pid,
                )
            )

    # Sidecar block with no matching PDF page (orphan).
    for sid in dict.fromkeys(sidecar_ids):
        if sid not in page_set:
            diags.append(
                Diagnostic(
                    "error",
                    "orphan-narration",
                    f"narration block '{sid}' has no matching PDF page (removed/renamed?)",
                    sid,
                )
            )

    # Order drift: shared ids should appear in the same relative order.
    shared_in_pages = [p for p in real_pages if p in sidecar_set]
    shared_in_sidecar = [s for s in sidecar_ids if s in page_set]
    if shared_in_pages != shared_in_sidecar and set(shared_in_pages) == set(shared_in_sidecar):
        diags.append(
            Diagnostic(
                "info",
                "order-drift",
                "sidecar block order differs from PDF page order (save re-sorts to PDF order)",
            )
        )

    # Transition disagreement at a slide boundary (e.g. an LLM wrote both sides).
    by_id = {b.slide_id: b for b in blocks}
    for earlier, later in zip(real_pages, real_pages[1:], strict=False):
        prev_block, next_block = by_id.get(earlier), by_id.get(later)
        if prev_block is None or next_block is None:
            continue
        out_t, in_t = prev_block.transition_out, next_block.transition_in
        if in_t.kind != "cut" and (out_t.kind, out_t.seconds) != (in_t.kind, in_t.seconds):
            diags.append(
                Diagnostic(
                    "warning",
                    "transition-conflict",
                    f"transition out of '{earlier}' disagrees with transition into "
                    f"'{later}' — the earlier slide's transition wins",
                    earlier,
                )
            )

    return sort_diagnostics(diags)


def boundary_transition(
    prev_block: PageNarration | None, next_block: PageNarration | None
) -> Transition:
    """The effective transition between two consecutive slides.

    The earlier slide's ``transition_out`` wins; if it is a plain cut, the next
    slide's ``transition_in`` applies; absent any direction, the default is a
    cut. This keeps rendering well-defined even when the two sides disagree.
    """
    if prev_block is not None and prev_block.transition_out.kind != "cut":
        return prev_block.transition_out
    if next_block is not None and next_block.transition_in.kind != "cut":
        return next_block.transition_in
    return Transition()


def sort_diagnostics(diags: list[Diagnostic]) -> list[Diagnostic]:
    """Order findings errors-first, then warnings, then info (stable)."""
    severity_rank = {"error": 0, "warning": 1, "info": 2}
    return sorted(diags, key=lambda d: severity_rank[d.severity])


def has_errors(diags: list[Diagnostic]) -> bool:
    """True if any diagnostic is an error."""
    return any(d.severity == "error" for d in diags)


def count_by_severity(diags: list[Diagnostic]) -> dict[Severity, int]:
    """Tally diagnostics by severity."""
    counts: Counter[Severity] = Counter(d.severity for d in diags)
    return {"error": counts["error"], "warning": counts["warning"], "info": counts["info"]}
