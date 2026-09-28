// The browser-owned preview player. One <audio> element is the clock; the
// slide shown, the transition overlay, the scrubber, and the time label are
// all *derived* from its currentTime on each animation frame. Nothing ticks to
// the server: the only thing reported outward is a change of playing slide
// (once per slide, not per frame), so an editor can follow along.
//
// Because every frame is recomputed from currentTime, "resync" after a seek,
// pause, resume, rate change, or a hidden tab coming back is simply "render a
// frame now".
import { cueAt, cueStart } from './cues'
import type { PreviewManifest } from './manifest'
import { activeStep, morphFrame, type MorphFrame } from './morph'

/** The slice of HTMLMediaElement the controller drives (tests pass a fake). */
export interface MediaLike {
  currentTime: number
  readonly duration: number
  readonly paused: boolean
  playbackRate: number
  defaultPlaybackRate: number
  preservesPitch?: boolean
  play(): Promise<void>
  pause(): void
  addEventListener(type: string, listener: () => void): void
  removeEventListener(type: string, listener: () => void): void
}

export interface Scheduler {
  request(callback: () => void): number
  cancel(handle: number): void
}

export interface VisibilitySource {
  readonly hidden: boolean
  addEventListener(type: 'visibilitychange', listener: () => void): void
  removeEventListener(type: 'visibilitychange', listener: () => void): void
}

export interface Frame {
  loaded: boolean
  playing: boolean
  time: number
  duration: number
  /** The slide the audio is on (deck previews move through many). */
  slideId: string | null
  /**
   * The page image to hold on the stage between transitions — deck previews
   * only (a single-slide preview's stage already shows its slide).
   */
  imageUrl: string | null
  /** The transition drawing right now, if any. */
  morph: MorphFrame | null
}

export interface ControllerOptions {
  scheduler?: Scheduler
  visibility?: VisibilitySource
  /** Every derived frame (render it). */
  onFrame?: (frame: Frame) => void
  /** The playing slide changed. Fired once per change, never per frame. */
  onSlide?: (slideId: string) => void
  /** The loaded track played to its end. */
  onEnded?: () => void
}

const MEDIA_EVENTS = ['play', 'pause', 'seeked', 'ratechange', 'ended', 'loadedmetadata'] as const

const EMPTY: Frame = {
  loaded: false,
  playing: false,
  time: 0,
  duration: 0,
  slideId: null,
  imageUrl: null,
  morph: null,
}

const browserScheduler: Scheduler = {
  request: (cb) => requestAnimationFrame(cb),
  cancel: (h) => cancelAnimationFrame(h),
}

export class PlaybackController {
  private manifestValue: PreviewManifest | null = null
  private images = new Map<string, string | null>()
  private raf: number | null = null
  private lastSlide: string | null = null
  private generationValue = 0
  private rate = 1
  private readonly scheduler: Scheduler
  private readonly visibility: VisibilitySource | undefined
  private readonly onMediaEvent = (): void => this.sync()
  private readonly onMediaEnded = (): void => {
    if (this.manifestValue !== null) this.options.onEnded?.()
  }
  private readonly onVisibility = (): void => {
    if (!this.visibility?.hidden) this.sync()
  }

  constructor(
    private readonly media: MediaLike,
    private readonly options: ControllerOptions = {},
  ) {
    this.scheduler = options.scheduler ?? browserScheduler
    this.visibility = options.visibility ?? (typeof document === 'undefined' ? undefined : document)
    for (const type of MEDIA_EVENTS) media.addEventListener(type, this.onMediaEvent)
    media.addEventListener('ended', this.onMediaEnded)
    this.visibility?.addEventListener('visibilitychange', this.onVisibility)
  }

  get manifest(): PreviewManifest | null {
    return this.manifestValue
  }

  /** Bumped by every load and stop; a caller holding an older value is stale. */
  get generation(): number {
    return this.generationValue
  }

  /**
   * Take over a freshly loaded track described by `manifest` (the caller has
   * pointed the media element at `manifest.media_url`). Seeks to `start_at`.
   */
  load(manifest: PreviewManifest): number {
    this.generationValue++
    this.manifestValue = manifest
    this.images = new Map(manifest.pages.map((p) => [p.slide_id, p.image_url]))
    this.lastSlide = null
    this.applyRate()
    if (manifest.start_at > 0) this.media.currentTime = manifest.start_at
    this.sync()
    return this.generationValue
  }

  /** Start (or resume) — only if `generation` is still current when given. */
  play(generation?: number): void {
    if (generation !== undefined && generation !== this.generationValue) return
    if (this.manifestValue === null) return
    this.media.play().catch(() => {
      // autoplay refused or the source changed underneath: stay paused
    })
  }

  pause(): void {
    this.media.pause()
  }

  /** Unload: pause, forget the track, clear every visual. Supersedes pending plays. */
  stop(): void {
    this.generationValue++
    this.media.pause()
    this.manifestValue = null
    this.images.clear()
    this.lastSlide = null
    this.cancelLoop()
    this.options.onFrame?.(EMPTY)
  }

  seek(seconds: number): void {
    if (this.manifestValue === null) return
    this.media.currentTime = Math.min(Math.max(0, seconds), this.duration())
    this.sync()
  }

  seekFraction(fraction: number): void {
    this.seek(fraction * this.duration())
  }

  /** Jump the deck track to `slideId`'s cue; false when it isn't in this track. */
  seekToSlide(slideId: string): boolean {
    const start = this.manifestValue ? cueStart(this.manifestValue.cues, slideId) : null
    if (start === null) return false
    this.seek(start)
    return true
  }

  /** Preview-only rate (never re-synthesizes); kept across loads, pitch preserved. */
  setRate(rate: number): void {
    this.rate = rate
    this.applyRate()
  }

  /** Detach every listener and stop the frame loop. */
  dispose(): void {
    this.cancelLoop()
    for (const type of MEDIA_EVENTS) this.media.removeEventListener(type, this.onMediaEvent)
    this.media.removeEventListener('ended', this.onMediaEnded)
    this.visibility?.removeEventListener('visibilitychange', this.onVisibility)
  }

  /** Render one frame from the media clock now, and keep looping while playing. */
  sync(): void {
    this.render()
    if (!this.media.paused && this.manifestValue !== null) this.ensureLoop()
    else this.cancelLoop()
  }

  // ---- internals ----------------------------------------------------------
  private duration(): number {
    const fromMedia = this.media.duration
    return Number.isFinite(fromMedia) && fromMedia > 0
      ? fromMedia
      : (this.manifestValue?.duration ?? 0)
  }

  private applyRate(): void {
    this.media.preservesPitch = true
    // a new source resets playbackRate to the default: pin both
    this.media.defaultPlaybackRate = this.rate
    this.media.playbackRate = this.rate
  }

  private ensureLoop(): void {
    if (this.raf !== null) return
    const tick = (): void => {
      this.raf = null
      this.sync()
    }
    this.raf = this.scheduler.request(tick)
  }

  private cancelLoop(): void {
    if (this.raf !== null) {
      this.scheduler.cancel(this.raf)
      this.raf = null
    }
  }

  private render(): void {
    const manifest = this.manifestValue
    if (manifest === null) {
      this.options.onFrame?.(EMPTY)
      return
    }
    const time = this.media.currentTime
    const index = cueAt(manifest.cues, time)
    const slideId = index >= 0 ? (manifest.cues[index]?.slide_id ?? null) : manifest.slide_id
    const active = activeStep(manifest.transitions, time)
    if (slideId !== null && slideId !== this.lastSlide) {
      const first = this.lastSlide === null
      this.lastSlide = slideId
      if (!first) this.options.onSlide?.(slideId)
    }
    this.options.onFrame?.({
      loaded: true,
      playing: !this.media.paused,
      time,
      duration: this.duration(),
      slideId,
      imageUrl:
        manifest.slide_id === null && slideId !== null ? (this.images.get(slideId) ?? null) : null,
      morph: active ? morphFrame(active.step, active.progress) : null,
    })
  }
}
