import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import type { ReviewDTO } from '@/api/client'
import ReviewPanel from '@/features/review/ReviewPanel.vue'
import SlideLinks from '@/features/review/SlideLinks.vue'
import { useEditorStore } from '@/stores/editor'
import { useReviewStore } from '@/stores/review'

import { FakeServer } from './fakeServer'

const REVIEW: ReviewDTO = {
  active: true,
  final_build: false,
  conversations: [
    { id: 'deck', title: '', slides: [], origin: 'requested', status: 'open', turn: 'author', is_deck: true, messages: [] },
    {
      id: 'c1', title: '', slides: ['b', 'gone'], origin: 'requested', status: 'open', turn: 'author', is_deck: false,
      messages: [{ author: 'agent', at: '2026-09-28T10:15:00', text: 'I reworded b.' }],
    },
    { id: 'c2', title: 'Shorter c', slides: ['c'], origin: 'requested', status: 'closed', turn: 'agent', is_deck: false, messages: [] },
  ],
  changes: [
    { slide_id: 'b', kinds: ['edited'], image: true, narration: true, moved: false, base_index: 1, current_index: 1 },
    { slide_id: 'gone', kinds: ['deleted'], image: false, narration: false, moved: false, base_index: 2, current_index: null },
  ],
  unfiled: [],
  pending: { zeta: ['c1'] },
  badges: { b: 'your-turn', c: 'closed' },
  base_order: ['a', 'b', 'gone', 'c'],
  base_images: { b: '/base/b.png', gone: '/base/gone.png' },
  diffs: { b: [['=', 'World'], ['+', 'again']] },
}

async function setup() {
  setActivePinia(createPinia())
  const server = new FakeServer({ a: 'A.', b: 'World.', c: 'C.' })
  const editor = useEditorStore()
  const client = server.client()
  const sent: unknown[] = []
  client.review = async () => REVIEW
  client.reviewCommand = async (_t, body) => {
    sent.push(body)
    return { message: 'Reply sent', conversation: null, count: 0, focus: false }
  }
  editor.client = client
  await editor.open('tok')
  const review = useReviewStore()
  await review.refresh()
  return { editor, review, sent }
}

describe('review store', () => {
  it('lays removed slides after their old predecessor in one strip', async () => {
    const { review } = await setup()
    expect(review.strip.map((it) => (it.kind === 'page' ? it.slideId : `-${it.slideId}`))).toEqual([
      'a', 'b', '-gone', 'c',
    ])
  })

  it('keeps the arrows inside a chosen conversation, removed slides included', async () => {
    const { editor, review } = await setup()
    review.select('c1')
    expect(editor.currentId).toBe('b')
    expect(review.step(1)).toBe(true)
    expect(review.viewingRemoved).toBe('gone') // the removed slide, shown from the base
    expect(review.step(1)).toBe(true) // c is outside c1: stay put
    expect(review.viewingRemoved).toBe('gone')
    review.step(-1)
    expect([review.viewingRemoved, editor.currentId]).toEqual([null, 'b'])
    review.filter = null
    expect(review.step(1)).toBe(false) // no conversation chosen: ordinary slide stepping
  })

  it('choosing a conversation shows one of its slides, even one since removed', async () => {
    const { editor, review } = await setup()
    review.data = {
      ...REVIEW,
      conversations: [
        ...REVIEW.conversations,
        { id: 'c3', title: '', slides: ['gone'], origin: 'requested', status: 'closed', turn: 'agent', is_deck: false, messages: [] },
      ],
    }
    review.select('c3') // its only slide was deleted: show it from the base
    expect([review.viewingRemoved, editor.currentId]).toEqual(['gone', 'a'])
    review.select('c1') // already on one of c1's slides: stay
    expect(review.viewingRemoved).toBe('gone')
    review.select('c2')
    expect([review.viewingRemoved, editor.currentId]).toEqual([null, 'c'])
    review.toggle('c2') // choosing it again: back to every slide, staying here
    expect([review.filter, editor.currentId]).toEqual([null, 'c'])
    review.toggle('c1')
    expect(review.filter).toBe('c1')
  })

  it('jumps to the next slide waiting for you', async () => {
    const { editor, review } = await setup()
    review.nextYourTurn()
    expect(editor.currentId).toBe('b')
    expect(review.waitingHere).toBe(1)
  })
})

describe('review panel', () => {
  it('reads a conversation chosen from the list, replies with Enter, and accepts it from its row', async () => {
    const { editor, review, sent } = await setup()
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    expect(w.get('[data-testid="review-pending"]').text()).toContain('@zeta')
    expect(w.get('[data-testid="conv-row-c1"]').text()).toContain('I reworded b.') // untitled: its first words
    expect(w.find('[data-testid="conv-row-c2"]').exists()).toBe(false) // accepted: hidden
    await w.get('[data-testid="conv-row-c1"]').trigger('click')
    expect(editor.currentId).toBe('b') // the strip follows to one of its slides
    expect(review.scope).toEqual(new Set(['b', 'gone']))
    const reply = w.get('[data-testid="reply-c1"]')
    await reply.setValue('Looks good.')
    await reply.trigger('keydown', { key: 'Enter' })
    await w.get('[data-testid="accept-c1"]').trigger('click')
    await vi.waitFor(() => expect(sent).toHaveLength(2))
    expect(sent).toEqual([
      { type: 'reply', conversation: 'c1', text: 'Looks good.' },
      { type: 'accept', conversation: 'c1' },
    ])
  })

  it('the whole-deck conversation sits in the list, and choosing it greys nothing out', async () => {
    const { review, sent } = await setup()
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    await w.get('[data-testid="conv-row-deck"]').trigger('click')
    expect(review.scope).toBeNull()
    const note = w.get('[data-testid="reply-deck"]')
    await note.setValue('Publish these.')
    await note.trigger('keydown', { key: 'Enter' })
    await vi.waitFor(() => expect(sent).toEqual([{ type: 'reply', conversation: 'deck', text: 'Publish these.' }]))
  })

  it('opens a new conversation about this slide, or the slides Ctrl-clicked in the strip', async () => {
    const { editor, review, sent } = await setup()
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    expect(w.find('[data-testid="new-slide-a"]').exists()).toBe(true) // this slide, by default
    editor.goToSlide('b')
    await flushPromises()
    expect(w.find('[data-testid="new-slide-b"]').exists()).toBe(true) // follows the slide shown
    review.pick('c') // Ctrl-click: b (on screen) and c
    await flushPromises()
    expect(review.newSlides).toEqual(['b', 'c'])
    editor.goToSlide('a')
    expect(review.newSlides).toEqual(['b', 'c']) // tagged by hand: moving doesn't change them
    await w.get('[data-testid="new-slide-remove-b"]').trigger('click')
    const note = w.get('[data-testid="new-note"]')
    await note.setValue('Merge these?')
    await note.trigger('keydown', { key: 'Enter' })
    await vi.waitFor(() => expect(sent).toEqual([{ type: 'comment', slides: ['c'], text: 'Merge these?' }]))
    await flushPromises()
    expect(review.newSlides).toEqual(['a']) // sent: back to the slide on screen
  })

  it('renames the chosen conversation', async () => {
    const { review, sent } = await setup()
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    review.select('c1')
    await flushPromises()
    await w.get('[data-testid="conv-rename"]').trigger('click')
    const input = w.get('[data-testid="conv-title-input"]')
    await input.setValue('Why b changed')
    await input.trigger('keydown', { key: 'Enter' })
    await vi.waitFor(() => expect(sent).toEqual([{ type: 'retitle', conversation: 'c1', title: 'Why b changed' }]))
  })

  it('resets the comparison after asking, leaving the conversations alone', async () => {
    const { sent } = await setup()
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    const ask = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    await w.get('[data-testid="review-reset"]').trigger('click')
    expect(sent).toEqual([]) // said no
    await w.get('[data-testid="review-reset"]').trigger('click')
    await vi.waitFor(() => expect(sent).toEqual([{ type: 'mark_seen' }]))
    expect(ask).toHaveBeenCalledTimes(2)
  })
})

describe('the line under the slide', () => {
  it('links the slide\'s conversations and says what changed', async () => {
    const { editor, review } = await setup()
    editor.goToSlide('b')
    const w = mount(SlideLinks, { attachTo: document.body })
    await flushPromises()
    expect(w.get('[data-testid="review-change"]').text()).toContain('slide, narration')
    const asked = review.panelRequests
    await w.get('[data-testid="slide-link-c1"]').trigger('click')
    expect(review.filter).toBe('c1')
    expect(review.panelRequests).toBe(asked + 1) // the Review tab opens on it
  })
})
