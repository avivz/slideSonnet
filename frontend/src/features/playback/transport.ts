// What the play/stop buttons and slide navigation do to the preview player —
// the defined behaviors, independent of any audio element. (Ported from the
// NiceGUI editor's PlaybackController.)
//
// - A play button toggles: pressed for the loaded, up-to-date track it pauses or
//   resumes; pressed for anything else (or a stale track) it builds that track.
// - A new request supersedes whatever is rolling; the superseded build never starts.
// - Stop cancels a request still being built, and unloads the player.
// - A single-slide track belongs to its slide: navigating away clears it. The
//   whole-deck track ('video') spans every slide: navigating seeks it, playing or
//   paused. Play all ('deck') plays slide by slide: navigating jumps it there.

/** A slide's id, 'deck' (Play all, slide by slide), or 'video' (the whole deck as one track). */
export type TrackKey = 'deck' | 'video' | string

export class Transport {
  private generation = 0
  playing = false
  loadedKey: TrackKey | null = null
  /** The narration revision the loaded track was built from. */
  loadedRevision: string | null = null
  pendingKey: TrackKey | null = null

  /** Register a new play request; returns its token. */
  begin(key: TrackKey): number {
    this.generation++
    this.pendingKey = key
    return this.generation
  }

  /** True if no stop or newer request arrived since `token` was issued. */
  mayStart(token: number): boolean {
    return token === this.generation
  }

  loaded(key: TrackKey, revision: string): void {
    this.loadedKey = key
    this.loadedRevision = revision
    this.pendingKey = null
  }

  unload(): void {
    this.loadedKey = null
    this.loadedRevision = null
    this.playing = false
    this.pendingKey = null
  }

  stop(): void {
    this.generation++
    this.unload()
  }

  /** What a play press for `key` should do, given the deck's current revision. */
  pressAction(key: TrackKey, revision: string): 'build' | 'pause' | 'resume' | 'wait' {
    if (this.pendingKey === key) return 'wait' // a double-click doesn't cancel its own build
    if (this.loadedKey !== key) return 'build'
    // Play all builds each slide as it comes, so an edit never makes it stale
    if (key !== 'deck' && this.loadedRevision !== revision) return 'build'
    return this.playing ? 'pause' : 'resume'
  }

  /** What moving to another slide should do to the player right now. */
  navAction(): 'seek' | 'jump' | 'clear' | 'none' {
    if (this.loadedKey === 'video' || this.pendingKey === 'video') return 'seek'
    if (this.loadedKey === 'deck' || this.pendingKey === 'deck') return 'jump'
    if (this.loadedKey !== null || this.pendingKey !== null) return 'clear'
    return 'none'
  }
}
