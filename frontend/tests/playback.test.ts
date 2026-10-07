import { describe, expect, it, vi } from 'vitest'

import { PlaybackController, type Frame, type MediaLike, type Scheduler } from '@/features/playback/controller'
import { formatClock, formatLength } from '@/features/playback/clock'
import { StageOverlay } from '@/features/playback/dom'
import type { PreviewManifest } from '@/features/playback/manifest'
import { OutputWaker } from '@/features/playback/wake'

describe('the clock', () => {
  it('reads a position as m:ss and a length in words', () => {
    expect([0, 9.9, 65, 600].map(formatClock)).toEqual(['0:00', '0:09', '1:05', '10:00'])
    expect([3, 393.2, 3720].map(formatLength)).toEqual(['3 s', '6 min 33 s', '1 h 2 min'])
  })
})

class FakeMedia implements MediaLike {
  currentTime = 0
  duration = 10
  paused = true
  playbackRate = 1
  defaultPlaybackRate = 1
  preservesPitch = false
  listeners = new Map<string, Set<() => void>>()
  play = vi.fn(async () => {
    this.paused = false
    this.fire('play')
  })
  pause = vi.fn(() => {
    this.paused = true
    this.fire('pause')
  })
  addEventListener(type: string, l: () => void): void {
    this.listeners.set(type, (this.listeners.get(type) ?? new Set()).add(l))
  }
  removeEventListener(type: string, l: () => void): void {
    this.listeners.get(type)?.delete(l)
  }
  fire(type: string): void {
    for (const l of this.listeners.get(type) ?? []) l()
  }
  listenerCount(): number {
    return [...this.listeners.values()].reduce((n, s) => n + s.size, 0)
  }
}

class ManualScheduler implements Scheduler {
  private next = 1
  pending = new Map<number, () => void>()
  request(cb: () => void): number {
    const id = this.next++
    this.pending.set(id, cb)
    return id
  }
  cancel(id: number): void {
    this.pending.delete(id)
  }
  /** Advance the media clock and run one animation frame. */
  frame(media: FakeMedia, t: number): void {
    media.currentTime = t
    const callbacks = [...this.pending.values()]
    this.pending.clear()
    for (const cb of callbacks) cb()
  }
}

function manifest(overrides: Partial<PreviewManifest> = {}): PreviewManifest {
  return {
    artifact_id: 'x', slide_id: 'a', narration_revision: 'r', pdf_revision: 'p', engine: 'kokoro',
    media_url: '/t.wav', duration: 10, speech: [],
    ...overrides,
  }
}

function setup() {
  const media = new FakeMedia()
  const scheduler = new ManualScheduler()
  const frames: Frame[] = []
  const visibility = new EventTarget() as EventTarget & { hidden: boolean }
  visibility.hidden = false
  const controller = new PlaybackController(media, {
    scheduler,
    visibility: visibility as never,
    onFrame: (f) => frames.push(f),
  })
  return { media, scheduler, frames, controller, visibility, last: () => frames.at(-1) as Frame }
}

describe('PlaybackController', () => {
  it('derives each frame from the audio clock, and seeks both ways', async () => {
    const { media, scheduler, controller, last } = setup()
    controller.load(manifest())
    controller.play()
    await Promise.resolve()
    scheduler.frame(media, 3)
    expect(last()).toMatchObject({ loaded: true, playing: true, time: 3, duration: 10, slideId: 'a', imageUrl: null })
    controller.seek(1)
    expect(media.currentTime).toBe(1)
    controller.seekFraction(0.5)
    expect(media.currentTime).toBe(5)
    controller.seek(99)
    expect(media.currentTime).toBe(10) // never past the end
  })

  it('pins the rate across loads, pitch preserved', () => {
    const { media, controller } = setup()
    controller.setRate(1.5)
    controller.load(manifest())
    expect([media.playbackRate, media.defaultPlaybackRate, media.preservesPitch]).toEqual([1.5, 1.5, true])
  })

  it('pauses, resumes and stops without a stale start', async () => {
    const { media, scheduler, controller, last } = setup()
    const gen = controller.load(manifest())
    controller.play()
    await Promise.resolve()
    controller.pause()
    expect(last().playing).toBe(false)
    expect(scheduler.pending.size).toBe(0) // no frame loop while paused
    controller.stop()
    expect(last().loaded).toBe(false)
    media.play.mockClear()
    controller.play(gen) // a play for the superseded track never starts
    controller.play() // …and with nothing loaded, nothing plays
    expect(media.play).not.toHaveBeenCalled()
  })

  it('re-renders when a hidden tab comes back, and detaches on dispose', () => {
    const { media, frames, controller, visibility } = setup()
    controller.load(manifest())
    const before = frames.length
    visibility.hidden = true
    visibility.dispatchEvent(new Event('visibilitychange'))
    visibility.hidden = false
    visibility.dispatchEvent(new Event('visibilitychange'))
    expect(frames.length).toBe(before + 1)
    controller.dispose()
    expect(media.listenerCount()).toBe(0)
  })
})

describe('DOM views', () => {
  const frame = (over: Partial<Frame>): Frame => ({
    loaded: true, playing: true, time: 30, duration: 100, slideId: 'a', imageUrl: '/a.png', ...over,
  })

  it('the overlay holds the playing slide over the stage, and hides when there is none', () => {
    const stage = document.createElement('div')
    const overlay = new StageOverlay(stage)
    overlay.render(frame({}))
    expect(overlay.root.classList.contains('ss-on')).toBe(true)
    expect(stage.querySelector('img')?.getAttribute('src')).toBe('/a.png')
    overlay.render(frame({ imageUrl: null })) // the stage shows the playing slide itself
    expect(overlay.root.classList.contains('ss-on')).toBe(false)
    overlay.render(frame({}))
    overlay.render(frame({ loaded: false }))
    expect(overlay.root.classList.contains('ss-on')).toBe(false)
    expect(new StageOverlay(stage).root).not.toBe(overlay.root) // a new one replaces the old
    expect(stage.children).toHaveLength(1)
  })
})

describe('waking the sound output before the first word', () => {
  function fakeContext() {
    const ctx = { state: 'suspended', closed: false, resume: vi.fn(async () => { ctx.state = 'running' }), close: vi.fn(async () => { ctx.closed = true }) }
    return ctx
  }
  it('holds the first start for the lead-in, starts at once while awake, and lets go on stop', async () => {
    vi.useFakeTimers()
    const made: ReturnType<typeof fakeContext>[] = []
    const waker = new OutputWaker(() => { const c = fakeContext(); made.push(c); return c }, 0.8)
    let started = false
    void waker.wake().then(() => { started = true })
    await vi.advanceTimersByTimeAsync(700)
    expect(started).toBe(false) // a sleeping device would swallow these first words
    await vi.advanceTimersByTimeAsync(200)
    expect(started).toBe(true)
    await waker.wake() // already awake (a resume after pause): no second wait
    expect(made).toHaveLength(1)
    waker.release()
    expect(made[0]?.closed).toBe(true)
    vi.useRealTimers()
  })
  it('never stands in the way where the browser has no audio context', async () => {
    await new OutputWaker(() => null, 0.8).wake()
  })
})
