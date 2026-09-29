// Transition effects for the preview: a browser-side approximation of the
// exported FFmpeg xfade (fade/wipe/slide/cover/reveal/circle), computed as pure
// data so it is testable without a DOM. Each morph *completes* at its boundary,
// matching the export's absorb-into-hold timing. (Ported from the NiceGUI
// editor's static/morph.html.)
import type { MorphStep } from './manifest'

export type Direction = 'left' | 'right' | 'up' | 'down'

export type Effect =
  | { t: 'fade' }
  | { t: 'fadecolor'; color: string }
  | { t: 'wipe' | 'slide' | 'cover' | 'reveal'; d: Direction }
  | { t: 'circle'; d: 'open' | 'close' }

const FAMILIES = ['wipe', 'slide', 'cover', 'reveal'] as const

function direction(raw: string): Direction {
  return raw === 'left' || raw === 'right' || raw === 'up' ? raw : 'down'
}

export function effect(kind: string): Effect {
  if (kind === 'fade' || kind === 'dissolve' || kind === 'crossfade') return { t: 'fade' }
  for (const family of FAMILIES) {
    if (kind.startsWith(family)) return { t: family, d: direction(kind.slice(family.length)) }
  }
  if (kind === 'fadeblack') return { t: 'fadecolor', color: '#000' }
  if (kind === 'fadewhite') return { t: 'fadecolor', color: '#fff' }
  if (kind === 'circleopen') return { t: 'circle', d: 'open' }
  if (kind === 'circleclose') return { t: 'circle', d: 'close' }
  return { t: 'fade' }
}

/**
 * The step animating at time `t` and its progress 0..1, or null when none is.
 * Past its boundary a step is done: the overlay (dom.ts) keeps the incoming
 * frame up until the picture that follows it is painted — no fixed grace.
 */
export function activeStep(
  steps: readonly MorphStep[],
  t: number,
): { step: MorphStep; progress: number } | null {
  for (const step of steps) {
    if (t >= step.at - step.dur && t <= step.at) {
      const raw = (t - (step.at - step.dur)) / step.dur
      return { step, progress: Math.min(1, Math.max(0, raw)) }
    }
  }
  return null
}

export interface LayerStyle {
  /** Image to show, or null for a solid black frame (no neighbour slide). */
  src: string | null
  opacity: number
  transform: string
  clipPath: string
  zIndex: number
}

export interface MorphFrame {
  /** Outgoing slide. */
  a: LayerStyle
  /** Incoming slide. */
  b: LayerStyle
  /** Colour behind both layers (fade-through-black/white), or '' for none. */
  background: string
}

// incoming layer revealed from an edge via a shrinking inset (top right bottom left)
function wipeClip(d: Direction, p: number): string {
  const off = (1 - p) * 100
  if (d === 'left') return `inset(0 0 0 ${off}%)` // grows right → left
  if (d === 'right') return `inset(0 ${off}% 0 0)` // grows left → right
  if (d === 'up') return `inset(${off}% 0 0 0)` // grows bottom → up
  return `inset(0 0 ${off}% 0)` // down: top → bottom
}

// incoming slides in from an edge
function enter(d: Direction, p: number): string {
  const off = (1 - p) * 100
  if (d === 'left') return `translateX(${off}%)`
  if (d === 'right') return `translateX(${-off}%)`
  if (d === 'up') return `translateY(${off}%)`
  return `translateY(${-off}%)`
}

// outgoing pushed/pulled the way the incoming travels (slide & reveal)
function exit(d: Direction, p: number): string {
  const off = p * 100
  if (d === 'left') return `translateX(${-off}%)`
  if (d === 'right') return `translateX(${off}%)`
  if (d === 'up') return `translateY(${-off}%)`
  return `translateY(${off}%)`
}

/** Layer styles for `step` at progress `p` (0 = all outgoing, 1 = all incoming). */
export function morphFrame(step: MorphStep, p: number): MorphFrame {
  const a: LayerStyle = { src: step.from, opacity: 1, transform: '', clipPath: '', zIndex: 1 }
  const b: LayerStyle = { src: step.to, opacity: 1, transform: '', clipPath: '', zIndex: 2 }
  let background = ''
  const e = effect(step.kind)
  switch (e.t) {
    case 'fade':
      b.opacity = p
      break
    case 'fadecolor':
      // fade the outgoing down to the colour by mid-point, then the incoming up
      background = e.color
      a.opacity = Math.max(0, 1 - 2 * p)
      b.opacity = Math.max(0, 2 * p - 1)
      break
    case 'wipe':
      b.clipPath = wipeClip(e.d, p)
      break
    case 'cover':
      b.transform = enter(e.d, p)
      break
    case 'slide':
      b.transform = enter(e.d, p)
      a.transform = exit(e.d, p)
      break
    case 'reveal':
      b.zIndex = 1 // the incoming sits beneath
      a.zIndex = 2
      a.transform = exit(e.d, p)
      break
    case 'circle':
      if (e.d === 'open') {
        b.clipPath = `circle(${p * 75}% at 50% 50%)`
      } else {
        b.zIndex = 1
        a.zIndex = 2
        a.clipPath = `circle(${(1 - p) * 75}% at 50% 50%)`
      }
      break
  }
  return { a, b, background }
}
