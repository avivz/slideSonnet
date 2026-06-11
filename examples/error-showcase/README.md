# error-showcase — every reconciliation problem, one slide each

A deliberately broken deck for seeing how slideSonnet surfaces each error.
Open it in the editor:

```bash
slidesonnet edit examples/error-showcase/error-showcase.pdf
```

or run the checker:

```bash
slidesonnet check examples/error-showcase/error-showcase.pdf   # exits 1: 2 errors
```

| page | slide id | problem | where you see it in the editor |
|---|---|---|---|
| 1 | `all-good` | none — the control case | "no issues on this slide" |
| 2 | `auto-p2-s1` | frame has no `\ssid` | warning: auto-generated id; editing works, but name the slide in the source |
| 3 | `silent-stage` | named but never narrated | warning in checks; "no speech on this slide"; play says there's nothing to play |
| 4+5 | `twin`, `twin-2` | same `\ssid` on two pages | warning: page 5 is auto-renamed `twin-2` so each page stays narratable; give each its own `\ssid` (a real `twin-2` elsewhere would make it skip to `twin-3`) |
| 6 | `double-block` | two `@double-block` blocks in the sidecar | warning: the second block is auto-renamed `double-block-2` (its text is kept, not dropped) and lands in the tray; the slide keeps the first block and stays editable |
| — | `@ghost-slide` | narration block with no matching page | the "Unattached narration" tray: attach it to a slide or delete it |

The header pill counts the errors deck-wide (⛔ 2 — the two orphans,
`ghost-slide` and the disambiguated `double-block-2`). Warnings don't block
anything; errors fail `slidesonnet check` (exit 1).

Note: a duplicate `@id` in the sidecar no longer freezes saving. On load the
later block is renamed (`double-block` → `double-block-2`) so neither block's
text is lost, and the rename surfaces in the unattached-narration tray. Merge
the two `@blocks` in `error-showcase.narration` to resolve the warning.

Rebuild the PDF after editing the source:

```bash
cd examples/error-showcase && latexmk -pdf error-showcase.tex
```
