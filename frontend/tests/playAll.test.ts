// Play all: the deck slide by slide, inside the chosen conversation.
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { PreviewManifest } from '@/features/playback/manifest'
import { nextAfter, playable, progress, startAt } from '@/features/playback/playlist'
import { useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'
import { usePlayerStore } from '@/stores/player'

import { FakeServer } from './fakeServer'

const pages = [{ slide_id: 'a' }, { slide_id: '' }, { slide_id: 'b' }, { slide_id: 'c' }, { slide_id: 'd' }]

describe('what Play all plays', () => {
  it('plays every slide with an id, or only the chosen conversation\'s', () => {
    expect(playable(pages, null)).toEqual(['a', 'b', 'c', 'd']) // a page without an id can't be built
    expect(playable(pages, new Set(['b', 'd']))).toEqual(['b', 'd'])
  })

  it('starts here, or at the conversation\'s first slide when here is outside it', () => {
    expect(startAt(pages, null, 'c')).toBe('c')
    expect(startAt(pages, new Set(['b', 'd']), 'c')).toBe('b')
    expect(startAt(pages, new Set(['zz']), 'c')).toBeNull() // nothing to play
  })

  it('moves on to the next slide in play, and ends after the last', () => {
    expect(nextAfter(pages, null, 'a')).toBe('b') // over the page without an id
    expect(nextAfter(pages, new Set(['a', 'd']), 'a')).toBe('d')
    expect(nextAfter(pages, null, 'd')).toBeNull()
  })

  it('counts where it is: slide 2 of 3', () => {
    expect(progress(pages, new Set(['a', 'c', 'd']), 'c')).toEqual({ at: 2, of: 3 })
  })
})

// ---- the player playing all, against a fake <audio> and the fake server --------

class FakeAudio {
  src = ''
  currentTime = 0
  duration = NaN
  paused = true
  playbackRate = 1
  defaultPlaybackRate = 1
  private listeners = new Map<string, Set<() => void>>()
  async play(): Promise<void> {
    this.paused = false
    this.emit('play')
  }
  pause(): void {
    this.paused = true
    this.emit('pause')
  }
  removeAttribute(): void {
    this.src = ''
  }
  addEventListener(type: string, l: () => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set())
    this.listeners.get(type)?.add(l)
  }
  removeEventListener(type: string, l: () => void): void {
    this.listeners.get(type)?.delete(l)
  }
  emit(type: string): void {
    for (const l of this.listeners.get(type) ?? []) l()
  }
  /** The track plays out. */
  end(): void {
    this.paused = true
    this.emit('ended')
  }
}

function slideTrack(slideId: string): PreviewManifest {
  return {
    artifact_id: slideId, slide_id: slideId, narration_revision: 'r1', pdf_revision: 'p', engine: 'kokoro',
    media_url: `/media/${slideId}.wav`, duration: 2, start_at: 0,
    cues: [{ start: 0, slide_id: slideId }], pages: [], transitions: [],
    speech: [
      { slide_id: slideId, index: 0, start: 0.3, end: 1, silences: [] },
      { slide_id: slideId, index: 1, start: 1, end: 1.8, silences: [] },
    ],
  }
}

async function playing(server = new FakeServer()) {
  setActivePinia(createPinia())
  const editor = useEditorStore()
  const client = server.client()
  // every preview job succeeds at once with its slide's track
  client.job = async (id) => {
    const body = server.jobs[Number(id.split('-')[1]) - 1]?.body ?? {}
    return { id, kind: 'preview', status: 'succeeded', result: slideTrack(String(body.slide_id)) } as never
  }
  client.cancelJob = async () => ({}) as never
  editor.client = client
  await editor.open('tok')
  const player = usePlayerStore()
  const audio = new FakeAudio()
  player.attach(audio as unknown as HTMLAudioElement)
  const previews = (): string[] => server.jobs.filter((j) => j.kind === 'preview').map((j) => String(j.body.slide_id))
  return { editor, player, audio, server, previews }
}

describe('Play all', () => {
  it('plays slide by slide, preparing the next while one plays, and stops after the last', async () => {
    const { editor, player, audio, previews } = await playing(new FakeServer({ a: 'One.', c: 'Three.' }))
    await player.press('deck')
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    expect(player.allProgress).toEqual({ at: 1, of: 3 })
    await vi.waitFor(() => expect(previews()).toEqual(['a', 'b'])) // b is ready before a ends
    audio.end()
    await vi.waitFor(() => expect(audio.src).toBe('/media/b.wav')) // a silent slide plays too: its pause
    expect(editor.currentId).toBe('b') // the editor follows
    audio.end()
    await vi.waitFor(() => expect(audio.src).toBe('/media/c.wav'))
    audio.end()
    await vi.waitFor(() => expect(player.allAt).toBeNull())
    expect(audio.src).toBe('')
  })

  it('while you type, plays on and shows the playing slide over the one you type in', async () => {
    const { editor, player, audio } = await playing()
    await player.press('deck')
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    player.setEditing(true)
    audio.end()
    await vi.waitFor(() => expect(audio.src).toBe('/media/b.wav'))
    expect(editor.currentId).toBe('a') // the editor waits for you
    expect(player.frame.imageUrl).toBe('/img/p/b.png') // the stage shows b, as it looks now
    player.setEditing(false)
    expect(editor.currentId).toBe('b')
  })

  it('asks once, up front, before generating missing clips on a paid engine', async () => {
    const server = new FakeServer()
    server.paid = true
    const { player, audio, previews } = await playing(server)
    const asked = vi.fn(async () => true)
    useGenerationStore().setConfirm(asked)
    await player.press('deck')
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    expect(asked).toHaveBeenCalledOnce()
    expect(server.generated[0]).toMatchObject({ allow_paid: true, targets: [
      { slide_id: 'a', speech_index: 0 }, { slide_id: 'b', speech_index: 0 },
    ] })
    await vi.waitFor(() => expect(previews()).toEqual(['a', 'b']))
    expect(server.jobs.every((j) => j.body.allow_paid === true)).toBe(true)
  })

  it('jumping to another slide plays on from there', async () => {
    const { editor, player, audio } = await playing()
    await player.press('deck')
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    editor.go(2)
    await vi.waitFor(() => expect(audio.src).toBe('/media/c.wav'))
    expect(player.allProgress).toEqual({ at: 3, of: 3 })
  })

  it('paused to edit, resumes with the new words, from the line it was on', async () => {
    const server = new FakeServer({ a: 'One. Two.', b: 'World.' })
    const { editor, player, audio, previews } = await playing(server)
    await player.press('deck')
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    audio.currentTime = 1.5 // on the second line
    await player.press('deck') // pause
    expect(audio.paused).toBe(true)
    const line = editor.draftFor('a')?.middle[0]
    if (line?.kind === 'speech') line.text = 'One. Two, reworded.'
    editor.touch('a')
    await player.press('deck') // resume: a is rebuilt with the new words
    await vi.waitFor(() => expect(previews().filter((s) => s === 'a')).toHaveLength(2))
    await vi.waitFor(() => expect(audio.paused).toBe(false))
    expect(audio.currentTime).toBe(1) // back to the start of the line it paused in
  })

  it('on a paid engine, asks before generating a line edited while paused', async () => {
    const server = new FakeServer({ a: 'One.', b: 'World.' })
    server.paid = true
    server.cached = { a: [true], b: [true] } // everything generated: Play all starts without asking
    const { editor, player, audio } = await playing(server)
    editor.engine = 'inworld' // a paid engine (the fake server never calls it)
    const asked = vi.fn(async () => true)
    useGenerationStore().setConfirm(asked)
    await player.press('deck')
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    expect(asked).not.toHaveBeenCalled()
    await player.press('deck') // pause
    const line = editor.draftFor('a')?.middle[0]
    if (line?.kind === 'speech') line.text = 'One, reworded.'
    editor.touch('a')
    server.cached = { a: [false], b: [true] } // the new words have no audio yet
    await player.press('deck') // resume
    await vi.waitFor(() => expect(audio.paused).toBe(false))
    expect(asked).toHaveBeenCalledOnce()
    expect(server.jobs.filter((j) => j.kind === 'preview').at(-2)?.body).toMatchObject({ slide_id: 'a', allow_paid: true })
  })
})

describe('Stop wins', () => {
  function type(editor: ReturnType<typeof useEditorStore>, text: string): void {
    const line = editor.draftFor('a')?.middle[0]
    if (line?.kind === 'speech') line.text = text
    editor.touch('a')
  }

  it('over a play press still saving the line being typed, or one that can’t be saved', async () => {
    const { editor, player, server, previews } = await playing()
    for (const key of ['a', 'deck']) {
      server.holding = true
      type(editor, `Typed just before playing ${key}.`)
      const pressed = player.press(key)
      await flushPromises()
      player.stop()
      server.release()
      await pressed
    }
    editor.client.saveSlide = async () => {
      throw new ApiError(500, 'io', 'Disk full.')
    }
    type(editor, 'Typed, never saved.')
    await player.press('a')
    await flushPromises()
    expect(previews()).toEqual([])
  })

  it('cancels Play all’s track being built, and a superseded one', async () => {
    const { editor, player, server } = await playing()
    const cancelled: string[] = []
    editor.client.job = async (id) => ({ id, kind: 'preview', status: 'running', result: null }) as never
    editor.client.cancelJob = async (id) => {
      cancelled.push(id)
      return {} as never
    }
    void player.press('deck')
    await vi.waitFor(() => expect(server.jobs.map((j) => j.body.slide_id)).toContain('a'))
    editor.go(2) // on to c while a is still being built
    await vi.waitFor(() => expect(server.jobs.map((j) => j.body.slide_id)).toContain('c'))
    expect(cancelled).toContain('job-1')
    player.stop()
    await flushPromises()
    const c = server.jobs.findIndex((j) => j.body.slide_id === 'c')
    expect(cancelled).toContain(`job-${c + 1}`)
  })
})
