import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import type { ReviewDTO } from '@/api/client'
import ReviewPanel from '@/features/review/ReviewPanel.vue'
import { useEditorStore } from '@/stores/editor'
import { useReviewStore } from '@/stores/review'

import { FakeServer } from './fakeServer'

const REVIEW: ReviewDTO = {
  active: true,
  final_build: false,
  conversations: [
    { id: 'deck', slides: [], origin: 'requested', status: 'open', turn: 'author', is_deck: true, messages: [] },
    {
      id: 'c1', slides: ['b', 'gone'], origin: 'requested', status: 'open', turn: 'author', is_deck: false,
      messages: [{ author: 'agent', at: '2026-09-28T10:15:00', text: 'I reworded b.' }],
    },
    { id: 'c2', slides: ['c'], origin: 'requested', status: 'closed', turn: 'agent', is_deck: false, messages: [] },
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
        { id: 'c3', slides: ['gone'], origin: 'requested', status: 'closed', turn: 'agent', is_deck: false, messages: [] },
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
  it('replies with Enter, accepts, and lists what isn’t compiled yet', async () => {
    const { editor, sent } = await setup()
    editor.goToSlide('b')
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    expect(w.get('[data-testid="review-pending"]').text()).toContain('@zeta')
    expect(w.get('[data-testid="conv-c1"]').text()).toContain('I reworded b.')
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

  it('keeps a half-written note with the slide it was started on', async () => {
    // playback (or the arrows) can move the editor mid-sentence: the note must
    // neither follow to the new slide nor be lost
    const { editor, sent } = await setup()
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    await w.get('[data-testid="slide-note"]').setValue('Too long.')
    editor.goToSlide('b')
    await flushPromises()
    expect((w.get('[data-testid="slide-note"]').element as HTMLTextAreaElement).value).toBe('')
    editor.goToSlide('a')
    await flushPromises()
    const note = w.get('[data-testid="slide-note"]')
    expect((note.element as HTMLTextAreaElement).value).toBe('Too long.')
    await note.trigger('keydown', { key: 'Enter' })
    await vi.waitFor(() => expect(sent).toEqual([{ type: 'comment', slides: ['a'], text: 'Too long.' }]))
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
