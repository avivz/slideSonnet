import type { Cue } from './manifest'

/**
 * Index of the cue playing at time `t` (seconds): the last cue whose start is
 * at or before `t`. Before the first cue, the first one. -1 for no cues.
 * Binary search, so a 200-slide deck costs nothing per animation frame.
 */
export function cueAt(cues: readonly Cue[], t: number): number {
  if (cues.length === 0) return -1
  let lo = 0
  let hi = cues.length - 1
  const time = t + 1e-6 // a frame landing exactly on a boundary belongs to the next slide
  if (time < (cues[0] as Cue).start) return 0
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if ((cues[mid] as Cue).start <= time) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** Start time of `slideId` in the cue sheet, or null when it isn't in it. */
export function cueStart(cues: readonly Cue[], slideId: string): number | null {
  const cue = cues.find((c) => c.slide_id === slideId)
  return cue ? cue.start : null
}

/**
 * The deck track reached `slideId`, outside the chosen conversation's slides
 * (`scope`): the start of the next slide inside it, or null when none is left.
 */
export function nextInScope(cues: readonly Cue[], slideId: string, scope: ReadonlySet<string>): number | null {
  const here = cues.findIndex((c) => c.slide_id === slideId)
  const next = cues.slice(here + 1).find((c) => scope.has(c.slide_id))
  return next ? next.start : null
}

/** `m:ss` for a playback position. */
export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** A video's length in words: "42 s", "6 min 33 s", "1 h 2 min". */
export function formatLength(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s} s`
  if (s < 3600) return `${Math.floor(s / 60)} min ${s % 60} s`
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`
}
