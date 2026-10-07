import { describe, expect, it } from 'vitest'

import { Transport } from '@/features/playback/transport'

describe('Transport', () => {
  it.each([
    // [setup, revision, expected]
    ['nothing loaded', 'r1', 'build'],
    ['loaded, playing', 'r1', 'pause'],
    ['loaded, paused', 'r1', 'resume'],
    ['loaded, playing', 'r2', 'pause'], // pausing never needs the new words
    ['loaded, paused', 'r2', 'refresh'], // the narration changed: rebuild, resume where it was
    ['building', 'r1', 'wait'], // a double-click never cancels its own build
  ] as const)('%s: press @%s → %s', (setup, revision, expected) => {
    const t = new Transport()
    if (setup.startsWith('loaded')) {
      t.loaded('r1')
      t.playing = setup.endsWith('playing')
    } else if (setup === 'building') {
      t.begin()
    }
    expect(t.pressAction(revision)).toBe(expected)
  })

  it('a newer request or a stop supersedes an in-flight build', () => {
    const t = new Transport()
    const first = t.begin()
    const second = t.begin()
    expect([t.mayStart(first), t.mayStart(second)]).toEqual([false, true])
    t.stop()
    expect(t.mayStart(second)).toBe(false)
    expect(t.hasTrack).toBe(false)
  })

  it('navigating jumps playback there, while loaded or still being built; idle, nothing', () => {
    const loaded = new Transport()
    loaded.loaded('r1')
    const building = new Transport()
    building.begin()
    expect([loaded.navAction(), building.navAction(), new Transport().navAction()]).toEqual(['jump', 'jump', 'none'])
  })
})
