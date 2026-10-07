// "Press ? for shortcuts": the first few times the editor opens, until it's
// dismissed or ? has been used. Remembered in this browser only.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { HINT_OPENS, createShortcutHint } from '@/features/editor/shortcutHint'

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('the shortcuts hint', () => {
  it(`shows the first ${HINT_OPENS} times the editor opens, and not once dismissed`, () => {
    for (let i = 0; i < HINT_OPENS; i++) {
      const hint = createShortcutHint()
      hint.opened()
      expect(hint.shown.value).toBe(true)
    }
    const later = createShortcutHint()
    later.opened()
    expect(later.shown.value).toBe(false)

    localStorage.clear()
    const first = createShortcutHint()
    first.opened()
    first.done() // dismissed, or ? pressed
    expect(first.shown.value).toBe(false)
    const next = createShortcutHint()
    next.opened()
    expect(next.shown.value).toBe(false)
  })

  it('still works when the browser keeps nothing', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const hint = createShortcutHint()
    hint.opened()
    expect(hint.shown.value).toBe(true)
    hint.done()
    expect(hint.shown.value).toBe(false)
  })
})
