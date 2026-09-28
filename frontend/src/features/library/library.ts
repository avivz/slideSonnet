// The library's pure logic: filtering, grouping, and what a card says.
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

export type Tone = 'ok' | 'partial' | 'bad' | 'pending'

export interface CardStatus {
  text: string
  tone: Tone
  /** 0..1 share of slides with narration, or `null` while unknown. */
  progress: number | null
}

/** What a deck card's status line says: size first, then what's left. */
export function cardStatus(stats: DeckStatsDTO | 'error' | undefined): CardStatus {
  if (stats === undefined) return { text: '…', tone: 'pending', progress: null }
  if (stats === 'error') return { text: 'unreadable', tone: 'bad', progress: null }
  const slides = `${stats.slides} slide${stats.slides === 1 ? '' : 's'}`
  const progress = stats.slides > 0 ? Math.min(1, stats.narrated / stats.slides) : 0
  if (stats.errors > 0) {
    return { text: `${slides} · ${stats.errors} error${stats.errors === 1 ? '' : 's'}`, tone: 'bad', progress }
  }
  const complete = stats.slides > 0 && stats.narrated >= stats.slides
  if (complete) return { text: `${slides} · complete`, tone: 'ok', progress }
  return { text: `${slides} · ${stats.slides - stats.narrated} to narrate`, tone: 'partial', progress }
}

/** `3 decks` / `1 deck` / `no decks`. */
export function countText(n: number): string {
  return n === 0 ? 'no decks' : `${n} deck${n === 1 ? '' : 's'}`
}
