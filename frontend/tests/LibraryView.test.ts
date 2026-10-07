import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient, ApiError } from '@/api/client'
import LibraryView from '@/features/library/LibraryView.vue'
import { useLibraryStore } from '@/stores/library'

import { library } from './fixtures'

function fakeClient(overrides: Partial<ApiClient> = {}): ApiClient {
  const client = new ApiClient({ fetch: async () => new Response('{}') })
  client.library = vi.fn(async () => library())
  client.setLibraryRoot = vi.fn(async () => ({ ...library(), root: 'teaching', parents: ['~'] }))
  client.deckStats = vi.fn(async (token: string) =>
    token === 'p'
      ? Promise.reject(new Error('broken'))
      : { token, slides: 4, narrated: token === 'l' ? 4 : 1, errors: 0, warnings: 0 },
  )
  return Object.assign(client, overrides)
}

async function mountLibrary(client = fakeClient()) {
  setActivePinia(createPinia())
  const store = useLibraryStore()
  store.client = client
  const wrapper = mount(LibraryView, { attachTo: document.body })
  await flushPromises()
  return { wrapper, store, client }
}

describe('LibraryView', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('lists decks as links into the editor, with their size filled in', async () => {
    const { wrapper } = await mountLibrary()
    expect(wrapper.get('[data-testid="library-count"]').text()).toBe('4 decks')
    const card = wrapper.get('[data-testid="deck-card-l"]')
    expect(card.attributes('href')).toBe('/d/l')
    expect(card.text()).toContain('4 slides')
    expect(card.text()).not.toMatch(/complete|narrate/)
    expect(wrapper.get('[data-testid="deck-card-p"]').text()).toContain('can’t be read')
    expect(wrapper.findAll('h2').map((h) => h.text())).toEqual(['week02 2'])
  })

  it('filters as you type and opens the highlighted deck with Enter', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    const { wrapper } = await mountLibrary()
    const input = wrapper.get('[data-testid="library-search"]')
    await input.setValue('week02')
    expect(wrapper.findAll('a.row')).toHaveLength(2)
    await input.trigger('keydown', { key: 'ArrowDown' })
    await input.trigger('keydown', { key: 'Enter' })
    expect(assign).toHaveBeenCalledWith('/d/p')
    vi.unstubAllGlobals()
  })

  it('shows PDFs without narration with the command that starts one', async () => {
    const { wrapper } = await mountLibrary()
    const bare = wrapper.get('[data-testid="library-unnarrated"]')
    expect(bare.text()).toContain('slidesonnet init week03/draft.pdf')
  })

  it('explains an empty folder, and rescans on request', async () => {
    const empty = { ...library(), sections: [], unnarrated: [] }
    const client = fakeClient({ library: vi.fn(async () => empty) })
    const { wrapper } = await mountLibrary(client)
    expect(wrapper.get('[data-testid="library-empty"]').text()).toContain('No decks under this folder')
    await wrapper.get('[data-testid="library-rescan"]').trigger('click')
    expect(client.library).toHaveBeenLastCalledWith({ rescan: true })
  })

  it('moves up to a folder above, or into a week, and lists its decks', async () => {
    const { wrapper, client } = await mountLibrary()
    const crumbs = wrapper.get('[data-testid="library-path"]')
    expect(crumbs.text()).toMatch(/~\s*\/\s*teaching\s*\/\s*course/)

    await wrapper.get('[data-testid="library-up"]').trigger('click')
    await flushPromises()
    expect(client.setLibraryRoot).toHaveBeenLastCalledWith('..')
    expect(wrapper.get('[data-testid="library-path"]').text()).toMatch(/~\s*\/\s*teaching$/)

    await wrapper.get('[data-testid="library-crumb-0"]').trigger('click') // ~
    expect(client.setLibraryRoot).toHaveBeenLastCalledWith('..')
    await wrapper.get('button[data-testid="library-open-week02"]').trigger('click')
    expect(client.setLibraryRoot).toHaveBeenLastCalledWith('week02')
  })

  it('says plainly when a folder can’t be opened, and keeps the list', async () => {
    const client = fakeClient({
      setLibraryRoot: vi.fn(async () => {
        throw new ApiError(404, 'folder_not_found', 'There is no folder at “..”.')
      }),
    })
    const { wrapper } = await mountLibrary(client)
    await wrapper.get('[data-testid="library-up"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('There is no folder at “..”.')
    expect(wrapper.get('[data-testid="library-count"]').text()).toBe('4 decks')
  })
})
