// The library's pure logic: filtering, grouping, and what a deck row says.
// (Ported from gui/library_view.py and gui/app.py::_filter_decks.)
import type { DeckStatsDTO, LibraryDTO, LibraryDeckDTO } from '@/api/client'

/**
 * Decks whose label contains every whitespace-separated term of `query`.
 *
 * Substring-per-term rather than fuzzy: with names as regular as
 * `lecture02_4_llm_basics_p1`, typing `02_4` or `llm` should mean exactly what
 * it looks like. Library order is preserved.
 */
export function filterDecks<T extends { label: string }>(decks: readonly T[], query: string): T[] {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return [...decks]
  return decks.filter((d) => terms.every((t) => d.label.toLowerCase().includes(t)))
}

export interface DisplayGroup {
  /** Heading for the group; `null` for the leading group of lone decks. */
  title: string | null
  decks: LibraryDeckDTO[]
}

/**
 * Sections as the page shows them.
 *
 * A folder holding two or more decks gets its own heading. Folders holding a
 * single deck would each become a heading over one card (the old library's
 * `basel-problem / basel-problem`), so they're gathered into one untitled
 * group shown first. Library order is kept inside every group.
 */
export function displayGroups(library: LibraryDTO, query = ''): DisplayGroup[] {
  const lone: LibraryDeckDTO[] = []
  const titled: DisplayGroup[] = []
  for (const section of library.sections) {
    const decks = filterDecks(section.decks, query)
    if (decks.length === 0) continue
    if (section.decks.length >= 2 && section.title !== '') {
      titled.push({ title: section.title, decks })
    } else {
      lone.push(...decks)
    }
  }
  return lone.length > 0 ? [{ title: null, decks: lone }, ...titled] : titled
}

/**
 * The part of a deck's path its heading and name don't already say.
 *
 * Decks usually live at `<section>/<name>/<name>.pdf`, where repeating the
 * folder under the name is noise; a deeper nesting or a folder named
 * differently from the deck is worth showing.
 */
export function subPath(deck: LibraryDeckDTO, underHeading: boolean): string {
  const redundant = new Set(['', deck.name, `${deck.section}/${deck.name}`])
  if (underHeading) redundant.add(deck.section)
  return redundant.has(deck.group) ? '' : deck.group
}

/** A deck row's size: `49 slides`, blank while unknown. */
export function sizeText(stats: DeckStatsDTO | 'error' | undefined): string {
  if (stats === undefined) return ''
  if (stats === 'error') return 'can’t be read'
  return `${stats.slides} slide${stats.slides === 1 ? '' : 's'}`
}

/** `3 decks` / `1 deck` / `no decks`. */
export function countText(n: number): string {
  return n === 0 ? 'no decks' : `${n} deck${n === 1 ? '' : 's'}`
}
