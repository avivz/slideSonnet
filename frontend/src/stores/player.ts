// The preview player for the open deck: builds preview tracks as backend jobs,
// plays them on the browser-owned controller (one <audio> clock), and follows
// the playing slide in the editor — never while the user is typing.
//
// One Play button: it plays from the current slide on, slide by slide over the
// slides in play, each slide's track prepared while the one before it plays.
import { defineStore } from 'pinia'
import { computed, reactive, ref, shallowRef, watch } from 'vue'

import { ApiError, type JobDTO } from '@/api/client'
import { waitForJob } from '@/api/jobs'
import { written } from '@/features/editor/narration'
import { PlaybackController, type Frame } from '@/features/playback/controller'
import type { PreviewManifest } from '@/features/playback/manifest'
import { nextAfter, playable, progress, startAt } from '@/features/playback/playlist'
import { Transport } from '@/features/playback/transport'
import { OutputWaker } from '@/features/playback/wake'
import { fractionAt, lineAt, spanAt, timeAt, voicedFraction, wordAt } from '@/features/playback/words'
import { useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'
import { useReviewStore } from '@/stores/review'

export const SPEEDS = [1, 1.25, 1.5, 2] as const

const EMPTY_FRAME: Frame = {
  loaded: false, playing: false, time: 0, duration: 0, slideId: null, imageUrl: null,
}

/** Where to go on from in a track: a line's start (or the word at `offset` in it), else the time. */
interface Place {
  line: number | null
  time: number
  offset?: number
}

/** A slide's track, prepared ahead; `cancel` drops its job and settles `manifest` with null. */
interface Prepared {
  slideId: string
  revision: string
  manifest: Promise<PreviewManifest | null>
  cancel: () => void
}

/** A preview being built on the server; `cancel` drops it. */
interface PreviewBuild {
  done: Promise<JobDTO>
  cancel: () => void
}

export const usePlayerStore = defineStore('player', () => {
  const editor = useEditorStore()
  const generation = useGenerationStore()
  const review = useReviewStore()
  const transport = reactive(new Transport())
  const frame = shallowRef<Frame>(EMPTY_FRAME)
  const speed = ref<number>(1)
  /** The playing slide's track is being prepared. */
  const building = ref(false)
  /** A field in the narration editor has focus: following waits for it. */
  const editing = ref(false)
  let pendingFollow: string | null = null
  let following = false
  let audio: HTMLAudioElement | null = null
  let controller: PlaybackController | null = null
  /** Bumped by every play press and by Stop: a press that awaited past a newer one gives way. */
  let operation = 0
  const frameListeners = new Set<(f: Frame) => void>()
  /** Plays silence ahead of the first word, so a sleeping output doesn't swallow it. */
  const waker = new OutputWaker()
  /** The word being spoken: a line (by its place among the slide's spoken lines) and a character range. */
  const spoken = ref<{ slideId: string; index: number; start: number; end: number } | null>(null)

  // ---- playing, slide by slide -------------------------------------------------
  /** The slide playback is on (playing it, or getting it ready); null when stopped. */
  const allAt = ref<string | null>(null)
  /** Slides whose clips are missing may be generated (the user agreed, or the engine is free). */
  let allowPaidAll = false
  /** The next slide's track, prepared while this one plays. */
  let ahead: Prepared | null = null
  /** The track playback is waiting for now (cancelled when superseded or stopped). */
  let active: Prepared | null = null
  /** Where that track starts (a line clicked while it was being prepared moves it). */
  let startFrom: Place | null = null
  const allProgress = computed(() =>
    allAt.value === null ? null : progress(editor.pages, review.scope, allAt.value),
  )

  /** A slide's spoken line, by its place among the slide's spoken lines, as it reads now. */
  function lineText(slideId: string, index: number): string | undefined {
    return editor.draftFor(slideId)?.middle.filter((seg) => seg.kind === 'speech' && written(seg))[index]?.text
  }

  /** Where `place` is in `manifest`'s track. */
  function timeOf(manifest: PreviewManifest, place: Place): number {
    const span = manifest.speech.find((s) => s.index === place.line)
    if (!span) return place.time
    const text = place.offset ? lineText(manifest.slide_id, span.index) : undefined
    return text === undefined ? span.start : timeAt(span, fractionAt(text, place.offset ?? 0))
  }

  function updateSpoken(f: Frame): void {
    const spans = controller?.manifest?.speech ?? []
    let next: typeof spoken.value = null
    const span = f.loaded ? spanAt(spans, f.time) : null
    if (span) {
      const text = lineText(span.slide_id, span.index)
      const range = text === undefined ? null : wordAt(text, voicedFraction(span, f.time))
      if (range) next = { slideId: span.slide_id, index: span.index, start: range[0], end: range[1] }
    }
    const now = spoken.value
    // a new value only when the word moves: frames come ~60 times a second
    if (next?.slideId !== now?.slideId || next?.index !== now?.index || next?.start !== now?.start) {
      spoken.value = next
    }
  }

  /** The slide's picture as it is now (a recompiled PDF shows at once, even mid-play). */
  function liveImage(slideId: string): string | null {
    const i = editor.pages.findIndex((p) => p.slide_id === slideId)
    return i >= 0 ? (editor.images[i] ?? null) : null
  }

  /**
   * The frame to draw. The stage shows the editor's slide itself; over it goes
   * the playing slide when the editor is elsewhere (it waits while you type),
   * always in its current picture.
   */
  function staged(f: Frame): Frame {
    if (!f.loaded || f.slideId === null || f.slideId === editor.currentId) return f
    return { ...f, imageUrl: liveImage(f.slideId) }
  }

  /** Bind the player to its <audio> element (the PlayerBar mounts one). */
  function attach(element: HTMLAudioElement): () => void {
    audio = element
    controller = new PlaybackController(element, {
      onFrame: (raw) => {
        const f = staged(raw)
        frame.value = f
        transport.playing = f.playing
        updateSpoken(f)
        for (const l of frameListeners) l(f)
      },
      onEnded: () => void playNext(),
    })
    controller.setRate(speed.value)
    return () => {
      controller?.dispose()
      controller = null
      audio = null
    }
  }

  function onFrame(listener: (f: Frame) => void): () => void {
    frameListeners.add(listener)
    return () => frameListeners.delete(listener)
  }

  /** Bring the editor to the playing slide — later, if a field is being typed in. */
  function showSlide(slideId: string): void {
    if (editing.value) {
      pendingFollow = slideId
      return
    }
    if (slideId === editor.currentId) return
    following = true
    editor.goToSlide(slideId)
    following = false
  }

  function setEditing(on: boolean): void {
    editing.value = on
    if (!on && pendingFollow !== null) {
      const slide = pendingFollow
      pendingFollow = null
      showSlide(slide)
    }
  }

  /** Ask the server for one slide's preview track. */
  async function startPreview(slideId: string, allowPaid: boolean): Promise<PreviewBuild> {
    const token = editor.token
    if (token === null) throw new Error('No deck is open.')
    const job = await editor.client.startJob(token, {
      kind: 'preview',
      slide_id: slideId,
      engine: editor.activeEngine,
      allow_paid: allowPaid,
    })
    const wait = waitForJob(editor.client, job.id)
    return {
      done: wait.done,
      cancel: () => {
        wait.abandon()
        void editor.client.cancelJob(job.id).catch(() => undefined)
      },
    }
  }

  /** Point the player at a built track and start it once the output is awake. */
  async function begin(manifest: PreviewManifest, awake: Promise<void>, place: Place | null = null): Promise<void> {
    if (audio === null || controller === null) return
    audio.src = manifest.media_url
    const track = controller.load(manifest)
    transport.loaded(manifest.narration_revision)
    if (place !== null) controller.seek(timeOf(manifest, place))
    await awake
    controller.play(track) // unless stopped or replaced meanwhile
  }

  /** The Play button: play from this slide on, or pause, or resume. */
  async function press(): Promise<void> {
    const op = ++operation
    const awake = waker.wake() // starts now, in step with the build
    const saved = await editor.ensureSaved() // a play press flushes the field being typed in
    if (op !== operation) return // Stop (or another press) came meanwhile: it wins
    if (!saved) {
      if (!transport.hasTrack) waker.release()
      return // never play words other than the ones on screen
    }
    const action = transport.pressAction(editor.revision)
    if (action === 'wait') return
    if (action === 'pause') {
      controller?.pause()
      return
    }
    if (action === 'resume') {
      const track = controller?.generation
      await awake
      controller?.play(track)
      return
    }
    if (action === 'refresh' && allAt.value !== null) {
      // edited while paused: rebuild with the new words, and go on from the line it was on
      const time = frame.value.time
      await playSlide(allAt.value, awake, { line: lineAt(controller?.manifest?.speech ?? [], time), time })
      return
    }
    await playAll(awake, op)
  }

  /** Play from here: generate what's missing up front (asking once if it costs), then play. */
  async function playAll(awake: Promise<void>, op: number): Promise<void> {
    const first = startAt(editor.pages, review.scope, editor.currentId)
    if (first === null) {
      editor.flash('No slides to play')
      return
    }
    const inPlay = new Set(playable(editor.pages, review.scope))
    const missing = generation.uncached().filter((c) => inPlay.has(c.slide_id))
    allowPaidAll = !generation.paid
    if (missing.length) {
      const queued = await generation.enqueue(missing, { action: 'Generate & play' })
      if (op !== operation) return // stopped while generating was being asked for
      if (generation.paid) allowPaidAll = queued > 0
    }
    await playSlide(first, awake)
  }

  /** Playback reaches `slideId`: show it, play its track (prepared already, or now), prepare the next. */
  async function playSlide(
    slideId: string, awake: Promise<void> = Promise.resolve(), place: Place | null = null,
  ): Promise<void> {
    controller?.pause()
    const ticket = transport.begin()
    startFrom = place
    building.value = true
    allAt.value = slideId
    showSlide(slideId)
    void generation.focus(slideId) // its clips first, if any are still generating
    if (generation.paid && !allowPaidAll) {
      // a line edited since playback began has no audio yet: ask before paying for it
      await editor.refresh()
      const missing = generation.uncached(slideId)
      if (missing.length) allowPaidAll = (await generation.enqueue(missing, { action: 'Generate & play' })) > 0
      if (!transport.mayStart(ticket)) return
    }
    active?.cancel() // a slide playback has moved on from
    const track = take(slideId)
    active = track
    const manifest = await track.manifest
    if (active === track) active = null
    if (!transport.mayStart(ticket)) return // stopped, or moved on meanwhile
    building.value = false
    if (manifest === null) {
      void playNext() // no audio for it (generation declined, or it failed): go on
      return
    }
    await begin(manifest, awake, startFrom)
    const next = nextAfter(editor.pages, review.scope, slideId)
    if (next !== null) prepare(next)
  }

  /**
   * A click in a spoken line: playback goes on from there, at the word clicked
   * (roughly). Playing, it moves within the slide's track, or plays the slide
   * clicked from that line and on slide by slide; edited since, the slide is
   * rebuilt first. Paused, it moves where Play resumes on the paused slide.
   * Stopped, a click only puts the cursor in.
   */
  async function playFrom(slideId: string, line: number, offset = 0): Promise<void> {
    if (allAt.value === null) return
    const op = ++operation
    const saved = await editor.ensureSaved() // the words heard are the ones on screen
    if (op !== operation || !saved || allAt.value === null) return
    if (!playable(editor.pages, review.scope).includes(slideId)) return
    const manifest = controller?.manifest
    // a line the track doesn't have: it stays where it is
    const place: Place = { line, time: manifest?.slide_id === slideId ? frame.value.time : 0, offset }
    const paused = transport.hasTrack && !transport.playing && !transport.pending
    const current = !transport.pending && (paused || transport.loadedRevision === editor.revision)
    if (manifest?.slide_id === slideId && current) {
      // paused after an edit too: Play rebuilds it, on from this line
      controller?.seek(timeOf(manifest, place))
      return
    }
    if (paused) return // another slide: going there while paused stops playback, as ever
    if (transport.pending && allAt.value === slideId) {
      startFrom = place // still being got ready: it starts here
      return
    }
    await playSlide(slideId, Promise.resolve(), place)
  }

  /** The current slide ended: on to the next one, or the end. */
  async function playNext(): Promise<void> {
    if (allAt.value === null) return
    const next = nextAfter(editor.pages, review.scope, allAt.value)
    if (next === null) {
      stop()
      editor.flash('Played to the end', 'ok')
      return
    }
    await playSlide(next)
  }

  /** Start building `slideId`'s track in the background. */
  function prepare(slideId: string): void {
    if (ahead?.slideId === slideId && ahead.revision === editor.revision) return
    ahead?.cancel()
    let cancelled = false
    let build: PreviewBuild | null = null
    let dropped: () => void = () => {}
    const cancelledNow = new Promise<null>((resolve) => (dropped = () => resolve(null)))
    const manifest = (async (): Promise<PreviewManifest | null> => {
      try {
        build = await startPreview(slideId, allowPaidAll)
        if (cancelled) {
          build.cancel()
          return null
        }
        const finished = await Promise.race([build.done, cancelledNow])
        if (finished === null) return null // cancelled while it was being built
        if (finished.status !== 'succeeded' || finished.result === null) {
          if (finished.status === 'failed') {
            const why = finished.error?.message ?? 'unknown error'
            editor.flash(`Slide ${slideId} could not be played: ${why}`, 'err')
          }
          return null
        }
        const m = finished.result as unknown as PreviewManifest
        void fetch(m.media_url).catch(() => undefined) // have the audio at hand when it's needed
        return m
      } catch (e) {
        if (!(e instanceof ApiError && e.code === 'paid_confirmation_required')) {
          editor.flash(e instanceof ApiError ? e.message : `Slide ${slideId} could not be played.`, 'err')
        }
        return null
      }
    })()
    ahead = {
      slideId,
      revision: editor.revision,
      manifest,
      cancel: () => {
        cancelled = true
        build?.cancel()
        dropped()
      },
    }
  }

  /** `slideId`'s track: the one prepared, unless the narration changed since. */
  function take(slideId: string): Prepared {
    prepare(slideId)
    const ready = ahead as Prepared // prepare() always leaves one for slideId
    ahead = null
    return ready
  }

  /** Stop wins: cancels a build in flight and unloads the player. */
  function stop(): void {
    operation++
    allAt.value = null
    ahead?.cancel()
    ahead = null
    active?.cancel()
    active = null
    building.value = false
    transport.stop()
    pendingFollow = null
    controller?.stop()
    waker.release()
    if (audio) {
      audio.pause()
      audio.removeAttribute('src')
    }
  }

  function cycleSpeed(): void {
    const i = SPEEDS.indexOf(speed.value as (typeof SPEEDS)[number])
    speed.value = SPEEDS[(i + 1) % SPEEDS.length] as number
    controller?.setRate(speed.value)
  }

  function seekFraction(f: number): void {
    controller?.seekFraction(f)
  }

  // navigating: playback goes on from the slide chosen (paused, it stops)
  watch(
    () => editor.currentId,
    (slideId) => {
      // (the slide playback is on already: it plays on)
      if (following || transport.navAction() === 'none' || slideId === allAt.value) return
      const paused = transport.hasTrack && !transport.playing
      if (paused || !playable(editor.pages, review.scope).includes(slideId)) stop()
      else void playSlide(slideId)
    },
    { flush: 'sync' }, // `following` is only set for the duration of the call
  )

  return {
    transport, frame, speed, building, editing, spoken, allAt, allProgress,
    attach, onFrame, press, playFrom, stop, cycleSpeed, seekFraction, setEditing,
  }
})
