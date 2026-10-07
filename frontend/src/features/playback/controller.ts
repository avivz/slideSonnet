// The browser-owned preview player. One <audio> element is the clock; the
// scrubber, the time label, and the word being spoken are all *derived* from
// its currentTime on each animation frame. Nothing ticks to the server.
//
// Because every frame is recomputed from currentTime, "resync" after a seek,
// pause, resume, rate change, or a hidden tab coming back is simply "render a
// frame now".
import type { PreviewManifest } from './manifest'

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
  /** The slide the audio is on. */
  slideId: string | null
  /**
   * The playing slide's picture, to hold over the stage while the editor is on
   * another slide; null when the stage shows it already.
   */
  imageUrl: string | null
}

export interface ControllerOptions {
  scheduler?: Scheduler
  visibility?: VisibilitySource
  /** Every derived frame (render it). */
  onFrame?: (frame: Frame) => void
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
}

const browserScheduler: Scheduler = {
  request: (cb) => requestAnimationFrame(cb),
  cancel: (h) => cancelAnimationFrame(h),
}

export class PlaybackController {
  private manifestValue: PreviewManifest | null = null
  private raf: number | null = null
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
   * pointed the media element at `manifest.media_url`).
   */
  load(manifest: PreviewManifest): number {
    this.generationValue++
    this.manifestValue = manifest
    this.applyRate()
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
    this.options.onFrame?.({
      loaded: true,
      playing: !this.media.paused,
      time: this.media.currentTime,
      duration: this.duration(),
      slideId: manifest.slide_id,
      imageUrl: null,
    })
  }
}
