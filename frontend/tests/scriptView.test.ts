// The script view: the whole deck's narration as one document.
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import SaveIndicator from '@/features/editor/SaveIndicator.vue'
import ScriptView from '@/features/editor/ScriptView.vue'
import { AUTOSAVE_MS, useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'
import { usePlayerStore } from '@/stores/player'
import { useReviewStore } from '@/stores/review'

import { FakeServer, speech } from './fakeServer'

async function setup(server = new FakeServer()) {
  setActivePinia(createPinia())
  const editor = useEditorStore()
  editor.client = server.client()
  await editor.open('tok')
  return { editor, server }
}

beforeEach(() => {
  document.body.innerHTML = ''
})
afterEach(() => vi.useRealTimers())

describe('script view', () => {
  it('lays the deck out as one script; typing in a slide edits and saves that slide', async () => {
    vi.useFakeTimers()
    const { editor, server } = await setup()
    const w = mount(ScriptView, { attachTo: document.body })
    expect(w.findAll('[data-testid^="script-slide-"]').map((s) => s.attributes('data-testid'))).toEqual([
      'script-slide-a', 'script-slide-b', 'script-slide-c',
    ])
    expect(w.get('[data-testid="script-slide-c"]').text()).toContain('No narration')
    const b = w.get('[data-testid="script-text-b-0"]')
    await b.trigger('focus') // clicking into a slide's words shows that slide
    expect(editor.currentId).toBe('b')
    await b.setValue('New words for b.')
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    await flushPromises()
    expect(server.narration.b?.segments.find((s) => s.kind === 'speech')).toMatchObject({ text: 'New words for b.' })
  })

  it('a slide without narration offers to add a line, and puts the cursor in it', async () => {
    const { editor, server } = await setup()
    const w = mount(ScriptView, { attachTo: document.body })
    await w.get('[data-testid="script-add-c"]').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(w.get('[data-testid="script-text-c-0"]').element)
    expect(editor.currentId).toBe('c') // the slide shows above
    expect(server.saves).toHaveLength(0) // nothing said yet: nothing written
  })

  it('while a line is typed in, playback and auto-generate leave it alone', async () => {
    await setup()
    const player = usePlayerStore()
    const generation = useGenerationStore()
    const w = mount(ScriptView, { attachTo: document.body })
    const line = w.get('[data-testid="script-text-b-0"]')
    await line.trigger('focusin')
    expect([player.editing, generation.focusedSpeech]).toEqual([true, { slideId: 'b', index: 0 }])
    await line.trigger('focusout')
    expect([player.editing, generation.focusedSpeech]).toEqual([false, null])
    await line.trigger('focusin')
    w.unmount() // switched to the slide view while typing: nothing stays held
    expect([player.editing, generation.focusedSpeech]).toEqual([false, null])
  })

  it('shows the deck’s save state, and a failed save until it is retried', async () => {
    const { editor } = await setup()
    const w = mount(SaveIndicator)
    expect(w.text()).toBe('Saved')
    const save = editor.client.saveSlide
    editor.client.saveSlide = async () => {
      throw new ApiError(500, 'io', 'Disk full.')
    }
    const line = editor.draftFor('a')?.middle[0]
    if (line) line.text = 'Changed.'
    editor.touch('a')
    await editor.flush()
    await flushPromises()
    expect(w.text()).toContain('Not saved')
    editor.client.saveSlide = save
    await w.get('button').trigger('click') // retry
    await flushPromises()
    expect(w.text()).toBe('Saved')
  })

  it('marks the word being spoken in its line', async () => {
    await setup(new FakeServer({ a: 'Now change one behaviour.', b: 'World.' }))
    const w = mount(ScriptView, { attachTo: document.body })
    expect(w.find('mark').exists()).toBe(false)
    usePlayerStore().spoken = { slideId: 'a', index: 0, start: 4, end: 10 }
    await flushPromises()
    // everything said so far in the line, up to and including the word
    expect(w.get('[data-testid="script-slide-a"] mark').text()).toBe('Now change')
  })

  it('shows pauses inline, editable, between the lines', async () => {
    const server = new FakeServer()
    server.narration.a = {
      ...server.narration.a!,
      segments: [speech('One.'), { kind: 'pause', seconds: 0.7 }, speech('Two.')],
    }
    const { editor } = await setup(server)
    const w = mount(ScriptView, { attachTo: document.body })
    // a pause sits at the end of the line before it, not on a row of its own
    const pause = w.get('[data-testid="script-line-a-0"] [data-testid="script-pause-a-1"]')
    expect((pause.element as HTMLInputElement).value).toBe('0.7')
    await pause.setValue('1.2')
    await pause.trigger('change')
    expect(editor.draftFor('a')?.middle[1]).toMatchObject({ kind: 'pause', seconds: 1.2 })
    await editor.flush()
  })

  it('under review, shows how each changed slide\'s narration changed', async () => {
    await setup(new FakeServer({ a: 'A.', b: 'World again.' }))
    const review = useReviewStore()
    review.data = {
      active: true, final_build: false, conversations: [], changes: [], unfiled: [], pending: {},
      badges: {}, base_order: ['a', 'b'], base_images: {},
      diffs: { b: [['=', 'World'], ['-', 'today.'], ['+', 'again.']] },
    }
    const w = mount(ScriptView, { attachTo: document.body })
    await flushPromises()
    expect(w.find('[data-testid="script-diff-a"]').exists()).toBe(false) // unchanged: nothing extra
    const diff = w.get('[data-testid="script-slide-b"] [data-testid="script-diff-b"]')
    expect([diff.get('del').text(), diff.get('ins').text()]).toEqual(['today.', 'again.'])
  })
})
