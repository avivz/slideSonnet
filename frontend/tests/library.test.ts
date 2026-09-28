import { describe, expect, it } from 'vitest'

import { cardStatus, countText, displayGroups, filterDecks, subPath } from '@/features/library/library'

import { deck, library } from './fixtures'

describe('filterDecks', () => {
  const decks = [deck('lecture02_4_llm_basics_p1'), deck('lecture10_prompting'), deck('Week9/LLM')]
  it.each([
    ['', 3],
    ['llm', 2],
    ['02_4', 1],
    ['LECTURE prompt', 1], // every term, case-insensitive
    ['nothing', 0],
  ])('%j matches %i', (query, n) => {
    expect(filterDecks(decks, query)).toHaveLength(n)
  })
})

describe('displayGroups', () => {
  it('gathers single-deck folders into one untitled group first', () => {
    const groups = displayGroups(library())
    expect(groups.map((g) => g.title)).toEqual([null, 'week02'])
    expect(groups[0]?.decks.map((d) => d.label)).toEqual(['overview', 'week01/intro/intro'])
  })

  it('filters inside groups and drops empty ones', () => {
    expect(displayGroups(library(), 'prompt').map((g) => [g.title, g.decks.length])).toEqual([
      ['week02', 1],
    ])
  })
})

describe('subPath', () => {
  it.each([
    ['week01/intro/intro', false, ''], // <section>/<name>/<name>.pdf: nothing to add
    ['week02/llm_basics', true, ''], // the heading already says week02
    ['week02/llm_basics', false, 'week02'], // …but not in the untitled group
    ['week02/labs/extra/deck', true, 'week02/labs/extra'],
  ])('%s (under heading: %s) → %j', (label, under, expected) => {
    expect(subPath(deck(label), under)).toBe(expected)
  })
})

describe('cardStatus', () => {
  const s = (slides: number, narrated: number, errors = 0) => ({
    token: 't', slides, narrated, errors, warnings: 0,
  })
  it.each([
    [undefined, '…', 'pending', null],
    ['error' as const, 'unreadable', 'bad', null],
    [s(49, 49), '49 slides · complete', 'ok', 1],
    [s(49, 38), '49 slides · 11 to narrate', 'partial', 38 / 49],
    [s(1, 0), '1 slide · 1 to narrate', 'partial', 0],
    [s(12, 12, 2), '12 slides · 2 errors', 'bad', 1],
  ])('%j', (stats, text, tone, progress) => {
    expect(cardStatus(stats)).toEqual({ text, tone, progress })
  })
})

it('countText', () => {
  expect([0, 1, 3].map(countText)).toEqual(['no decks', '1 deck', '3 decks'])
})
