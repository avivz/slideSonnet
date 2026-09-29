// Component tests for the deck editor, against the in-memory fake server.
// One test per behavior worth pinning; the browser journeys cover focus,
// real audio, and navigation between pages.
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ConsolePanel from '@/features/editor/ConsolePanel.vue'
import NarrationEditor from '@/features/editor/NarrationEditor.vue'
import OrphanTray from '@/features/editor/OrphanTray.vue'
import VoicesDialog from '@/features/editor/VoicesDialog.vue'
import { AUTOSAVE_MS, useEditorStore } from '@/stores/editor'
import { AUTO_BUILD_MS, useGenerationStore } from '@/stores/generation'

import { FakeServer, speech } from './fakeServer'

async function setup(server = new FakeServer()) {
  setActivePinia(createPinia())
  const editor = useEditorStore()
  editor.client = server.client()
  await editor.open('tok')
  return { editor, server, generation: useGenerationStore() }
}

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('narration editor', () => {
  afterEach(() => vi.useRealTimers())

  it('flips the clip badge the moment typing leaves the generated text', async () => {
    const server = new FakeServer()
    server.cached.a = [true]
    await setup(server)
    const w = mount(NarrationEditor, { attachTo: document.body })
    const gen = w.get('[data-testid="gen-seg-0"]')
    expect(gen.attributes('data-state')).toBe('fresh')
    await w.get('[data-testid="utext-0"]').setValue('Hello, changed.')
    expect(gen.attributes('data-state')).toBe('missing') // before any save
    await w.get('[data-testid="utext-0"]').setValue('Hello.') // typed back: fresh again
    expect(gen.attributes('data-state')).toBe('fresh')
  })

  it('saves structure edits at once, and voice labels name the engine voice', async () => {
    vi.useFakeTimers()
    const server = new FakeServer()
    const { editor } = await setup(server)
    editor.snapshot = {
      ...editor.snapshot!,
      voices: { map: { lecturer: { kokoro: 'am_michael' } }, default_voice: 'lecturer', names: ['lecturer', 'guest'],
        resolved: { lecturer: 'am_michael', guest: null } },
    }
    const w = mount(NarrationEditor, { attachTo: document.body })
    await w.get('[data-testid="usettings-0"]').trigger('click')
    expect(w.get('[data-testid="uvoice-0"]').findAll('option').map((o) => o.text())).toEqual([
      'default (lecturer)', 'lecturer (am_michael)', 'guest (unmapped)',
    ])
    await w.get('[data-testid="add-pause"]').trigger('click')
    await flushPromises()
    expect(server.saves).toHaveLength(1) // no debounce for a structural edit
    await w.get('[data-testid="seg-up-1"]').trigger('click')
    await w.get('[data-testid="seg-del-0"]').trigger('click')
    await flushPromises()
    const last = server.narration.a?.segments
    expect(last?.map((s) => s.kind)).toEqual(['pause', 'speech', 'pause']) // silences + the line
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
  })

  it('+ Line and + Pause put the cursor in the new block; an empty line is never saved', async () => {
    const { server } = await setup()
    const w = mount(NarrationEditor, { attachTo: document.body })
    await w.get('[data-testid="add-utterance"]').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(w.get('[data-testid="utext-1"]').element)
    expect(server.saves).toHaveLength(0) // nothing said yet: nothing to write
    await w.get('[data-testid="add-pause"]').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(w.get('[data-testid="pause-secs-2"]').element)
    expect(server.narration.a?.segments.map((s) => s.kind === 'speech' ? s.text : s.seconds))
      .toEqual([0.3, 'Hello.', 1, 0.6]) // the pause, without an empty line
  })

  it('folds a line’s voice, pace and note away, naming only what differs from the defaults', async () => {
    const server = new FakeServer()
    const { editor } = await setup(server)
    const w = mount(NarrationEditor, { attachTo: document.body })
    expect(w.find('[data-testid="upace-0"]').exists()).toBe(false) // the text is what matters
    expect(w.find('[data-testid="uchips-0"]').exists()).toBe(false) // all defaults: nothing to name
    await w.get('[data-testid="usettings-0"]').trigger('click')
    await w.get('[data-testid="upace-0"]').setValue('slow')
    await w.get('[data-testid="udirect-0"]').setValue('warmly')
    await w.get('[data-testid="usettings-0"]').trigger('click') // fold it again
    expect(w.find('[data-testid="upace-0"]').exists()).toBe(false)
    expect(w.get('[data-testid="uchips-0"]').text()).toBe('slow · “warmly”')
    await w.get('[data-testid="uchips-0"]').trigger('click') // the chips open the settings too
    expect(w.find('[data-testid="upace-0"]').exists()).toBe(true)
    await editor.flush()
  })

  it('an opened line stays open when a newer version of the slide arrives', async () => {
    const server = new FakeServer()
    const { editor } = await setup(server)
    const w = mount(NarrationEditor, { attachTo: document.body })
    await w.get('[data-testid="usettings-0"]').trigger('click')
    server.narration.a = { ...server.narration.a!, segments: [speech('Reworded by the agent.')] }
    server.rev++
    await editor.refresh() // nothing typed here: the new version is taken, in place
    await flushPromises()
    expect((w.get('[data-testid="utext-0"]').element as HTMLTextAreaElement).value).toBe('Reworded by the agent.')
    expect(w.find('[data-testid="upace-0"]').exists()).toBe(true)
  })

  it('a line naming the deck’s default voice shows no voice chip', async () => {
    const server = new FakeServer()
    server.narration.a = { ...server.narration.a!, segments: [{ kind: 'speech', text: 'Hi.', voice: 'lecturer', pace: null, direction: null }] }
    const { editor } = await setup(server)
    editor.snapshot = {
      ...editor.snapshot!,
      voices: { map: {}, default_voice: 'lecturer', names: ['lecturer', 'guest'], resolved: { lecturer: 'x', guest: 'y' } },
    }
    const w = mount(NarrationEditor, { attachTo: document.body })
    expect(w.find('[data-testid="uchips-0"]').exists()).toBe(false)
  })

  it('a slide without an id cannot be edited', async () => {
    const server = new FakeServer()
    server.pages = ['']
    await setup(server)
    const w = mount(NarrationEditor)
    expect(w.text()).toContain('no slide id')
    expect(w.get('[data-testid="add-utterance"]').attributes('disabled')).toBeDefined()
  })
})

describe('console', () => {
  it('asks before paid generation, and only then allows it', async () => {
    const server = new FakeServer()
    server.paid = true
    const { editor } = await setup(server)
    editor.snapshot = { ...editor.snapshot!, missing_audio: 2 }
    const confirm = vi.fn(async () => true)
    useGenerationStore().setConfirm(confirm)
    const w = mount(ConsolePanel, { props: { confirm: async () => false } })
    await w.get('[data-testid="gen-missing"]').trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalledWith(2, 'kokoro', 'Generate')
    expect(server.generated).toEqual([{ targets: null, force: false, allow_paid: true }])
  })

  it('explains export blockers and exports a draft on request', async () => {
    const server = new FakeServer()
    server.blockers = ['deck.pdf is a plain build']
    await setup(server)
    const confirm = vi.fn(async (_o: { title: string; lines: string[]; yes: string }) => true)
    const w = mount(ConsolePanel, { props: { confirm } })
    await w.get('[data-testid="export"]').trigger('click')
    await vi.waitFor(() => expect(server.jobs).toHaveLength(1))
    expect(confirm.mock.calls[0]?.[0].lines[0]).toContain('plain build')
    expect(server.jobs[0]?.body).toMatchObject({ kind: 'export', draft: true })
    await vi.waitFor(() => expect(useEditorStore().flashMessage?.text).toContain('Exported deck.draft.mp4'))
  })
})

describe('auto-generate', () => {
  afterEach(() => vi.useRealTimers())

  it('generates an edited slide after it settles, skipping the line being typed', async () => {
    vi.useFakeTimers()
    const server = new FakeServer({ a: 'One.' })
    server.narration.a!.segments.push(speech('Two.'))
    const { editor, generation } = await setup(server)
    await generation.setAutoBuild(true) // sweeps the other slides (none have speech)
    server.generated = []
    const block = editor.draftFor('a')!
    block.middle[0]!.text = 'One, edited.'
    editor.touch('a')
    generation.focusedSpeech = { slideId: 'a', index: 1 } // still typing in line two
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS)
    await flushPromises()
    expect(server.generated).toEqual([]) // waits for the text to settle
    await vi.advanceTimersByTimeAsync(AUTO_BUILD_MS)
    await flushPromises()
    expect(server.generated).toEqual([
      { targets: [{ slide_id: 'a', speech_index: 0 }], force: false, allow_paid: false },
    ])
  })

  it('is refused on a paid engine', async () => {
    const server = new FakeServer()
    const { editor, generation } = await setup(server)
    editor.snapshot = { ...editor.snapshot!, engine: 'inworld' }
    await generation.setAutoBuild(true)
    expect(generation.autoBuild).toBe(false)
  })
})

describe('voices and unattached narration', () => {
  it('a renamed voice is sent as a rename, so references follow it', async () => {
    const server = new FakeServer()
    const { editor } = await setup(server)
    editor.snapshot = {
      ...editor.snapshot!,
      voices: { map: { lecturer: { kokoro: 'am_michael' } }, default_voice: 'lecturer', names: ['lecturer'],
        resolved: { lecturer: 'am_michael' } },
    }
    const w = mount(VoicesDialog, { props: { open: false }, attachTo: document.body })
    await w.setProps({ open: true })
    await flushPromises()
    const name = document.querySelector<HTMLInputElement>('[data-testid^="voice-name-"]')!
    name.value = 'narrator'
    name.dispatchEvent(new Event('input'))
    await flushPromises()
    document.querySelector<HTMLButtonElement>('[data-testid="voice-save"]')!.click()
    await flushPromises()
    expect(server.commands[0]).toMatchObject({
      type: 'edit_voices',
      voices: { narrator: { kokoro: 'am_michael' } },
      default_voice: 'narrator',
      renames: { lecturer: 'narrator' },
    })
  })

  it('attaches unattached narration to an empty slide', async () => {
    const server = new FakeServer({ a: 'Kept.', gone: 'From a dropped slide.' })
    const { editor } = await setup(server)
    editor.snapshot = { ...editor.snapshot!, orphans: ['gone'] }
    const w = mount(OrphanTray, { attachTo: document.body })
    expect(w.text()).toContain('From a dropped slide.')
    await w.get('[data-testid="orphan-attach-gone"]').trigger('click')
    await flushPromises()
    document.querySelector<HTMLButtonElement>('[data-testid="attach-confirm"]')!.click()
    await flushPromises()
    expect(server.commands[0]).toMatchObject({ type: 'attach_orphan', orphan_id: 'gone', target_id: 'b' })
  })
})
