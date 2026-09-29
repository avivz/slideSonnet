import { describe, expect, it } from 'vitest'

import { spanAt, voicedFraction, wordAt } from '@/features/playback/words'

describe('the spoken word, estimated', () => {
  const text = 'Now change one behaviour.'
  const word = (f: number): string => {
    const r = wordAt(text, f)
    return r ? text.slice(r[0], r[1]) : ''
  }

  it('walks the words in proportion to their length', () => {
    expect(word(0)).toBe('Now')
    expect(word(0.2)).toBe('change')
    expect(word(0.45)).toBe('one')
    expect(word(0.99)).toBe('behaviour.')
    expect(word(1)).toBe('behaviour.') // the very end still marks the last word
  })

  it('marks a pronunciation fix as the word it shows, weighed by that word', () => {
    const fixed = 'Ask [Leonhard Euler](/ˈleɪɒnhɑːrt/ /ˈɔɪlər/) now'
    const at = (f: number): string => {
      const r = wordAt(fixed, f)
      return r ? fixed.slice(r[0], r[1]) : ''
    }
    expect(at(0.5)).toBe('[Leonhard Euler](/ˈleɪɒnhɑːrt/ /ˈɔɪlər/)') // one word, not five pieces
    expect(at(0.9)).toBe('now') // its IPA doesn't stretch its share of the time
  })

  it('has nothing to mark in an empty line', () => {
    expect(wordAt('   ', 0.5)).toBeNull()
  })

  it('finds the utterance playing at a time, and none in a pause', () => {
    const spans = [
      { slide_id: 'a', index: 0, start: 0.3, end: 2.0, silences: [] },
      { slide_id: 'a', index: 1, start: 2.5, end: 4.0, silences: [] },
    ]
    expect(spanAt(spans, 1.0)).toMatchObject({ index: 0 })
    expect(spanAt(spans, 2.2)).toBeNull() // the pause between the lines
    expect(spanAt(spans, 3.9)).toMatchObject({ index: 1 })
    expect(spanAt(spans, 4.5)).toBeNull()
  })

  it('advances only while the voice speaks: pauses and the silent tail hold', () => {
    // 0-4 s span: voiced 0-1, a breath 1-2, voiced 2-3, a silent tail 3-4
    const span = { slide_id: 'a', index: 0, start: 0, end: 4, silences: [[1, 2], [3, 4]] as [number, number][] }
    expect(voicedFraction(span, 0.5)).toBeCloseTo(0.25)
    expect(voicedFraction(span, 1.5)).toBeCloseTo(0.5) // holds through the breath
    expect(voicedFraction(span, 2.5)).toBeCloseTo(0.75)
    expect(voicedFraction(span, 3.2)).toBe(1) // the words are done when the voice is
  })
})
