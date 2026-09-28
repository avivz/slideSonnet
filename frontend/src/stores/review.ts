// Review of the open deck: conversations with the agent, what changed since
// the base, and the editor's review views (compare, filter to a conversation,
// look at a removed slide). Writes go to the server as the author.
import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import { ApiError, type ConversationDTO, type ReviewCommand, type ReviewDTO } from '@/api/client'
import { useEditorStore } from '@/stores/editor'

export type Badge = 'your-turn' | 'agent-turn' | 'closed' | 'unfiled'

/** One filmstrip tile: a current page, or a slide removed since the base. */
export type StripItem = { kind: 'page'; index: number; slideId: string } | { kind: 'removed'; slideId: string }

export const useReviewStore = defineStore('review', () => {
  const editor = useEditorStore()
  const data = shallowRef<ReviewDTO | null>(null)
  const comparing = ref(false)
  /** The chosen conversation: other slides dim and the arrows stay inside it. */
  const filter = ref<string | null>(null)
  const showClosed = ref(false)
  /** D: the base version full-size instead of side by side. */
  const beforeOnly = ref(false)
  /** A removed slide shown on the stage (its base version). */
  const viewingRemoved = ref<string | null>(null)
  let loadedFor: string | null = null

  const active = computed(() => data.value?.active ?? false)
  const conversations = computed(() => data.value?.conversations ?? [])
  const deckConversation = computed(() => conversations.value.find((c) => c.is_deck) ?? null)
  const slideConversations = computed(() => conversations.value.filter((c) => !c.is_deck))
  const changes = computed(() => new Map((data.value?.changes ?? []).map((c) => [c.slide_id, c])))
  const removed = computed(() => (data.value?.changes ?? []).filter((c) => c.current_index === null).map((c) => c.slide_id))
  /** The slide the review tools are about: a removed one being looked at, else the open one. */
  const subject = computed(() => viewingRemoved.value ?? editor.currentId)
  const scope = computed(() => {
    const conv = conversations.value.find((c) => c.id === filter.value)
    return conv ? new Set(conv.slides) : null
  })

  function conversationsFor(slideId: string): ConversationDTO[] {
    return slideConversations.value.filter((c) => c.slides.includes(slideId))
  }
  function badge(slideId: string): Badge | null {
    return (data.value?.badges?.[slideId] as Badge | undefined) ?? null
  }
  const waitingHere = computed(
    () => conversationsFor(subject.value).filter((c) => c.status === 'open' && c.turn === 'author').length,
  )
  const closedCount = computed(() => slideConversations.value.filter((c) => c.status === 'closed').length)

  /** One filmstrip in the current order; a removed slide sits after its old predecessor. */
  const strip = computed<StripItem[]>(() => {
    const pages = editor.pages
    const items: StripItem[] = []
    const after = new Map<number, string[]>()
    if (active.value && removed.value.length) {
      const position = new Map(pages.map((p, i) => [p.slide_id, i]))
      const gone = new Set(removed.value)
      let anchor = -1
      for (const sid of data.value?.base_order ?? []) {
        const at = position.get(sid)
        if (at !== undefined) anchor = at
        else if (gone.has(sid)) after.set(anchor, [...(after.get(anchor) ?? []), sid])
      }
    }
    for (const sid of after.get(-1) ?? []) items.push({ kind: 'removed', slideId: sid })
    pages.forEach((p, index) => {
      items.push({ kind: 'page', index, slideId: p.slide_id })
      for (const sid of after.get(index) ?? []) items.push({ kind: 'removed', slideId: sid })
    })
    return items
  })

  // ---- loading ---------------------------------------------------------------
  async function refresh(): Promise<void> {
    const token = editor.token
    if (token === null) return
    if (loadedFor !== token) {
      data.value = null
      filter.value = null
      viewingRemoved.value = null
      loadedFor = token
    }
    comparing.value = true
    try {
      data.value = await editor.client.review(token)
      // the chosen conversation was cleared, or accepted while closed ones are hidden: show every slide
      const chosen = conversations.value.find((c) => c.id === filter.value)
      if (filter.value !== null && (!chosen || (chosen.status === 'closed' && !showClosed.value))) filter.value = null
    } catch (e) {
      if (e instanceof ApiError) editor.flash(e.message, 'warn')
    } finally {
      comparing.value = false
    }
  }

  async function command(body: ReviewCommand): Promise<boolean> {
    const token = editor.token
    if (token === null) return false
    await editor.flush() // the agent should see the saved narration
    try {
      const outcome = await editor.client.reviewCommand(token, body)
      if (outcome.message) editor.flash(outcome.message, body.type === 'file_unrequested' ? 'warn' : 'ok')
      if (outcome.focus && outcome.conversation) filter.value = outcome.conversation
      await refresh()
      return true
    } catch (e) {
      editor.flash(e instanceof ApiError ? e.message : 'The review couldn’t be updated.', 'warn')
      return false
    }
  }

  /** After a recompile or an outside narration edit: file what changed unasked. */
  async function fileUnrequested(): Promise<void> {
    if (active.value) await command({ type: 'file_unrequested' })
  }

  // ---- navigation within review ---------------------------------------------------
  function viewRemoved(slideId: string): void {
    void editor.flush()
    viewingRemoved.value = slideId
  }
  function leaveRemoved(): void {
    viewingRemoved.value = null
  }

  /** Clicking a slide outside the chosen conversation leaves that view. */
  function leaveFilterFor(slideId: string): void {
    if (scope.value !== null && !scope.value.has(slideId)) filter.value = null
  }

  /** Arrows: through the chosen conversation's slides, or off a removed one. False = not ours. */
  function step(delta: number): boolean {
    if (scope.value === null && viewingRemoved.value === null) return false
    const items = strip.value
    const here = subject.value
    const pos = items.findIndex((it) => it.slideId === here)
    if (pos < 0) return false
    for (let k = pos + delta; k >= 0 && k < items.length; k += delta) {
      const it = items[k] as StripItem
      if (scope.value === null && it.kind === 'page') {
        leaveRemoved()
        editor.go(it.index)
        return true
      }
      if (scope.value !== null && scope.value.has(it.slideId)) {
        if (it.kind === 'page') {
          leaveRemoved()
          editor.go(it.index)
        } else {
          viewRemoved(it.slideId)
        }
        return true
      }
    }
    return true // the end of the conversation (or strip): stay put
  }

  /** Focus on a conversation and show one of its slides (staying put when already on one). */
  function select(conversation: string): void {
    filter.value = conversation
    const slides = conversations.value.find((c) => c.id === conversation)?.slides ?? []
    if (slides.includes(subject.value)) return
    const live = slides.find((s) => editor.pages.some((p) => p.slide_id === s))
    if (live) {
      leaveRemoved()
      editor.goToSlide(live)
      return
    }
    // every slide it names was deleted since the review started: show one from the base
    const gone = slides.find((s) => removed.value.includes(s))
    if (gone) viewRemoved(gone)
  }

  /** The list's click: choose a conversation, or choose it again to see every slide. */
  function toggle(conversation: string): void {
    if (filter.value === conversation) filter.value = null
    else select(conversation)
  }

  function nextYourTurn(): void {
    const pages = editor.pages
    for (let step_ = 1; step_ <= pages.length; step_++) {
      const i = (editor.index + step_) % pages.length
      if (badge(pages[i]?.slide_id ?? '') === 'your-turn') {
        leaveRemoved()
        editor.go(i)
        return
      }
    }
    editor.flash('Nothing waiting for you')
  }

  return {
    data, comparing, filter, showClosed, beforeOnly, viewingRemoved, active, conversations,
    deckConversation, slideConversations, changes, removed, subject, scope, waitingHere, closedCount,
    strip,
    conversationsFor, badge, refresh, command, fileUnrequested, viewRemoved, leaveRemoved,
    leaveFilterFor, step, select, toggle, nextYourTurn,
  }
})
