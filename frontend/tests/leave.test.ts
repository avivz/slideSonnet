// Leaving a deck by any route (switcher, library link, back/forward) saves
// first, and stays when the narration can't be saved.
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'

import { ApiError } from '@/api/client'
import { useLeaveGuard } from '@/features/editor/leave'
import { useEditorStore } from '@/stores/editor'

import { FakeServer } from './fakeServer'

const Deck = defineComponent({
  setup() {
    useLeaveGuard()
    return () => h('p', 'deck')
  },
})

async function onDeck() {
  setActivePinia(createPinia())
  const editor = useEditorStore()
  editor.client = new FakeServer().client()
  const leftFor: unknown[] = []
  editor.client.cancelGeneration = async (_t, body) => {
    leftFor.push(body)
    return { count: 0 }
  }
  await editor.open('a')
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { render: () => h('p', 'library') } },
      { path: '/d/:token', component: Deck },
    ],
  })
  await router.push('/d/a')
  mount({ render: () => h(RouterView) }, { global: { plugins: [router] } })
  const line = editor.draftFor('a')?.middle[0]
  if (line) line.text = 'Typed, not saved yet.'
  editor.touch('a')
  return { editor, router, leftFor }
}

describe('leaving a deck', () => {
  it('saves the typing, and lets go of this tab’s generation', async () => {
    const { editor, router, leftFor } = await onDeck()
    await router.push('/d/b')
    expect(router.currentRoute.value.path).toBe('/d/b')
    expect(editor.isDirty('a')).toBe(false)
    expect(leftFor).toHaveLength(1)
  })

  it('stays when the typing can’t be saved, by any way out', async () => {
    const { editor, router, leftFor } = await onDeck()
    editor.client.saveSlide = async () => {
      throw new ApiError(500, 'io', 'Disk full.')
    }
    await router.push('/d/b')
    await router.push('/')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/d/a')
    expect(editor.draftFor('a')?.middle[0]?.text).toBe('Typed, not saved yet.')
    expect(leftFor).toEqual([])
  })
})
