// The preview player for the open deck: builds preview tracks as backend jobs,
// plays them on the browser-owned controller (one <audio> clock), and follows
// the playing slide in the editor — never while the user is typing.
import { defineStore } from 'pinia'
import { reactive, ref, shallowRef, watch } from 'vue'

import { ApiError } from '@/api/client'
import { waitForJob } from '@/api/jobs'
import { PlaybackController, type Frame } from '@/features/playback/controller'
import type { PreviewManifest } from '@/features/playback/manifest'
import { Transport, type TrackKey } from '@/features/playback/transport'
import { useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'

export const SPEEDS = [1, 1.25, 1.5, 2] as const

const EMPTY_FRAME: Frame = {
  loaded: false, playing: false, time: 0, duration: 0, slideId: null, imageUrl: null, morph: null,
}

export const usePlayerStore = defineStore('player', () => {
  const editor = useEditorStore()
  const generation = useGenerationStore()
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
  let jobId: string | null = null
  let abandonWait: (() => void) | null = null
  const frameListeners = new Set<(f: Frame) => void>()

  /** Bind the player to its <audio> element (the PlayerBar mounts one). */
  function attach(element: HTMLAudioElement): () => void {
    audio = element
    controller = new PlaybackController(element, {
      onFrame: (f) => {
        frame.value = f
        transport.playing = f.playing
        for (const l of frameListeners) l(f)
      },
      onSlide: follow,
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

  function follow(slideId: string): void {
    if (transport.loadedKey !== 'deck') return
    if (editing.value) {
      pendingFollow = slideId
      return
    }
    following = true
    editor.goToSlide(slideId)
    following = false
  }

  function setEditing(on: boolean): void {
    editing.value = on
    if (!on && pendingFollow !== null) {
      const slide = pendingFollow
      pendingFollow = null
      follow(slide)
    }
  }

  /** A play button: the slide (`key` = its id) or the whole deck (`'deck'`). */
  async function press(key: TrackKey): Promise<void> {
    await editor.flush() // a play press flushes the field being typed in
    const action = transport.pressAction(key, editor.revision)
    if (action === 'wait') return
    if (action === 'pause') {
      controller?.pause()
      return
    }
    if (action === 'resume') {
      controller?.play()
      return
    }
    await build(key)
  }

  async function build(key: TrackKey, allowPaid = false): Promise<void> {
    const token = editor.token
    if (token === null || audio === null || controller === null) return
    if (key !== 'deck' && !(editor.page?.audio.speech ?? 0)) {
      editor.flash('This slide has no narration to play')
      return
    }
    cancelBuild()
    controller.pause()
    const ticket = transport.begin(key)
    building.value = key
    try {
      const job = await editor.client.startJob(token, {
        kind: 'preview',
        slide_id: key === 'deck' ? null : key,
        engine: editor.activeEngine,
        allow_paid: allowPaid,
        start_slide: editor.currentId || null,
        single_slide_transitions: generation.singleSlideTransitions,
      })
      jobId = job.id
      const wait = waitForJob(editor.client, job.id)
      abandonWait = wait.abandon
      const finished = await wait.done
      if (!transport.mayStart(ticket)) return // stopped or superseded meanwhile
      if (finished.status !== 'succeeded' || finished.result === null) {
        if (finished.status === 'failed') {
          editor.flash(`Preview failed: ${finished.error?.message ?? 'unknown error'}`, 'err')
        }
        transport.unload()
        return
      }
      const manifest = finished.result as unknown as PreviewManifest
      audio.src = manifest.start_at > 0 ? `${manifest.media_url}#t=${manifest.start_at}` : manifest.media_url
      controller.load(manifest)
      transport.loaded(key, manifest.narration_revision)
      controller.play()
      editor.flash(`Preview ready (${manifest.duration.toFixed(1)}s)`, 'ok')
    } catch (e) {
      transport.unload()
      if (e instanceof ApiError && e.code === 'paid_confirmation_required' && !allowPaid) {
        building.value = null
        const missing = key === 'deck'
          ? (editor.snapshot?.missing_audio ?? 0)
          : (editor.page?.audio.speech ?? 0) - (editor.page?.audio.cached ?? 0)
        if (await confirmPaid(missing)) return build(key, true)
        return
      }
      editor.flash(e instanceof ApiError ? e.message : 'The preview could not be built.', 'err')
    } finally {
      if (transport.mayStart(ticket)) building.value = null
      jobId = null
      abandonWait = null
    }
  }

  let confirmPaid: (count: number) => Promise<boolean> = async () => false
  function setConfirm(fn: (count: number) => Promise<boolean>): void {
    confirmPaid = fn
  }

  function cancelBuild(): void {
    if (jobId !== null) {
      const id = jobId
      jobId = null
      void editor.client.cancelJob(id).catch(() => undefined)
    }
    abandonWait?.()
    abandonWait = null
    building.value = null
  }

  /** Stop wins: cancels a build in flight and unloads the player. */
  function stop(): void {
    cancelBuild()
    transport.stop()
    pendingFollow = null
    controller?.stop()
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

  // navigating: the deck track follows to the new slide; a slide's own track clears
  watch(
    () => editor.currentId,
    (slideId) => {
      if (following) return
      const action = transport.navAction()
      if (action === 'seek') controller?.seekToSlide(slideId)
      else if (action === 'clear') stop()
    },
    { flush: 'sync' }, // `following` is only set for the duration of the call
  )
  // an edit from outside this tab makes the loaded track stale: revoke it
  watch(
    () => editor.externalChanges,
    () => {
      if (transport.loadedKey !== null || building.value !== null) stop()
    },
  )

  return {
    transport, frame, speed, building, editing,
    attach, onFrame, press, stop, cycleSpeed, seekFraction, setEditing, setConfirm,
  }
})
