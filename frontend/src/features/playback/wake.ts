// Waking the sound output before the first word. Some outputs (Bluetooth
// headphones and speakers, above all) sleep when nothing plays and take the
// better part of a second to wake, swallowing a track's first words. So before
// playback starts from quiet, the page plays silence for a moment; while a track
// stays loaded the silence keeps playing, so a resume after a pause starts at once.

/** The slice of an AudioContext the waker drives (tests pass a fake). */
export interface OutputContext {
  readonly state: string
  resume(): Promise<void>
  close(): Promise<void>
}

/** A context that plays silence, or null where the browser has none. */
function silentContext(): OutputContext | null {
  if (typeof AudioContext === 'undefined') return null
  const ctx = new AudioContext()
  const silence = ctx.createConstantSource()
  silence.offset.value = 0
  silence.connect(ctx.destination)
  silence.start()
  return ctx
}

export class OutputWaker {
  private ctx: OutputContext | null = null

  constructor(
    private readonly create: () => OutputContext | null = silentContext,
    /** Seconds of silence before the first word. */
    private readonly lead = 0.8,
  ) {}

  /** Resolves once the output is awake: after the lead-in when it was quiet, at once when not. */
  async wake(): Promise<void> {
    if (this.ctx?.state === 'running') return
    try {
      this.ctx ??= this.create()
      if (this.ctx === null) return
      await this.ctx.resume()
    } catch {
      return // no sound output to wake: play anyway
    }
    await new Promise((done) => setTimeout(done, this.lead * 1000))
  }

  /** Playback is over: stop the silence and let the output sleep. */
  release(): void {
    const ctx = this.ctx
    this.ctx = null
    void ctx?.close().catch(() => undefined)
  }
}
