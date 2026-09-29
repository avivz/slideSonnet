import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type DeckSnapshot } from '@/api/client'
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

it('a recompiled PDF keeps each slide’s old picture until its new one is rendered', async () => {
  const { store, server } = await setup()
  expect(store.images[0]).toBe('/img/p/a.png')
  server.imagesRendered = false // same PDF, its render still filling in: keep what we show
  await store.refresh()
  expect(store.images[0]).toBe('/img/p/a.png')
  // recompiled with slide c moved to the front, nothing of it rendered yet: every
  // slide keeps its last picture (by slide id, not position) — no blank strip
  server.pdfRev = 'p2'
  server.pages = ['c', 'a', 'b']
  await store.refresh()
  expect(store.images).toEqual(['/img/p/c.png', '/img/p/a.png', '/img/p/b.png'])
  server.pages = ['c', 'a', 'b', 'new'] // a slide the old build never had: nothing to hold
  await store.refresh()
  expect(store.images[3]).toBeNull()
  server.imagesRendered = true // the render lands: the new pictures replace the old
  await store.refreshPages()
  expect(store.images).toEqual(['/img/p2/c.png', '/img/p2/a.png', '/img/p2/b.png', '/img/p2/new.png'])
})

// ---- save and session soundness ----------------------------------------------------

/** A promise the test settles by hand (to deliver responses out of order). */
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

describe('conflicts', () => {
  it('keeps every conflicted slide unsaved, and shows them one after another', async () => {
    const { store, server } = await setup()
    typeInto(store, 'a', 'Mine a.')
    typeInto(store, 'b', 'Mine b.')
    server.externalEdit('a', 'Theirs a.')
    server.externalEdit('b', 'Theirs b.')
    await store.refresh()
    expect(store.saveState).toBe('conflict')
    expect(await store.flush()).toBe(false)
    expect(server.saves).toHaveLength(0) // neither outside edit is overwritten
    expect(store.conflict?.slideId).toBe('a')
    await store.resolveConflict('theirs')
    expect(store.conflict).toMatchObject({ slideId: 'b', mine: 'Mine b.', theirs: 'Theirs b.' })
    expect(store.saveState).toBe('conflict') // never "Saved" while one is open
    await store.resolveConflict('mine')
    await flushPromises()
    expect(server.saves.map((s) => s.slideId)).toEqual(['b'])
    expect(server.narration.a?.segments[0]).toMatchObject({ text: 'Theirs a.' })
    expect(store.saveState).toBe('saved')
  })
})

describe('flush', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('says whether everything is saved; a failed save stays visibly unsaved', async () => {
    const { store, server } = await setup()
    typeInto(store, 'a', 'Will fail.')
    const save = store.client.saveSlide
    store.client.saveSlide = async () => {
      throw new ApiError(500, 'io', 'Disk full.')
    }
    expect(await store.flush()).toBe(false)
    expect(store.saveState).toBe('error')
    await vi.advanceTimersByTimeAsync(10_000)
    expect(store.saveState).toBe('error') // until a save succeeds
    store.client.saveSlide = save
    expect(await store.flush()).toBe(true)
    expect(store.saveState).toBe('saved')
    expect(server.saves).toHaveLength(1)
  })
})

describe('deck sessions', () => {
  it('drops a late snapshot of the previous deck', async () => {
    const { store } = await setup(new FakeServer({ a: 'Deck one.' }))
    const late = deferred<DeckSnapshot>()
    store.client.snapshot = () => late.promise
    const refreshing = store.refresh()
    store.client = new FakeServer({ a: 'Deck two.' }).client()
    await store.open('tok2')
    late.resolve(new FakeServer({ a: 'Deck one, late.' }).snapshot())
    await refreshing
    expect(store.draftFor('a')?.middle[0]?.text).toBe('Deck two.')
  })

  it('an open answered after a newer open is dropped', async () => {
    setActivePinia(createPinia())
    const store = useEditorStore()
    const first = new FakeServer({ a: 'First deck.' }).client()
    const late = deferred<DeckSnapshot>()
    first.snapshot = () => late.promise
    store.client = first
    const opening = store.open('tok1')
    await flushPromises()
    store.client = new FakeServer({ a: 'Second deck.' }).client()
    await store.open('tok2')
    late.resolve(new FakeServer({ a: 'First deck.' }).snapshot())
    await opening
    expect(store.token).toBe('tok2')
    expect(store.draftFor('a')?.middle[0]?.text).toBe('Second deck.')
  })

  it('never clears unsaved typing: reopening keeps it, and another deck waits for it to save', async () => {
    const { store, server } = await setup()
    typeInto(store, 'a', 'Still typing.')
    await store.open('tok') // e.g. the editor page mounted again
    expect(store.draftFor('a')?.middle[0]?.text).toBe('Still typing.')
    expect(store.isDirty('a')).toBe(true)
    store.client.saveSlide = async () => {
      throw new ApiError(500, 'io', 'Disk full.')
    }
    expect(await store.open('tok2')).toBe(false) // it can't be saved: stay on this deck
    expect(store.token).toBe('tok')
    expect(store.draftFor('a')?.middle[0]?.text).toBe('Still typing.')
    expect(server.saves).toHaveLength(0)
  })
})
