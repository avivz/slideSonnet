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
| 6 | `double-block` | two `@double-block` blocks in the sidecar | error in checks; **saving is frozen** until you fix the file (a rewrite would silently drop one block's text) |
| — | `@ghost-slide` | narration block with no matching page | the "Unattached narration" tray: attach it to a slide or delete it |

The header pill counts the errors deck-wide (⛔ 2). Warnings don't block
anything; errors fail `slidesonnet check` (exit 1).

Note: while the duplicate `@double-block` pair exists, the editor deliberately
stops writing to the sidecar (you'll get one warning when it would have saved).
Delete one of the two blocks in `error-showcase.narration` to unfreeze.

Rebuild the PDF after editing the source:

```bash
cd examples/error-showcase && latexmk -pdf error-showcase.tex
```
