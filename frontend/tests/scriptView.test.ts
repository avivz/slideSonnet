// The script view: the whole deck's narration as one document.
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ScriptView from '@/features/editor/ScriptView.vue'
import { AUTOSAVE_MS, useEditorStore } from '@/stores/editor'

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

  it('shows pauses inline, editable, between the lines', async () => {
    const server = new FakeServer()
    server.narration.a = {
      ...server.narration.a!,
      segments: [speech('One.'), { kind: 'pause', seconds: 0.7 }, speech('Two.')],
    }
    const { editor } = await setup(server)
    const w = mount(ScriptView, { attachTo: document.body })
    const pause = w.get('[data-testid="script-pause-a-1"]')
    expect((pause.element as HTMLInputElement).value).toBe('0.7')
    await pause.setValue('1.2')
    await pause.trigger('change')
    expect(editor.draftFor('a')?.middle[1]).toMatchObject({ kind: 'pause', seconds: 1.2 })
    await editor.flush()
  })
})
