import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useEditorStore, AUTOSAVE_MS } from '@/stores/editor'

import { FakeServer } from './fakeServer'

async function setup(server = new FakeServer()) {
  setActivePinia(createPinia())
  const store = useEditorStore()
  store.client = server.client()
  await store.open('tok')
  return { store, server }
}

function typeInto(store: ReturnType<typeof useEditorStore>, slideId: string, text: string) {
  const block = store.draftFor(slideId)
  const seg = block?.middle.find((s) => s.kind === 'speech')
  if (!seg) throw new Error('no utterance')
  seg.text = text
  store.touch(slideId)
}

describe('editor store', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('autosaves after a pause, with the revision it was edited at', async () => {
    const { store, server } = await setup()
    typeInto(store, 'a', 'Hel')
    typeInto(store, 'a', 'Hello there.')
    expect(store.saveState).toBe('unsaved')
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS - 1)
    expect(server.saves).toHaveLength(0) // typing never waits on the network
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(server.saves).toHaveLength(1)
    expect(server.saves[0]?.body).toMatchObject({
      expected_revision: 'r1',
      // the speaking slide's start/end silences are written explicitly
      segments: [{ kind: 'pause', seconds: 0.3 }, { kind: 'speech', text: 'Hello there.' }, { kind: 'pause', seconds: 0.6 }],
    })
    expect(store.saveState).toBe('saved')
  })

  it('keeps typing done during a slow save dirty, and saves it next', async () => {
    const { store, server } = await setup()
    server.holding = true
    typeInto(store, 'a', 'First.')
    const first = store.flush()
    await flushPromises()
    typeInto(store, 'a', 'First. And more.') // while the save is in flight
    server.release()
    await first
    await flushPromises()
    expect(store.isDirty('a')).toBe(true) // the ack covered only what was sent
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    await flushPromises()
    expect(server.saves.map((s) => (s.body as { segments: { text?: string }[] }).segments[1]?.text))
      .toEqual(['First.', 'First. And more.'])
    expect(store.isDirty('a')).toBe(false)
  })

  it('rebases a draft when another slide changed on disk', async () => {
    const { store, server } = await setup()
    typeInto(store, 'a', 'Mine.')
    server.externalEdit('b', 'An agent edited b.')
    await store.flush()
    await flushPromises()
    expect(store.conflict).toBeNull()
    expect(server.narration.a?.segments[1]).toMatchObject({ text: 'Mine.' })
  })

  it('shows both versions when the edited slide changed on disk, and never overwrites silently', async () => {
    const { store, server } = await setup()
    typeInto(store, 'a', 'My unsaved typing.')
    server.externalEdit('a', 'The agent rewrote a.')
    await store.refresh() // e.g. the deck.changed event
    expect(store.conflict).toMatchObject({ slideId: 'a', mine: 'My unsaved typing.', theirs: 'The agent rewrote a.' })
    await store.flush()
    expect(server.saves).toHaveLength(0) // not saved over the agent's edit
    await store.resolveConflict('mine')
    await flushPromises()
    expect(server.narration.a?.segments[1]).toMatchObject({ text: 'My unsaved typing.' })
  })

  it('takes the file version for a clean slide, or on request for a conflicted one', async () => {
    const { store, server } = await setup()
    store.draftFor('b') // viewed, not edited
    server.externalEdit('b', 'Fresh from disk.')
    typeInto(store, 'a', 'Typing.')
    server.externalEdit('a', 'Theirs.')
    await store.refresh()
    expect(store.draftFor('b')?.middle[0]?.text).toBe('Fresh from disk.')
    await store.resolveConflict('theirs')
    expect(store.draftFor('a')?.middle[0]?.text).toBe('Theirs.')
    expect(store.hasUnsaved).toBe(false)
  })

  it('navigating saves the slide being left', async () => {
    const { store, server } = await setup()
    typeInto(store, 'a', 'Edited then left.')
    store.go(1)
    await flushPromises()
    expect(store.currentId).toBe('b')
    expect(server.saves).toHaveLength(1)
  })
})

it('opening another deck never reuses the previous deck’s drafts', async () => {
  const { store } = await setup(new FakeServer({ a: 'Deck one.' }))
  store.draftFor('a')
  const other = new FakeServer({ a: 'Deck two.' })
  store.client = other.client()
  const opening = store.open('tok2')
  expect(store.draftFor('a')).toBeNull() // nothing to build from while it loads
  await opening
  expect(store.draftFor('a')?.middle[0]?.text).toBe('Deck two.')
})

it('a recompiled PDF drops the old page images; a render in progress keeps them', async () => {
  const { store, server } = await setup()
  expect(store.images[0]).toBe('/img/p/a.png')
  server.imagesRendered = false // same PDF, its render still filling in: keep what we show
  await store.refresh()
  expect(store.images[0]).toBe('/img/p/a.png')
  server.pdfRev = 'p2' // recompiled: the old pictures are of another PDF
  await store.refresh()
  expect(store.images).toEqual([null, null, null])
})
