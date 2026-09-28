// Play all: the deck slide by slide. Each slide plays its own track (its
// pauses, and its share of the transitions' time, already in it), so the next
// one can be prepared while this one plays. It plays the slides not greyed out:
// the chosen conversation's, or the whole deck's.

interface PageRef {
  slide_id: string
}
type Scope = ReadonlySet<string> | null

/** The slides Play all plays, in deck order (a page without an id can't be built). */
export function playable(pages: readonly PageRef[], scope: Scope): string[] {
  return pages.map((p) => p.slide_id).filter((id) => id !== '' && (scope === null || scope.has(id)))
}

/** Where Play all starts: here, or the first slide in play when here isn't one. */
export function startAt(pages: readonly PageRef[], scope: Scope, here: string): string | null {
  const slides = playable(pages, scope)
  return slides.includes(here) ? here : (slides[0] ?? null)
}

/** The slide after `slideId` (in play or not) that Play all plays next; null at the end. */
export function nextAfter(pages: readonly PageRef[], scope: Scope, slideId: string): string | null {
  const from = pages.findIndex((p) => p.slide_id === slideId)
  return playable(pages.slice(from + 1), scope)[0] ?? null
}

/** "Slide `at` of `of`" (at is 0 when the slide isn't in play). */
export function progress(pages: readonly PageRef[], scope: Scope, slideId: string): { at: number; of: number } {
  const slides = playable(pages, scope)
  return { at: slides.indexOf(slideId) + 1, of: slides.length }
}
