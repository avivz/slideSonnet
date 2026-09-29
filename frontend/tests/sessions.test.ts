// Switching decks (or engines) while answers are on their way: a late answer
// for the old one is dropped, and nothing from the old deck's review leaks over.
// Whatever consumes the narration stops while it can't be saved.
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'

import { ApiError, type GenerationStatusDTO, type ReviewDTO } from '@/api/client'
import ConsolePanel from '@/features/editor/ConsolePanel.vue'
import { useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'
import { useReviewStore } from '@/stores/review'

import { FakeServer } from './fakeServer'

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

function review(active: boolean): ReviewDTO {
  return {
    active, final_build: false, conversations: [], changes: [], unfiled: [], pending: {}, badges: {},
    base_order: [], base_images: {}, diffs: {},
  }
}

function status(engine: string, queued: number): GenerationStatusDTO {
  return { engine, done: 0, total: 0, running: null, inflight: [], last_error: null, queued } as GenerationStatusDTO
}

async function setup() {
  setActivePinia(createPinia())
  const server = new FakeServer()
  const editor = useEditorStore()
  editor.client = server.client()
  await editor.open('tok')
  return { editor, server }
}

describe('a late answer for the previous deck', () => {
  it('is dropped by the review, whose picks and views start afresh', async () => {
    const { editor } = await setup()
    const store = useReviewStore()
    const late = deferred<ReviewDTO>()
    editor.client.review = () => late.promise
    const loading = store.refresh()
    store.pick('b')
    store.beforeOnly = true
    editor.client = new FakeServer().client()
    editor.client.review = async () => review(false)
    await editor.open('tok2')
    expect([store.picked, store.pickedByHand, store.beforeOnly]).toEqual([[], false, false])
    await store.refresh()
    late.resolve(review(true))
    await loading
    expect(store.active).toBe(false) // deck two's review, not deck one's
  })

  it('is dropped by generation, for a deck or an engine switched away from', async () => {
    const { editor } = await setup()
    const store = useGenerationStore()
    const late = deferred<GenerationStatusDTO>()
    editor.client.generation = () => late.promise
    const loading = store.refresh()
    editor.client.generation = async (_t, engine) => status(String(engine), 2)
    await editor.setEngine('inworld')
    await store.refresh()
    late.resolve(status('kokoro', 7))
    await loading
    expect(store.status).toMatchObject({ engine: 'inworld', queued: 2 })
  })
})

describe('when the narration can’t be saved', () => {
  it('generation, export and review commands stop instead of using the old text', async () => {
    const { editor, server } = await setup()
    const block = editor.draftFor('a')
    if (block?.middle[0]) block.middle[0].text = 'Unsaved.'
    editor.touch('a')
    editor.client.saveSlide = async () => {
      throw new ApiError(500, 'io', 'Disk full.')
    }
    let sent = 0
    editor.client.reviewCommand = async () => {
      sent++
      return { message: '', conversation: null, count: 0, focus: false }
    }
    expect(await useGenerationStore().enqueue(null)).toBe(0)
    expect(server.generated).toEqual([])
    expect(await useReviewStore().command({ type: 'comment', slides: ['a'], text: 'Look.' })).toBe(false)
    expect(sent).toBe(0)
    const w = mount(ConsolePanel, { props: { confirm: async () => true } })
    await w.get('[data-testid="export"]').trigger('click')
    await flushPromises()
    expect(server.jobs).toEqual([])
    w.unmount()
  })
})
