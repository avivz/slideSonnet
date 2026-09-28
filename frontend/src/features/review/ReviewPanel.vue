<script setup lang="ts">
// The console's Review tab: the Deck conversation (instructions about the whole
// deck), this slide's conversations (reply / accept / reopen, and a note box
// that opens a new one), and every conversation (click one to focus on its
// slides). Every note is sent to the agent at once.
import { computed, reactive, ref } from 'vue'

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
  review.slideConversations.filter((c) => c.status === 'open' || review.showClosed),
)
const pendingHere = computed(() => Object.keys(review.data?.pending ?? {}))

// Unsent notes stay with what they're about: moving to another slide (the
// arrows, or playback following along) neither carries a note along nor loses it.
const deckOpen = ref(false) // whole-deck notes are occasional: start folded away
const deckCount = computed(() => review.deckConversation?.messages.length ?? 0)
const slideNotes = reactive(new Map<string, string>())
const replies = reactive(new Map<string, string>())

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
      <header class="head">
        <div class="row">
          <h2 class="head-title">Review</h2>
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
        <div class="row">
          <label v-if="review.closedCount || review.showClosed" class="check small">
            <input v-model="review.showClosed" type="checkbox" data-testid="review-show-closed" />
            Show closed ({{ review.closedCount }})
          </label>
          <span class="spacer"></span>
          <button
            v-if="review.deckConversation"
            class="btn quiet small"
            type="button"
            :aria-expanded="deckOpen"
            data-testid="deck-toggle"
            @click="deckOpen = !deckOpen"
          >
            {{ deckOpen ? '▾' : '▸' }} Note on the whole deck{{ deckCount ? ` (${deckCount})` : '' }}
          </button>
        </div>
        <div v-if="deckOpen && review.deckConversation" class="deck">
          <ul v-if="deckCount" class="messages">
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
        </div>
        <p v-if="review.data.final_build" class="warn-text small">
          Final build — comparison paused until the next normal compile.
        </p>
        <p v-if="pendingHere.length" class="warn-text small" data-testid="review-pending">
          Not in the PDF yet: {{ pendingHere.map((s) => `@${s}`).join(', ') }} — compile, or fix the id.
        </p>
      </header>


      <section v-if="subject" class="box slide">
        <h3 class="box-title">
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
              :model-value="replies.get(c.id) ?? ''"
              :test-id="`reply-${c.id}`"
              placeholder="Reply…"
              @update:model-value="(v) => replies.set(c.id, v)"
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
          :model-value="slideNotes.get(subject) ?? ''"
          test-id="slide-note"
          placeholder="New note for the agent about this slide…"
          @update:model-value="(v) => slideNotes.set(subject, v)"
          @send="(text) => review.command({ type: 'comment', slides: [subject], text })"
        />
      </section>

      <section v-if="listed.length" class="box list">
        <div class="row">
          <h3 class="box-title">Conversations</h3>
        </div>
        <div class="rows">
          <button
            class="conv-row all"
            :class="{ active: review.filter === null }"
            type="button"
            :aria-pressed="review.filter === null"
            data-testid="conv-row-all"
            @click="review.filter = null"
          >
            <span class="conv-id">All slides</span>
            <span class="conv-state">no conversation chosen</span>
          </button>
          <button
            v-for="c in listed"
            :key="c.id"
            class="conv-row"
            :class="{ active: c.id === review.filter }"
            type="button"
            :aria-pressed="c.id === review.filter"
            :title="c.id === review.filter ? 'Click again to see all slides' : 'Show this conversation’s slides'"
            :data-testid="`conv-row-${c.id}`"
            @click="review.toggle(c.id)"
          >
            <span class="conv-id mono">{{ c.id }}</span>
            <span class="conv-state" :class="c.status === 'closed' ? 'closed' : c.turn">
              {{ turnLabel(c) }}{{ originLabel(c) }}
            </span>
            <span class="conv-slides mono">{{ c.slides.map((s) => `@${s}`).join(' ') }}</span>
          </button>
        </div>
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
.head {
  display: grid;
  gap: var(--space-2);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--line);
}
.head-title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text);
}
/* each part of the panel sits in its own box */
.box {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
}
.box-title {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text);
}
.deck {
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
.rows {
  display: grid;
  border: 1px solid var(--line);
  border-radius: var(--radius-field);
  overflow: hidden;
}
.conv-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px var(--space-2);
  padding: var(--space-2);
  background: var(--surface);
  border: 0;
  border-top: 1px solid var(--line);
  color: var(--text);
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
}
.conv-row:first-child {
  border-top: 0;
}
.conv-row:hover {
  background: var(--raised);
}
.conv-row.active {
  background: var(--raised);
  box-shadow: inset 3px 0 0 var(--accent);
}
.conv-id {
  font-weight: 600;
}
.conv-state {
  color: var(--dim);
}
.conv-state.author {
  color: var(--warn);
}
.conv-slides {
  grid-column: 1 / -1;
  font-size: var(--text-xs);
  color: var(--dim);
  overflow-wrap: anywhere;
}
</style>
