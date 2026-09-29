import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ReviewDTO } from '@/api/client'
import ReviewPanel from '@/features/review/ReviewPanel.vue'
import SlideLinks from '@/features/review/SlideLinks.vue'
import WaitingBanner from '@/features/review/WaitingBanner.vue'
import { useConfirm } from '@/stores/confirm'
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
  it('shows clearing progress, blocks duplicate clears, and recovers after failure', async () => {
    const { editor, review } = await setup()
    let reject!: (reason: Error) => void
    const request = vi.spyOn(editor.client, 'reviewCommand').mockImplementation(
      () => new Promise((_resolve, rejectRequest) => { reject = rejectRequest }),
    )
    const w = mount(ReviewPanel)
    const clearing = review.command({ type: 'clear' })
    await flushPromises()
    const button = w.get('[data-testid="review-clear"]')
    expect(button.text()).toBe('Clearing…')
    expect(button.attributes('disabled')).toBeDefined()
    expect(await review.command({ type: 'clear' })).toBe(false)
    expect(request).toHaveBeenCalledTimes(1)
    reject(new Error('Failed'))
    expect(await clearing).toBe(false)
    await flushPromises()
    expect(review.clearing).toBe(false)
    expect(button.attributes('disabled')).toBeUndefined()
    w.unmount()
  })

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

  it('the author’s own edits carry no review markings, unless someone else changed the slide too', async () => {
    const { editor, review } = await setup()
    review.data = {
      ...REVIEW,
      conversations: [
        ...REVIEW.conversations,
        { id: 'c9', title: '', slides: ['a', 'c'], origin: 'author-edits', status: 'closed', turn: 'agent', is_deck: false, messages: [] },
      ],
      changes: [
        ...REVIEW.changes,
        { slide_id: 'a', kinds: ['edited'], image: false, narration: true, moved: false, base_index: 0, current_index: 0 },
      ],
      badges: { ...REVIEW.badges, a: 'closed' },
      diffs: { ...REVIEW.diffs, a: [['-', 'Hi'], ['+', 'A.']] },
    }
    // a: only my edits — no badge, no diff box, no conversation link, no "changed:" line
    expect([review.badge('a'), review.diffFor('a'), review.conversationsFor('a')]).toEqual([null, null, []])
    const w = mount(SlideLinks)
    await flushPromises()
    expect(w.find('[data-testid="slide-links"]').exists()).toBe(false)
    // c: also in an agent's conversation — marked as before (my edits' link stays out of it)
    expect(review.badge('c')).toBe('closed')
    expect(review.conversationsFor('c').map((c) => c.id)).toEqual(['c2'])
    editor.goToSlide('b')
    expect(review.diffFor('b')).toEqual([['=', 'World'], ['+', 'again']])
  })

  it('jumps to the next slide waiting for you', async () => {
    const { editor, review } = await setup()
    review.nextYourTurn()
    expect(editor.currentId).toBe('b')
  })

  it('counts what waits for you across the whole deck, and a banner leads to it', async () => {
    const { editor, review } = await setup()
    expect(editor.currentId).toBe('a') // c1 waits on b, not here
    expect(review.waitingCount).toBe(1) // the whole-deck one has nothing from the agent: not waiting
    const w = mount(WaitingBanner)
    await flushPromises()
    expect(w.text()).toContain('The agent is waiting for you on 2 slides')
    const asked = review.panelRequests
    await w.get('[data-testid="waiting-show"]').trigger('click')
    expect([review.filter, editor.currentId, review.panelRequests]).toEqual(['c1', 'b', asked + 1])
    expect(w.find('[data-testid="waiting-banner"]').exists()).toBe(false) // shown: it goes
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

  it('keeps a note that failed to send, and doesn’t send mid-composition', async () => {
    const { editor, sent } = await setup()
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    const note = w.get('[data-testid="new-note"]')
    await note.setValue('Shorter, please.')
    await note.trigger('keydown', { key: 'Enter', isComposing: true }) // choosing an IME candidate
    await flushPromises()
    expect(sent).toEqual([])
    editor.client.reviewCommand = async () => {
      throw new ApiError(503, 'busy', 'The review is busy.')
    }
    await note.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect((note.element as HTMLTextAreaElement).value).toBe('Shorter, please.') // not lost
  })

  it('the whole-deck conversation sits in the list, and choosing it greys nothing out', async () => {
    const { review, sent } = await setup()
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    expect(w.get('[data-testid="conv-row-deck"]').text()).not.toContain('your turn') // nothing waits in it
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

  it('always keeps a slide tagged: untagging the last goes back to the slide on screen', async () => {
    const { editor, review } = await setup()
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    expect(w.find('[data-testid="new-slide-remove-a"]').exists()).toBe(false) // the only tag: no ×
    review.pick('b')
    review.pick('b') // Ctrl-click b again: untagged
    expect(review.newSlides).toEqual(['a'])
    review.pick('a') // and a: nothing tagged by hand is left
    editor.goToSlide('c')
    expect(review.newSlides).toEqual(['c']) // follows the slide on screen again
    review.pick('a')
    await flushPromises()
    await w.get('[data-testid="new-reset"]').trigger('click') // Back to this slide
    expect(review.newSlides).toEqual(['c'])
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

  it.each([
    ['review-reset', { type: 'mark_seen' }],
    ['review-clear', { type: 'clear' }],
  ])('%s acts only after asking', async (button, command) => {
    const { review, sent } = await setup()
    review.showClosed = true // c2 is accepted: Clear has one to clear
    const w = mount(ReviewPanel, { attachTo: document.body })
    await flushPromises()
    const ask = vi.spyOn(useConfirm(), 'ask').mockResolvedValueOnce(false).mockResolvedValueOnce(true)
    await w.get(`[data-testid="${button}"]`).trigger('click')
    await flushPromises()
    expect(sent).toEqual([]) // said no
    await w.get(`[data-testid="${button}"]`).trigger('click')
    await vi.waitFor(() => expect(sent).toEqual([command]))
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
