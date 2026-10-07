// Play all: the deck slide by slide, inside the chosen conversation.
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import PlayerBar from '@/features/editor/PlayerBar.vue'
import type { PreviewManifest } from '@/features/playback/manifest'
import { nextAfter, playable, progress, startAt } from '@/features/playback/playlist'
import { useConfirm } from '@/stores/confirm'
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'

import { FakeServer, speech } from './fakeServer'

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
    media_url: `/media/${slideId}.wav`, duration: 2,
    speech: [
      { slide_id: slideId, index: 0, start: 0.3, end: 1, silences: [] },
      { slide_id: slideId, index: 1, start: 1, end: 1.8, silences: [] },
    ],
  }
}

/** The deck open, every preview job succeeding at once with its slide's track. */
async function opened(server: FakeServer) {
  setActivePinia(createPinia())
  const editor = useEditorStore()
  const client = server.client()
  client.job = async (id) => {
    const body = server.jobs[Number(id.split('-')[1]) - 1]?.body ?? {}
    return { id, kind: 'preview', status: 'succeeded', result: slideTrack(String(body.slide_id)) } as never
  }
  client.cancelJob = async () => ({}) as never
  editor.client = client
  await editor.open('tok')
  const previews = (): string[] => server.jobs.filter((j) => j.kind === 'preview').map((j) => String(j.body.slide_id))
  return { editor, previews }
}

async function playing(server = new FakeServer()) {
  const { editor, previews } = await opened(server)
  const player = usePlayerStore()
  const audio = new FakeAudio()
  player.attach(audio as unknown as HTMLAudioElement)
  return { editor, player, audio, server, previews }
}

describe('the player bar', () => {
  afterEach(() => vi.restoreAllMocks())

  it('has one Play button, besides Stop: it plays on from this slide, pauses, and resumes', async () => {
    // jsdom plays no media: its <audio> only reports play and pause
    let paused = true
    vi.spyOn(HTMLMediaElement.prototype, 'paused', 'get').mockImplementation(() => paused)
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(async function (this: HTMLMediaElement) {
      paused = false
      this.dispatchEvent(new Event('play'))
    })
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (this: HTMLMediaElement) {
      paused = true
      this.dispatchEvent(new Event('pause'))
    })
    const { editor, previews } = await opened(new FakeServer({ a: 'One.', b: 'Two.', c: 'Three.' }))
    editor.go(1)
    const w = mount(PlayerBar, { attachTo: document.body })
    expect(w.findAll('button').map((b) => b.attributes('data-testid'))).toEqual(['prev', 'next', 'play', 'stop', 'speed'])
    const play = w.get('[data-testid="play"]')
    expect(play.attributes('aria-label')).toBe('Play')
    await play.trigger('click')
    await vi.waitFor(() => expect(play.attributes('data-state')).toBe('playing'))
    expect(play.attributes('aria-label')).toBe('Pause')
    expect(previews()).toEqual(['b', 'c']) // this slide, and the next one getting ready
    await play.trigger('click')
    await vi.waitFor(() => expect(play.attributes('data-state')).toBe('idle'))
    expect(play.attributes('aria-label')).toBe('Play')
    await play.trigger('click')
    await vi.waitFor(() => expect(play.attributes('data-state')).toBe('playing'))
    expect(previews()).toEqual(['b', 'c']) // resumed, not rebuilt
    w.unmount()
  })
})

describe('Play all', () => {
  it('plays slide by slide, preparing the next while one plays, and stops after the last', async () => {
    const { editor, player, audio, previews } = await playing(new FakeServer({ a: 'One.', c: 'Three.' }))
    await player.press()
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
    const { editor, player, audio, previews } = await playing()
    await player.press()
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    player.setEditing(true)
    audio.end()
    await vi.waitFor(() => expect(audio.src).toBe('/media/b.wav'))
    expect(editor.currentId).toBe('a') // the editor waits for you
    expect(player.frame.imageUrl).toBe('/img/p/b.png') // the stage shows b, as it looks now
    editor.go(1) // going to the slide playing: it plays on, not over
    expect(previews().filter((s) => s === 'b')).toHaveLength(1)
    player.setEditing(false)
    expect(editor.currentId).toBe('b')
  })

  it('asks once, up front, before generating missing clips on a paid engine', async () => {
    const server = new FakeServer()
    server.paid = true
    const { player, audio, previews } = await playing(server)
    const asked = vi.spyOn(useConfirm(), 'ask').mockResolvedValue(true)
    await player.press()
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
    await player.press()
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    editor.go(2)
    await vi.waitFor(() => expect(audio.src).toBe('/media/c.wav'))
    expect(player.allProgress).toEqual({ at: 3, of: 3 })
  })

  it('paused to edit, resumes with the new words, from the line it was on', async () => {
    const server = new FakeServer({ a: 'One. Two.', b: 'World.' })
    const { editor, player, audio, previews } = await playing(server)
    await player.press()
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    audio.currentTime = 1.5 // on the second line
    await player.press() // pause
    expect(audio.paused).toBe(true)
    const line = editor.draftFor('a')?.middle[0]
    if (line?.kind === 'speech') line.text = 'One. Two, reworded.'
    editor.touch('a')
    await player.press() // resume: a is rebuilt with the new words
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
    const asked = vi.spyOn(useConfirm(), 'ask').mockResolvedValue(true)
    await player.press()
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    expect(asked).not.toHaveBeenCalled()
    await player.press() // pause
    const line = editor.draftFor('a')?.middle[0]
    if (line?.kind === 'speech') line.text = 'One, reworded.'
    editor.touch('a')
    server.cached = { a: [false], b: [true] } // the new words have no audio yet
    await player.press() // resume
    await vi.waitFor(() => expect(audio.paused).toBe(false))
    expect(asked).toHaveBeenCalledOnce()
    expect(server.jobs.filter((j) => j.kind === 'preview').at(-2)?.body).toMatchObject({ slide_id: 'a', allow_paid: true })
  })
})

describe('clicking a line while playing', () => {
  /** Every slide says two lines (each slide's track plays them at 0.3-1 s and 1-1.8 s). */
  function twoLines(): FakeServer {
    const server = new FakeServer({ a: '', b: '', c: '' })
    for (const block of Object.values(server.narration)) block.segments = [speech('One.'), speech('Two more words.')]
    return server
  }

  it('plays on from the line clicked on the playing slide, or from the word clicked in it', async () => {
    const { player, audio, previews } = await playing(twoLines())
    await player.press()
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    await player.playFrom('a', 1)
    expect(audio.currentTime).toBe(1) // the second line's start
    expect(audio.paused).toBe(false)
    await player.playFrom('a', 1, 'Two more words.'.indexOf('words'))
    expect(audio.currentTime).toBeCloseTo(1 + (0.8 * 9) / 16) // 'Two ' and 'more ' said: 9 of 16
    expect(previews()).toEqual(['a', 'b']) // on the track it had
  })

  it('on another slide: plays it from the line clicked, then on slide by slide', async () => {
    const { editor, player, audio } = await playing(twoLines())
    await player.press()
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    editor.go(1) // clicking into b's words shows b
    await player.playFrom('b', 1)
    await vi.waitFor(() => expect(audio.src).toBe('/media/b.wav'))
    await vi.waitFor(() => expect(audio.currentTime).toBe(1))
    expect(audio.paused).toBe(false)
    audio.end()
    await vi.waitFor(() => expect(audio.src).toBe('/media/c.wav'))
  })

  it('stopped, does nothing; paused, moves where Play resumes', async () => {
    const { player, audio, previews } = await playing(twoLines())
    await player.playFrom('a', 1)
    expect([audio.src, previews()]).toEqual(['', []])
    await player.press()
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    await player.press() // pause
    await player.playFrom('a', 1)
    expect([audio.currentTime, audio.paused]).toEqual([1, true])
    await player.press() // resume
    expect([audio.currentTime, audio.paused]).toEqual([1, false])
    expect(previews()).toEqual(['a', 'b'])
  })

  it('after typing in a line, plays the slide rebuilt with the new words, from the line clicked', async () => {
    const { editor, player, audio, previews } = await playing(twoLines())
    await player.press()
    await vi.waitFor(() => expect(audio.src).toBe('/media/a.wav'))
    const line = editor.draftFor('a')?.middle[0]
    if (line?.kind === 'speech') line.text = 'One, reworded.'
    editor.touch('a')
    await player.playFrom('a', 1)
    await vi.waitFor(() => expect(previews().filter((s) => s === 'a')).toHaveLength(2))
    await vi.waitFor(() => expect(audio.paused).toBe(false))
    expect(audio.currentTime).toBe(1)
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
    server.holding = true
    type(editor, 'Typed just before playing.')
    const pressed = player.press()
    await flushPromises()
    player.stop()
    server.release()
    await pressed
    editor.client.saveSlide = async () => {
      throw new ApiError(500, 'io', 'Disk full.')
    }
    type(editor, 'Typed, never saved.')
    await player.press()
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
    void player.press()
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
