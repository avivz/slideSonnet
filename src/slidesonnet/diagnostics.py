"""Id-only reconciliation between a PDF's pages and a narration sidecar (§5).

The slide-id is the sole join key — no fingerprints. Checks for duplicate ids,
auto/unnamed ids, un-narrated pages, orphan narration, and order drift.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from slidesonnet.narration.model import PageNarration

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
    page_counts = Counter(real_pages)
    sidecar_ids = [b.slide_id for b in blocks]
    sidecar_counts = Counter(sidecar_ids)
    sidecar_set = set(sidecar_ids)
    page_set = set(real_pages)

    # Pages with no marker at all.
    for i, pid in enumerate(pages, start=1):
        if not pid:
            diags.append(
                Diagnostic(
                    "warning",
                    "unmarked-page",
                    f"page {i} has no slide-id marker (missing \\ssid)",
                )
            )

    # Duplicate id across PDF pages.
    for pid, n in page_counts.items():
        if n >= 2:
            diags.append(
                Diagnostic(
                    "error",
                    "duplicate-id",
                    f"slide-id '{pid}' appears on {n} PDF pages — ambiguous binding",
                    pid,
                )
            )

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

    severity_rank = {"error": 0, "warning": 1, "info": 2}
    return sorted(diags, key=lambda d: severity_rank[d.severity])


def has_errors(diags: list[Diagnostic]) -> bool:
    """True if any diagnostic is an error."""
    return any(d.severity == "error" for d in diags)


def count_by_severity(diags: list[Diagnostic]) -> dict[Severity, int]:
    """Tally diagnostics by severity."""
    counts: Counter[Severity] = Counter(d.severity for d in diags)
    return {"error": counts["error"], "warning": counts["warning"], "info": counts["info"]}
