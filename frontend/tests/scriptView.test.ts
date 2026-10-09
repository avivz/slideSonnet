// The script view: the whole deck's narration as one document.
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { newSpeech } from '@/features/editor/narration'
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
    server.externalEdit('c', 'Written elsewhere.') // and a change from outside doesn't take it away
    await editor.refresh()
    expect(document.activeElement).toBe(w.get('[data-testid="script-text-c-1"]').element)
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

  it('a click in a line asks playback to go on from the word clicked — not a selection, a pause, or an empty line', async () => {
    const server = new FakeServer()
    server.narration.a = {
      ...server.narration.a!,
      segments: [speech('One.'), { kind: 'pause', seconds: 0.7 }, speech('Two words.')],
    }
    const { editor } = await setup(server)
    editor.draftFor('a')?.middle.push(newSpeech())
    const from = vi.spyOn(usePlayerStore(), 'playFrom').mockResolvedValue()
    const w = mount(ScriptView, { attachTo: document.body })
    const line = w.get('[data-testid="script-text-a-2"]')
    const box = line.element as HTMLTextAreaElement
    box.setSelectionRange(4, 4)
    await line.trigger('click')
    expect(from).toHaveBeenCalledWith('a', 1, 4) // the second spoken line, at 'words'
    box.setSelectionRange(0, 3)
    await line.trigger('click') // selecting words to change them
    await w.get('[data-testid="script-pause-a-1"]').trigger('click')
    await w.get('[data-testid="script-text-a-3"]').trigger('click') // nothing written yet
    expect(from).toHaveBeenCalledOnce()
  })

  it('shows pauses inline, editable, between the lines', async () => {
    const server = new FakeServer()
    server.narration.a = {
      ...server.narration.a!,
      segments: [speech('One.'), { kind: 'pause', seconds: 0.7 }, speech('Two.')],
    }
    const { editor } = await setup(server)
    const w = mount(ScriptView, { attachTo: document.body })
    // one pause in the file is one pause on screen (the line after it brings none)
    expect(w.findAll('[data-testid^="script-pause-a-"]')).toHaveLength(1)
    // a pause sits at the end of the line before it, not on a row of its own
    const pause = w.get('[data-testid="script-line-a-0"] [data-testid="script-pause-a-1"]')
    expect((pause.element as HTMLInputElement).value).toBe('0.7')
    await pause.setValue('1.2')
    await pause.trigger('change')
    expect(editor.draftFor('a')?.middle[1]).toMatchObject({ kind: 'pause', seconds: 1.2 })
    await editor.flush()
  })

  it('shows a real double pause as two; a pause can be added after any line', async () => {
    const server = new FakeServer()
    server.narration.a = {
      ...server.narration.a!,
      segments: [speech('One.'), { kind: 'pause', seconds: 0.3 }, { kind: 'pause', seconds: 0.5 }, speech('Two.'), speech('Three.')],
    }
    const { editor } = await setup(server)
    const w = mount(ScriptView, { attachTo: document.body })
    const pauses = () => w.findAll('[data-testid^="script-pause-a-"]').map((p) => p.attributes('data-testid'))
    expect(pauses()).toEqual(['script-pause-a-1', 'script-pause-a-2'])
    // after the pauses a line already has, too
    await w.get('[data-testid="script-add-pause-a-0"]').trigger('click')
    await flushPromises()
    expect(pauses()).toEqual(['script-pause-a-1', 'script-pause-a-2', 'script-pause-a-3'])
    expect(document.activeElement).toBe(w.get('[data-testid="script-pause-a-3"]').element) // to set its length
    await w.get('[data-testid="script-add-pause-a-4"]').trigger('click')
    await editor.flush()
    const saved = server.narration.a?.segments.map((s) => (s.kind === 'pause' ? s.seconds : s.text))
    expect(saved?.slice(1, -1)).toEqual(['One.', 0.3, 0.5, 1, 'Two.', 1, 'Three.']) // within the start/end silences
  })

  it('a pause cleared, set to 0, or deleted across from a line goes away', async () => {
    const server = new FakeServer()
    server.narration.a = {
      ...server.narration.a!,
      segments: [
        speech('One.'), { kind: 'pause', seconds: 0.3 }, speech('Two.'), { kind: 'pause', seconds: 0.5 },
        speech('Three.'), { kind: 'pause', seconds: 0.7 }, speech('Four.'), { kind: 'pause', seconds: 0.9 }, speech('Five.'),
      ],
    }
    const { editor } = await setup(server)
    const w = mount(ScriptView, { attachTo: document.body })
    await w.get('[data-testid="script-pause-a-1"]').setValue('')
    await w.get('[data-testid="script-pause-a-2"]').setValue('0') // (the pauses after shift down one)
    // Backspace at the start of a line takes the pause before it
    const four = w.get('[data-testid="script-text-a-4"]')
    ;(four.element as HTMLTextAreaElement).setSelectionRange(0, 0)
    await four.trigger('keydown', { key: 'Backspace' })
    // Delete at the end of a line takes the pause after it
    const moved = w.get('[data-testid="script-text-a-3"]')
    expect(moved.element).toBe(four.element) // the same line, one place up
    ;(moved.element as HTMLTextAreaElement).setSelectionRange(5, 5)
    await moved.trigger('keydown', { key: 'Delete' })
    expect(w.findAll('[data-testid^="script-pause-a-"]')).toHaveLength(0)
    await editor.flush()
    const saved = server.narration.a?.segments.map((s) => (s.kind === 'pause' ? s.seconds : s.text))
    expect(saved?.slice(1, -1)).toEqual(['One.', 'Two.', 'Three.', 'Four.', 'Five.'])
  })

  it('Enter splits a line where the cursor is (at its end: a new empty line); Backspace at a line’s start joins it back', async () => {
    const server = new FakeServer()
    server.narration.a = {
      ...server.narration.a!,
      segments: [speech('One. Two.'), { kind: 'pause', seconds: 0.4 }, speech('Three.')],
    }
    const { editor } = await setup(server)
    const middle = () => editor.draftFor('a')?.middle.map((s) => (s.kind === 'pause' ? s.seconds : s.text))
    const w = mount(ScriptView, { attachTo: document.body })
    const line = w.get('[data-testid="script-text-a-0"]')
    ;(line.element as HTMLTextAreaElement).focus()
    ;(line.element as HTMLTextAreaElement).setSelectionRange(4, 4)
    await line.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(middle()).toEqual(['One.', 'Two.', 0.4, 'Three.']) // the pause still follows the words it followed
    const two = w.get('[data-testid="script-text-a-1"]').element as HTMLTextAreaElement
    expect([document.activeElement, two.selectionStart]).toEqual([two, 0])
    // Shift+Enter is a line break inside the line, as before
    await w.get('[data-testid="script-text-a-1"]').trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(middle()).toHaveLength(4)
    // Backspace at the start of a line right after another joins the two
    await w.get('[data-testid="script-text-a-1"]').trigger('keydown', { key: 'Backspace' })
    await flushPromises()
    expect(middle()).toEqual(['One. Two.', 0.4, 'Three.'])
    const one = w.get('[data-testid="script-text-a-0"]').element as HTMLTextAreaElement
    expect([document.activeElement, one.selectionStart]).toEqual([one, 4])
    // at a line's end: a new, empty line, with the cursor in it (written once it has words)
    one.setSelectionRange(9, 9)
    await w.get('[data-testid="script-text-a-0"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(middle()).toEqual(['One. Two.', '', 0.4, 'Three.'])
    expect(document.activeElement).toBe(w.get('[data-testid="script-text-a-1"]').element)
    await editor.flush()
    expect(server.narration.a?.segments.filter((s) => s.kind === 'speech').map((s) => s.text)).toEqual(['One. Two.', 'Three.'])
  })

  it('a line can be added after any line, empty, with the cursor in it', async () => {
    const server = new FakeServer()
    server.narration.a = {
      ...server.narration.a!,
      segments: [speech('One.'), { kind: 'pause', seconds: 0.4 }, speech('Two.')],
    }
    const { editor } = await setup(server)
    const w = mount(ScriptView, { attachTo: document.body })
    await w.get('[data-testid="script-add-line-a-0"]').trigger('click')
    await flushPromises()
    // after the pause the line ends with
    expect(editor.draftFor('a')?.middle.map((s) => (s.kind === 'pause' ? s.seconds : s.text))).toEqual(['One.', 0.4, '', 'Two.'])
    expect(document.activeElement).toBe(w.get('[data-testid="script-text-a-2"]').element)
    expect(editor.currentId).toBe('a')
  })

  // under review the server notes the edit right after saving it: an outside change
  it.each([false, true])('a line emptied and left goes away (another change after the save: %s)', async (noted) => {
    const server = new FakeServer()
    server.narration.a = { ...server.narration.a!, segments: [speech('One.'), speech('Two.')] }
    const { editor } = await setup(server)
    if (noted) {
      const save = editor.client.saveSlide
      editor.client.saveSlide = async (...args) => {
        const result = await save(...args)
        server.rev++
        return result
      }
    }
    const w = mount(ScriptView, { attachTo: document.body })
    const line = w.get('[data-testid="script-text-a-1"]')
    ;(line.element as HTMLTextAreaElement).focus()
    await line.setValue('')
    await editor.flush()
    await flushPromises()
    expect(server.narration.a?.segments.filter((s) => s.kind === 'speech').map((s) => s.text)).toEqual(['One.'])
    expect(w.find('[data-testid="script-line-a-1"]').exists()).toBe(true) // still in it: it stays
    line.element.dispatchEvent(new FocusEvent('blur')) // another window took focus: the cursor stays here
    await flushPromises()
    expect(w.find('[data-testid="script-line-a-1"]').exists()).toBe(true)
    ;(line.element as HTMLTextAreaElement).blur()
    await flushPromises()
    expect(w.find('[data-testid="script-line-a-1"]').exists()).toBe(false)
    expect(editor.isDirty('a')).toBe(false) // nothing more to save
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

  it('inside a chosen conversation, going to a slide outside it shows every slide again', async () => {
    const { editor } = await setup()
    const review = useReviewStore()
    review.data = {
      active: true, final_build: false, changes: [], unfiled: [], pending: {}, badges: {},
      base_order: ['a', 'b', 'c'], base_images: {}, diffs: {},
      conversations: [
        { id: 'c1', title: '', slides: ['a'], origin: 'requested', status: 'open', turn: 'agent', messages: [] },
      ],
    }
    review.filter = 'c1'
    const w = mount(ScriptView, { attachTo: document.body })
    await flushPromises()
    expect(w.get('[data-testid="script-slide-b"]').classes()).toContain('dimmed')
    await w.get('[data-testid="script-text-a-0"]').trigger('focus') // a slide of the conversation: still chosen
    await w.get('[data-testid="script-slide-a"]').trigger('click')
    expect(review.filter).toBe('c1')
    await w.get('[data-testid="script-slide-b"]').trigger('click') // anywhere in another slide
    expect([review.filter, editor.currentId]).toEqual([null, 'b'])
    review.filter = 'c1'
    await w.get('[data-testid="script-text-b-0"]').trigger('focus') // or into its words
    expect(review.filter).toBeNull()
  })
})
