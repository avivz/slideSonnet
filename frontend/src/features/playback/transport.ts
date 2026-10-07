// What the Play and Stop buttons and slide navigation do to the preview player —
// the defined behaviors, independent of any audio element. (Ported from the
// NiceGUI editor's PlaybackController.)
//
// - Play toggles: with a track loaded it pauses or resumes; resuming a track the
//   narration has changed since is a 'refresh' (rebuild it, go on from where it
//   was); with nothing loaded it starts playing.
// - A new request supersedes whatever is rolling; the superseded build never starts.
// - Stop cancels a request still being built, and unloads the player.
// - Playback goes slide by slide: navigating while it plays (or gets ready)
//   jumps it to the slide chosen.

export class Transport {
  private generation = 0
  playing = false
  /** A track is in the player, playing or paused. */
  hasTrack = false
  /** The narration revision the loaded track was built from. */
  loadedRevision: string | null = null
  /** A track is being prepared. */
  pending = false

  /** Register a new play request; returns its token. */
  begin(): number {
    this.generation++
    this.pending = true
    return this.generation
  }

  /** True if no stop or newer request arrived since `token` was issued. */
  mayStart(token: number): boolean {
    return token === this.generation
  }

  loaded(revision: string): void {
    this.hasTrack = true
    this.loadedRevision = revision
    this.pending = false
  }

  unload(): void {
    this.hasTrack = false
    this.loadedRevision = null
    this.playing = false
    this.pending = false
  }

  stop(): void {
    this.generation++
    this.unload()
  }

  /** What a Play press should do, given the deck's current revision. */
  pressAction(revision: string): 'build' | 'pause' | 'resume' | 'refresh' | 'wait' {
    if (this.pending) return 'wait' // a double-click doesn't cancel its own build
    if (!this.hasTrack) return 'build'
    if (this.playing) return 'pause' // pausing never needs the new words
    return this.loadedRevision === revision ? 'resume' : 'refresh'
  }

  /** What moving to another slide should do to the player right now. */
  navAction(): 'jump' | 'none' {
    return this.hasTrack || this.pending ? 'jump' : 'none'
  }
}
