import { describe, expect, it } from 'vitest'

import { Transport } from '@/features/playback/transport'

describe('Transport', () => {
  it.each([
    // [setup, key, revision, expected]
    ['nothing loaded', 'a', 'r1', 'build'],
    ['a loaded, playing', 'a', 'r1', 'pause'],
    ['a loaded, paused', 'a', 'r1', 'resume'],
    ['a loaded, playing', 'deck', 'r1', 'build'], // a different track
    ['a loaded, playing', 'a', 'r2', 'pause'], // pausing never needs the new words
    ['a loaded, paused', 'a', 'r2', 'refresh'], // the narration changed: rebuild, resume where it was
    ['a building', 'a', 'r1', 'wait'], // a double-click never cancels its own build
    ['deck loaded, playing', 'deck', 'r2', 'pause'],
  ] as const)('%s: press %s @%s → %s', (setup, key, revision, expected) => {
    const t = new Transport()
    if (setup.startsWith('deck loaded')) {
      t.loaded('deck', 'r1')
      t.playing = true
    } else if (setup.startsWith('a loaded')) {
      t.loaded('a', 'r1')
      t.playing = setup.endsWith('playing')
    } else if (setup === 'a building') {
      t.begin('a')
    }
    expect(t.pressAction(key, revision)).toBe(expected)
  })

  it('a newer request or a stop supersedes an in-flight build', () => {
    const t = new Transport()
    const first = t.begin('a')
    const second = t.begin('deck')
    expect([t.mayStart(first), t.mayStart(second)]).toEqual([false, true])
    t.stop()
    expect(t.mayStart(second)).toBe(false)
    expect(t.loadedKey).toBeNull()
  })

  it.each([
    ['deck', 'jump'], // Play all goes on from the slide chosen
    ['video', 'seek'], // the whole-deck track spans every slide
    ['a', 'clear'],
    [null, 'none'],
  ] as const)('navigating with %s loaded → %s', (key, expected) => {
    const t = new Transport()
    if (key !== null) t.loaded(key, 'r1')
    expect(t.navAction()).toBe(expected)
    if (key !== null) {
      const pending = new Transport()
      pending.begin(key) // same rule while it is still being built
      expect(pending.navAction()).toBe(expected)
    }
  })
})
