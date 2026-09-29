import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PlaybackController, type Frame, type MediaLike, type Scheduler } from '@/features/playback/controller'
import { cueAt, cueStart, formatClock, formatLength, nextInScope } from '@/features/playback/cues'
import { StageOverlay } from '@/features/playback/dom'
import type { PreviewManifest } from '@/features/playback/manifest'
import { activeStep, effect, morphFrame } from '@/features/playback/morph'
import { OutputWaker } from '@/features/playback/wake'

const CUES = [
  { start: 0, slide_id: 'a' },
  { start: 4, slide_id: 'b' },
  { start: 7, slide_id: 'c' },
]

describe('playing the deck inside a chosen conversation', () => {
  const cues = [
    { start: 0, slide_id: 'a' }, { start: 3, slide_id: 'b' }, { start: 6, slide_id: 'c' }, { start: 9, slide_id: 'd' },
  ]
  const scope = new Set(['a', 'c'])
  it('jumps over a slide outside it to the next one inside, and ends after the last', () => {
    expect(nextInScope(cues, 'b', scope)).toBe(6) // b is out: on to c
    expect(nextInScope(cues, 'd', scope)).toBeNull() // nothing in scope after d: stop
  })
})

describe('cues', () => {
  it.each([
    [-1, 0], // before the first cue: the first slide
    [0, 0],
    [3.99, 0],
    [4, 1], // a frame exactly on a boundary belongs to the next slide
    [6.5, 1],
    [7, 2],
    [99, 2],
  ])('t=%d → cue %d', (t, index) => {
    expect(cueAt(CUES, t)).toBe(index)
  })

  it('handles no cues, cue lookup, and the clock', () => {
    expect(cueAt([], 3)).toBe(-1)
    expect(cueStart(CUES, 'b')).toBe(4)
    expect(cueStart(CUES, 'zz')).toBeNull()
    expect([0, 9.9, 65, 600].map(formatClock)).toEqual(['0:00', '0:09', '1:05', '10:00'])
    expect([3, 393.2, 3720].map(formatLength)).toEqual(['3 s', '6 min 33 s', '1 h 2 min'])
  })
})

describe('morph', () => {
  const step = { at: 4, dur: 1, kind: 'wipeleft', from: 'a.png', to: 'b.png' }

  it('is active from dur before the boundary until the boundary', () => {
    expect(activeStep([step], 2.9)).toBeNull()
    expect(activeStep([step], 3.5)?.progress).toBeCloseTo(0.5)
    expect(activeStep([step], 4)?.progress).toBe(1)
    expect(activeStep([step], 4.01)).toBeNull() // the overlay holds the incoming frame until the next is painted
  })

  it.each([
    ['crossfade', { t: 'fade' }],
    ['slideup', { t: 'slide', d: 'up' }],
    ['revealright', { t: 'reveal', d: 'right' }],
    ['fadeblack', { t: 'fadecolor', color: '#000' }],
    ['circleclose', { t: 'circle', d: 'close' }],
    ['something-new', { t: 'fade' }], // unknown kinds degrade to a fade
  ])('%s', (kind, expected) => {
    expect(effect(kind)).toEqual(expected)
  })

  it('computes layer styles per family', () => {
    expect(morphFrame(step, 0.25).b.clipPath).toBe('inset(0 0 0 75%)')
    const fade = morphFrame({ ...step, kind: 'fade' }, 0.4)
    expect([fade.a.opacity, fade.b.opacity]).toEqual([1, 0.4])
    const black = morphFrame({ ...step, kind: 'fadeblack' }, 0.75)
    expect([black.background, black.a.opacity, black.b.opacity]).toEqual(['#000', 0, 0.5])
    const reveal = morphFrame({ ...step, kind: 'revealleft' }, 0.5)
    expect([reveal.a.zIndex, reveal.b.zIndex, reveal.a.transform]).toEqual([2, 1, 'translateX(-50%)'])
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
    artifact_id: 'x', slide_id: null, narration_revision: 'r', pdf_revision: 'p', engine: 'kokoro',
    media_url: '/t.wav', duration: 10, start_at: 0, cues: CUES,
    pages: CUES.map((c) => ({ slide_id: c.slide_id, image_url: `/${c.slide_id}.png` })),
    transitions: [{ at: 4, dur: 0.5, kind: 'fade', from: '/a.png', to: '/b.png' }],
    speech: [],
    ...overrides,
  }
}

function setup() {
  const media = new FakeMedia()
  const scheduler = new ManualScheduler()
  const frames: Frame[] = []
  const slides: string[] = []
  const visibility = new EventTarget() as EventTarget & { hidden: boolean }
  visibility.hidden = false
  const controller = new PlaybackController(media, {
    scheduler,
    visibility: visibility as never,
    onFrame: (f) => frames.push(f),
    onSlide: (s) => slides.push(s),
  })
  return { media, scheduler, frames, slides, controller, visibility, last: () => frames.at(-1) as Frame }
}

describe('PlaybackController', () => {
  it('derives slide, image and transitions from the audio clock, reporting each slide once', async () => {
    const { media, scheduler, slides, controller, last } = setup()
    controller.load(manifest())
    controller.play()
    await Promise.resolve()
    for (const t of [1, 2, 3.6, 3.8, 4.1, 5, 6]) scheduler.frame(media, t)
    expect(slides).toEqual(['b']) // not the opening slide, not once per frame
    expect(last()).toMatchObject({ loaded: true, playing: true, slideId: 'b', imageUrl: '/b.png', morph: null })
    controller.load(manifest({ slide_id: 'b', cues: [{ start: 0, slide_id: 'b' }] }))
    expect(last().imageUrl).toBeNull() // a single-slide stage already shows its slide
    controller.load(manifest())
    scheduler.frame(media, 3.75)
    expect(last().morph?.b.opacity).toBeCloseTo(0.5) // mid-fade
    scheduler.frame(media, 8)
    expect(slides).toEqual(['b', 'a', 'c'])
  })

  it('seeks both ways, to a slide, and starts where the manifest says', () => {
    const { media, controller, slides, last } = setup()
    controller.load(manifest({ start_at: 4 }))
    expect(media.currentTime).toBe(4)
    expect(last().slideId).toBe('b')
    controller.seekToSlide('c')
    expect(media.currentTime).toBe(7)
    controller.seek(1)
    controller.seekFraction(0.5)
    expect(media.currentTime).toBe(5)
    expect(slides).toEqual(['c', 'a', 'b'])
    expect(controller.seekToSlide('nope')).toBe(false)
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
    loaded: true, playing: true, time: 30, duration: 100, slideId: 'a', imageUrl: '/a.png', morph: null,
    ...over,
  })

  it('the overlay holds the playing slide, marks transitions, and hides when unloaded', () => {
    const stage = document.createElement('div')
    const overlay = new StageOverlay(stage)
    overlay.render(frame({}))
    expect(overlay.root.classList.contains('ss-on')).toBe(true)
    expect(overlay.root.hasAttribute('data-morph')).toBe(false)
    expect(stage.querySelector('img')?.getAttribute('src')).toBe('/a.png')
    const step = { at: 1, dur: 1, kind: 'fade', from: '/a.png', to: '/b.png' }
    overlay.render(frame({ morph: morphFrame(step, 0.5) }))
    expect(overlay.root.hasAttribute('data-morph')).toBe(true)
    overlay.render(frame({ imageUrl: null })) // a single-slide preview between transitions
    expect(overlay.root.classList.contains('ss-on')).toBe(false)
    overlay.render(frame({ loaded: false }))
    expect(overlay.root.classList.contains('ss-on')).toBe(false)
  })

  describe('handing off after a transition', () => {
    // the browser decodes a picture on its own time: each img.decode() waits for the test
    const decoded = new Map<string, () => void>()
    const paint = async (src: string): Promise<void> => {
      decoded.get(new URL(src, location.href).href)?.()
      await flushPromises()
    }
    beforeEach(() => {
      decoded.clear()
      HTMLImageElement.prototype.decode = function (this: HTMLImageElement) {
        return new Promise<void>((resolve) => decoded.set(this.src, resolve))
      }
    })
    afterEach(() => {
      delete (HTMLImageElement.prototype as Partial<HTMLImageElement>).decode
    })
    const fade = { at: 1, dur: 1, kind: 'fade', from: '/a.png', to: '/b.png' }
    const layers = (stage: HTMLElement) =>
      [...stage.querySelectorAll<HTMLImageElement>('.ss-morph img')].map((img) => [img.getAttribute('src'), img.style.opacity])

    it('keeps the incoming slide up until the still picture is painted (Watch as video)', async () => {
      const stage = document.createElement('div')
      const overlay = new StageOverlay(stage)
      overlay.render(frame({ morph: morphFrame(fade, 1) })) // the fade has landed on b
      // the stage holds b in its live picture — another URL, not loaded yet
      overlay.render(frame({ slideId: 'b', imageUrl: '/b-live.png' }))
      expect(layers(stage)).toEqual([['/b-live.png', '1'], ['/b.png', '1']]) // b stays up over it
      await paint('/b-live.png')
      expect(layers(stage)).toEqual([['/b-live.png', '1'], ['/b-live.png', '0']]) // painted: handed off
      overlay.render(frame({ slideId: 'c', imageUrl: '/c.png' })) // a plain cut: nothing to hold
      expect(layers(stage)[1]).toEqual(['/c.png', '0'])
    })

    it('lifts off a single-slide preview only once the stage shows the slide', async () => {
      const stage = document.createElement('div')
      const under = document.createElement('img')
      under.src = '/b-stage.png'
      stage.append(under)
      const overlay = new StageOverlay(stage)
      overlay.render(frame({ imageUrl: null, morph: morphFrame(fade, 1) }))
      overlay.render(frame({ imageUrl: null })) // the transition is over
      expect(overlay.root.classList.contains('ss-on')).toBe(true) // the stage isn't painted yet
      expect(layers(stage)[1]).toEqual(['/b.png', '1'])
      await paint('/b-stage.png')
      expect(overlay.root.classList.contains('ss-on')).toBe(false)
    })
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
