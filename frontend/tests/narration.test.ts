// The editor's block model: start/end silences split out of a speaking slide
// and written back around its cards. (Ported from test_gui_state.py's
// split_edge_silences / bracket_silences tests with the logic.)
import { describe, expect, it } from 'vitest'

import type { BlockDTO } from '@/api/client'
import { blockSegments, compose, decompose, editBlock, syncSilenceFields } from '@/features/editor/narration'

import { META } from './fakeServer'

const CUT = { kind: 'cut', seconds: 0 }
const speech = (text: string) => ({ kind: 'speech' as const, text, voice: null, pace: null, direction: null })
const pause = (seconds: number) => ({ kind: 'pause' as const, seconds })
const block = (segments: BlockDTO['segments']): BlockDTO => ({
  slide_id: 's', segments, transition_in: CUT, transition_out: CUT,
})
const DEFAULTS = { start: 0.3, end: 0.6 }

describe('edge silences', () => {
  it.each([
    // [segments, start, cards, end]
    [[pause(1), speech('hi'), pause(2)], 1, ['speech'], 2],
    [[speech('hi')], 0.3, ['speech'], 0.6], // implicit edges show the deck defaults
    [[speech('a'), pause(0.5), speech('b')], 0.3, ['speech', 'pause', 'speech'], 0.6],
    [[pause(1.5)], null, ['pause'], null], // a silent slide keeps its lone hold as a card
  ])('%j', (segments, start, cards, end) => {
    const b = editBlock('s', block(segments), CUT, DEFAULTS)
    expect([b.start, b.middle.map((m) => m.kind), b.end]).toEqual([start, cards, end])
  })

  it('writes the silences back explicitly around the cards, and round-trips', () => {
    const original = [pause(1), speech('hi'), pause(0.5), speech('there'), pause(2)]
    const b = editBlock('s', block(original), CUT, DEFAULTS)
    expect(blockSegments(b)).toEqual(original)
    // a slide that starts speaking gains its silence fields at the deck defaults
    const silent = editBlock('s', block([]), CUT, DEFAULTS)
    silent.middle.push({ key: 'k', kind: 'speech', text: 'now', voice: null, pace: 'normal', direction: ' ', seconds: 0 })
    syncSilenceFields(silent, DEFAULTS)
    expect(blockSegments(silent)).toEqual([pause(0.3), speech('now'), pause(0.6)]) // normal pace, blank note: unwritten
  })
})

describe('transition picker names', () => {
  it.each([
    ['wipeleft', 'wipe', 'Left'],
    ['crossfade', 'fade', null], // the legacy alias shows as Fade
    ['cut', 'cut', null],
  ])('%s ⇄ %s %s', (kind, family, direction) => {
    expect(decompose(META.transitions, META.aliases, kind)).toEqual({ family, direction })
    if (kind !== 'crossfade') expect(compose(META.transitions, family, direction)).toBe(kind)
  })

  it('falls back to a family’s first direction', () => {
    expect(compose(META.transitions, 'wipe', 'Sideways')).toBe('wipeleft')
  })
})
