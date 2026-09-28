// The preview player for the open deck: builds preview tracks as backend jobs,
// plays them on the browser-owned controller (one <audio> clock), and follows
// the playing slide in the editor — never while the user is typing.
//
// Three things play: one slide (its own track), Play all (slide by slide, each
// slide's track prepared while the one before it plays), and the whole deck as
// one track with its transitions drawn ("watch as video", slow to prepare).
import { defineStore } from 'pinia'
import { computed, reactive, ref, shallowRef, watch } from 'vue'

import { ApiError, type JobDTO } from '@/api/client'
import { waitForJob } from '@/api/jobs'
import { PlaybackController, type Frame } from '@/features/playback/controller'
import { nextInScope } from '@/features/playback/cues'
import type { PreviewManifest } from '@/features/playback/manifest'
import { nextAfter, playable, progress, startAt } from '@/features/playback/playlist'
import { Transport, type TrackKey } from '@/features/playback/transport'
import { OutputWaker } from '@/features/playback/wake'
import { spanAt, voicedFraction, wordAt } from '@/features/playback/words'
import { useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'
import { useReviewStore } from '@/stores/review'

export const SPEEDS = [1, 1.25, 1.5, 2] as const

const EMPTY_FRAME: Frame = {
  loaded: false, playing: false, time: 0, duration: 0, slideId: null, imageUrl: null, morph: null,
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
  const building = ref<TrackKey | null>(null)
  /** A field in the narration editor has focus: following waits for it. */
  const editing = ref(false)
  let pendingFollow: string | null = null
  let following = false
  let audio: HTMLAudioElement | null = null
  let controller: PlaybackController | null = null
  let current: PreviewBuild | null = null
  const frameListeners = new Set<(f: Frame) => void>()
  /** Plays silence ahead of the first word, so a sleeping output doesn't swallow it. */
  const waker = new OutputWaker()
  /** The word being spoken: a line (by its place among the slide's spoken lines) and a character range. */
  const spoken = ref<{ slideId: string; index: number; start: number; end: number } | null>(null)

  // ---- Play all ---------------------------------------------------------------
  /** The slide Play all is on (playing it, or getting it ready); null when not playing all. */
  const allAt = ref<string | null>(null)
  /** Slides whose clips are missing may be generated (the user agreed, or the engine is free). */
  let allowPaidAll = false
  /** The next slide's track, prepared while this one plays. */
  let ahead: {
    slideId: string
    revision: string
    manifest: Promise<PreviewManifest | null>
    cancel: () => void
  } | null = null
  const allProgress = computed(() =>
    allAt.value === null ? null : progress(editor.pages, review.scope, allAt.value),
  )

  function updateSpoken(f: Frame): void {
    const spans = controller?.manifest?.speech ?? []
    let next: typeof spoken.value = null
    const span = f.loaded ? spanAt(spans, f.time) : null
    if (span) {
      const line = editor.draftFor(span.slide_id)?.middle.filter((seg) => seg.kind === 'speech')[span.index]
      const range = line ? wordAt(line.text, voicedFraction(span, f.time)) : null
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
    if (!f.loaded || f.slideId === null) return f
    const held = allAt.value !== null ? f.slideId !== editor.currentId : f.imageUrl !== null
    return held ? { ...f, imageUrl: liveImage(f.slideId) ?? f.imageUrl } : f
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
      onSlide: follow,
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

  /** The whole-deck track moved on to `slideId`. */
  function follow(slideId: string): void {
    if (transport.loadedKey !== 'video') return
    // inside a chosen conversation the deck plays only its slides
    const scope = review.scope
    if (scope !== null && !scope.has(slideId)) {
      const next = controller?.manifest ? nextInScope(controller.manifest.cues, slideId, scope) : null
      if (next === null) controller?.pause()
      else controller?.seek(next)
      return
    }
    showSlide(slideId)
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

  /** Where the whole-deck track starts: this slide, or the chosen conversation's first. */
  function startSlide(): string | null {
    return startAt(editor.pages, review.scope, editor.currentId) ?? (editor.currentId || null)
  }

  /** Ask the server for a preview track: one slide, or the whole deck (`slideId` null). */
  async function startPreview(slideId: string | null, allowPaid: boolean): Promise<PreviewBuild> {
    const token = editor.token
    if (token === null) throw new Error('No deck is open.')
    const job = await editor.client.startJob(token, {
      kind: 'preview',
      slide_id: slideId,
      engine: editor.activeEngine,
      allow_paid: allowPaid,
      start_slide: slideId === null ? startSlide() : null,
      // Play all cuts between slides; a slide on its own may show its transitions
      single_slide_transitions: allAt.value === null && generation.singleSlideTransitions,
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
  async function begin(key: TrackKey, manifest: PreviewManifest, awake: Promise<void>): Promise<void> {
    if (audio === null || controller === null) return
    audio.src = manifest.start_at > 0 ? `${manifest.media_url}#t=${manifest.start_at}` : manifest.media_url
    const track = controller.load(manifest)
    transport.loaded(key, manifest.narration_revision)
    await awake
    controller.play(track) // unless stopped or replaced meanwhile
  }

  /** A play button: a slide (`key` = its id), Play all (`'deck'`), or the whole deck as one track (`'video'`). */
  async function press(key: TrackKey): Promise<void> {
    const awake = waker.wake() // starts now, in step with the build
    await editor.flush() // a play press flushes the field being typed in
    const action = transport.pressAction(key, editor.revision)
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
    if (key === 'deck') await playAll(awake)
    else await build(key, false, awake)
  }

  /** One slide's track, or the whole deck's as one. */
  async function build(key: TrackKey, allowPaid = false, awake = waker.wake()): Promise<void> {
    if (audio === null || controller === null) return
    if (key !== 'video' && !(editor.page?.audio.speech ?? 0)) {
      editor.flash('This slide has no narration to play')
      return
    }
    stopAll()
    cancelBuild()
    controller.pause()
    const ticket = transport.begin(key)
    building.value = key
    try {
      current = await startPreview(key === 'video' ? null : key, allowPaid)
      const finished = await current.done
      if (!transport.mayStart(ticket)) return // stopped or superseded meanwhile
      if (finished.status !== 'succeeded' || finished.result === null) {
        if (finished.status === 'failed') {
          editor.flash(`Preview failed: ${finished.error?.message ?? 'unknown error'}`, 'err')
        }
        transport.unload()
        return
      }
      const manifest = finished.result as unknown as PreviewManifest
      await begin(key, manifest, awake)
      editor.flash(`Preview ready (${manifest.duration.toFixed(1)}s)`, 'ok')
    } catch (e) {
      transport.unload()
      if (e instanceof ApiError && e.code === 'paid_confirmation_required' && !allowPaid) {
        building.value = null
        const missing = key === 'video'
          ? (editor.snapshot?.missing_audio ?? 0)
          : (editor.page?.audio.speech ?? 0) - (editor.page?.audio.cached ?? 0)
        if (await confirmPaid(missing)) return build(key, true)
        return
      }
      editor.flash(e instanceof ApiError ? e.message : 'The preview could not be built.', 'err')
    } finally {
      if (transport.mayStart(ticket)) building.value = null
      current = null
    }
  }

  /** Play all from here: generate what's missing up front (asking once if it costs), then play. */
  async function playAll(awake: Promise<void>): Promise<void> {
    const first = startAt(editor.pages, review.scope, editor.currentId)
    if (first === null) {
      editor.flash('No slides to play')
      return
    }
    cancelBuild()
    const inPlay = new Set(playable(editor.pages, review.scope))
    const missing = generation.uncached().filter((c) => inPlay.has(c.slide_id))
    allowPaidAll = !generation.paid
    if (missing.length) {
      const queued = await generation.enqueue(missing, { action: 'Generate & play' })
      if (generation.paid) allowPaidAll = queued > 0
    }
    await playSlide(first, awake)
  }

  /** Play all reaches `slideId`: show it, play its track (prepared already, or now), prepare the next. */
  async function playSlide(slideId: string, awake: Promise<void> = Promise.resolve()): Promise<void> {
    controller?.pause()
    const ticket = transport.begin('deck')
    building.value = 'deck'
    allAt.value = slideId
    showSlide(slideId)
    void generation.focus(slideId) // its clips first, if any are still generating
    const manifest = await prepared(slideId)
    if (!transport.mayStart(ticket)) return // stopped, or moved on meanwhile
    building.value = null
    if (manifest === null) {
      void playNext() // no audio for it (generation declined, or it failed): go on
      return
    }
    await begin('deck', manifest, awake)
    const next = nextAfter(editor.pages, review.scope, slideId)
    if (next !== null) prepare(next)
  }

  /** The current slide ended: on to the next one, or the end. */
  async function playNext(): Promise<void> {
    if (allAt.value === null || transport.loadedKey === 'video') return
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
    const manifest = (async (): Promise<PreviewManifest | null> => {
      try {
        build = await startPreview(slideId, allowPaidAll)
        if (cancelled) {
          build.cancel()
          return null
        }
        const finished = await build.done
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
      },
    }
  }

  /** `slideId`'s track: the one prepared, unless the narration changed since. */
  function prepared(slideId: string): Promise<PreviewManifest | null> {
    prepare(slideId)
    const ready = ahead
    ahead = null
    return ready?.manifest ?? Promise.resolve(null)
  }

  /** Leave Play all (the track loaded, if any, is someone else's to stop). */
  function stopAll(): void {
    allAt.value = null
    ahead?.cancel()
    ahead = null
  }

  let confirmPaid: (count: number) => Promise<boolean> = async () => false
  function setConfirm(fn: (count: number) => Promise<boolean>): void {
    confirmPaid = fn
  }

  function cancelBuild(): void {
    current?.cancel()
    current = null
    building.value = null
  }

  /** Stop wins: cancels a build in flight and unloads the player. */
  function stop(): void {
    cancelBuild()
    stopAll()
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

  // navigating: the whole-deck track follows to the new slide, Play all goes on
  // from there (unless paused), and a slide's own track clears
  watch(
    () => editor.currentId,
    (slideId) => {
      if (following) return
      const action = transport.navAction()
      if (action === 'seek') controller?.seekToSlide(slideId)
      else if (action === 'jump') {
        const paused = transport.loadedKey === 'deck' && !transport.playing
        if (paused || !playable(editor.pages, review.scope).includes(slideId)) stop()
        else void playSlide(slideId)
      } else if (action === 'clear') stop()
    },
    { flush: 'sync' }, // `following` is only set for the duration of the call
  )
  // an edit from outside this tab makes the loaded track stale: revoke it (Play
  // all builds each slide as it comes, so it plays on with the new narration)
  watch(
    () => editor.externalChanges,
    () => {
      if (allAt.value !== null) return
      if (transport.loadedKey !== null || building.value !== null) stop()
    },
  )

  return {
    transport, frame, speed, building, editing, spoken, allAt, allProgress,
    attach, onFrame, press, stop, cycleSpeed, seekFraction, setEditing, setConfirm,
  }
})
