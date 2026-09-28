<script setup lang="ts">
// The console's Review tab: the Deck conversation (instructions about the whole
// deck), this slide's conversations (reply / accept / reopen, and a note box
// that opens a new one), and every conversation (click one to focus on its
// slides). Every note is sent to the agent at once.
import { computed } from 'vue'

import type { ConversationDTO } from '@/api/client'
import { useEditorStore } from '@/stores/editor'
import { useReviewStore } from '@/stores/review'

import NoteBox from './NoteBox.vue'

const editor = useEditorStore()
const review = useReviewStore()

const AUTHOR: Record<string, string> = { author: 'You', agent: 'Agent', system: 'Note' }

function turnLabel(c: ConversationDTO): string {
  if (c.status === 'closed') return 'accepted'
  return c.turn === 'author' ? 'your turn' : "agent's turn"
}
function originLabel(c: ConversationDTO): string {
  return c.origin === 'unrequested' ? ' · unrequested' : c.origin === 'author-edits' ? ' · your edits' : ''
}

const subject = computed(() => review.subject)
const change = computed(() => review.changes.get(subject.value) ?? null)
const changeText = computed(() => {
  const c = change.value
  if (!c) return ''
  const detail = [c.image ? 'slide' : '', c.narration ? 'narration' : ''].filter(Boolean)
  let text = c.kinds.join(', ')
  if (c.moved && c.base_index !== null) text += ` (was slide ${c.base_index + 1})`
  if (detail.length) text += ' — ' + detail.join(', ')
  return text
})
const here = computed(() =>
  review
    .conversationsFor(subject.value)
    .filter((c) => c.status === 'open' || review.showClosed)
    .sort((a, b) => Number(a.status !== 'open') - Number(b.status !== 'open') || a.id.localeCompare(b.id)),
)
const listed = computed(() =>
  review.slideConversations.filter((c) => c.status === 'open' || review.showClosed || c.id === review.filter),
)
const pendingHere = computed(() => Object.keys(review.data?.pending ?? {}))

function time(at: string): string {
  return at.slice(11, 16)
}
</script>

<template>
  <section class="review" data-testid="review-panel">
    <template v-if="!review.data || !review.active">
      <p v-if="!review.data && review.comparing" class="dim-text">Loading…</p>
      <template v-else>
        <button class="btn" type="button" data-testid="review-start" @click="review.command({ type: 'start' })">
          Start review
        </button>
        <p class="hint">
          Compare the next changes against the deck as it is now, slide by slide, and talk them
          over with the agent.
        </p>
      </template>
    </template>

    <template v-else>
      <div class="row">
        <h3 class="section-title">Review</h3>
        <span class="spacer"></span>
        <span v-if="review.comparing" class="dim-text small">comparing…</span>
        <button
          class="btn quiet small"
          type="button"
          :disabled="review.closedCount === 0"
          title="Make accepted changes the new starting point"
          data-testid="review-clear"
          @click="review.command({ type: 'clear' })"
        >
          Clear accepted ({{ review.closedCount }})
        </button>
      </div>
      <label v-if="review.closedCount || review.showClosed" class="check small">
        <input v-model="review.showClosed" type="checkbox" data-testid="review-show-closed" />
        Show closed ({{ review.closedCount }})
      </label>
      <p v-if="review.data.final_build" class="warn-text small">
        Final build — comparison paused until the next normal compile.
      </p>
      <p v-if="pendingHere.length" class="warn-text small" data-testid="review-pending">
        Not in the PDF yet: {{ pendingHere.map((s) => `@${s}`).join(', ') }} — compile, or fix the id.
      </p>

      <details v-if="review.deckConversation" class="deck" open>
        <summary class="section-title">Deck</summary>
        <ul class="messages">
          <li v-for="(m, i) in review.deckConversation.messages" :key="i" :class="m.author">
            <span class="meta">{{ AUTHOR[m.author] }} · {{ time(m.at) }}</span>
            <span class="text" dir="auto">{{ m.text }}</span>
          </li>
        </ul>
        <NoteBox
          test-id="deck-note"
          placeholder="Instructions for the agent about the whole deck…"
          @send="(text) => review.command({ type: 'reply', conversation: 'deck', text })"
        />
      </details>

      <section v-if="subject" class="slide">
        <h3 class="section-title">
          This slide <span class="mono">@{{ subject }}</span>
          <span v-if="review.viewingRemoved" class="err-text"> · removed</span>
        </h3>
        <p v-if="change" class="warn-text small" data-testid="review-change">Changed: {{ changeText }}</p>
        <article v-for="c in here" :key="c.id" class="conv" :data-testid="`conv-${c.id}`">
          <header class="meta">{{ c.id }} · {{ turnLabel(c) }}{{ originLabel(c) }}</header>
          <ul class="messages">
            <li v-for="(m, i) in c.messages" :key="i" :class="m.author">
              <span class="meta">{{ AUTHOR[m.author] }} · {{ time(m.at) }}</span>
              <span class="text" dir="auto">{{ m.text }}</span>
            </li>
          </ul>
          <template v-if="c.status === 'open'">
            <NoteBox
              :test-id="`reply-${c.id}`"
              placeholder="Reply…"
              @send="(text) => review.command({ type: 'reply', conversation: c.id, text })"
            />
            <button
              class="btn quiet small"
              type="button"
              title="Close this conversation — its changes are accepted"
              :data-testid="`accept-${c.id}`"
              @click="review.command({ type: 'accept', conversation: c.id })"
            >
              Accept
            </button>
          </template>
          <button
            v-else
            class="btn quiet small"
            type="button"
            :data-testid="`reopen-${c.id}`"
            @click="review.command({ type: 'reopen', conversation: c.id })"
          >
            Reopen
          </button>
        </article>
        <NoteBox
          test-id="slide-note"
          placeholder="New note for the agent about this slide…"
          @send="(text) => review.command({ type: 'comment', slides: [subject], text })"
        />
      </section>

      <section v-if="listed.length" class="list">
        <div class="row">
          <h3 class="section-title">Conversations</h3>
          <span class="spacer"></span>
          <button
            v-if="review.filter"
            class="btn quiet small"
            type="button"
            data-testid="conv-filter-clear"
            @click="review.filter = null"
          >
            Show all slides
          </button>
        </div>
        <button
          v-for="c in listed"
          :key="c.id"
          class="conv-row"
          :class="{ active: c.id === review.filter }"
          type="button"
          :data-testid="`conv-row-${c.id}`"
          @click="review.select(c.id)"
        >
          {{ c.id }} · {{ turnLabel(c) }}{{ originLabel(c) }} · {{ c.slides.map((s) => `@${s}`).join(' ') }}
        </button>
      </section>
      <p v-if="editor.snapshot && !review.data" class="dim-text small">Comparing…</p>
    </template>
  </section>
</template>

<style scoped>
.review {
  display: grid;
  gap: var(--space-3);
  align-content: start;
}
.row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.spacer {
  flex: 1;
}
.small {
  font-size: var(--text-xs);
}
.btn.small {
  min-height: 26px;
  padding: 0 var(--space-2);
}
.hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--dim);
}
.deck summary {
  cursor: pointer;
  margin-bottom: var(--space-2);
}
.slide,
.list {
  display: grid;
  gap: var(--space-2);
}
.conv {
  display: grid;
  gap: var(--space-1);
  padding-left: var(--space-2);
  border-left: 2px solid var(--line);
}
.messages {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.messages li {
  display: grid;
}
.meta {
  font-size: var(--text-xs);
  color: var(--dim);
}
.text {
  font-size: var(--text-md);
  white-space: pre-wrap;
}
.messages .system .text {
  color: var(--dim);
  font-style: italic;
}
.messages .agent .text {
  color: var(--accent);
}
.conv-row {
  padding: 3px var(--space-2);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  color: var(--text);
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
}
.conv-row:hover {
  background: var(--raised);
}
.conv-row.active {
  border-color: var(--accent);
}
</style>
