<script setup lang="ts">
// The console's Review tab, organised around conversations: the list (choose
// one to grey out the other slides and read it below; Accept right on its
// row), the chosen conversation (messages, reply, rename, accept/reopen), and a
// box that opens a new conversation about the slides tagged for it (the one on
// screen, or several Ctrl-clicked in the strip). Every note goes to the agent at once.
import { computed, nextTick, reactive, ref } from 'vue'

import type { ConversationDTO } from '@/api/client'
import { useReviewStore } from '@/stores/review'

import NoteBox from './NoteBox.vue'

const review = useReviewStore()

const AUTHOR: Record<string, string> = { author: 'You', agent: 'Agent', system: 'Note' }

function turnLabel(c: ConversationDTO): string {
  if (c.status === 'closed') return 'accepted'
  return c.turn === 'author' ? 'your turn' : "agent's turn"
}
function originLabel(c: ConversationDTO): string {
  return c.origin === 'unrequested' ? ' · unrequested' : c.origin === 'author-edits' ? ' · your edits' : ''
}
/** A conversation's name: its title, else its first words. */
function nameOf(c: ConversationDTO): string {
  if (c.is_deck) return 'Whole deck'
  if (c.title) return c.title
  const first = c.messages.find((m) => m.author !== 'system')?.text ?? ''
  const words = first.split(/\s+/).filter(Boolean)
  return words.length ? words.slice(0, 6).join(' ') + (words.length > 6 ? '…' : '') : 'untitled'
}

/** The list: the whole-deck conversation first, then the rest (accepted ones when shown). */
const listed = computed(() => [
  ...(review.deckConversation ? [review.deckConversation] : []),
  ...review.slideConversations.filter((c) => c.status === 'open' || review.showClosed),
])
const chosen = computed(() => review.chosen)
const pendingHere = computed(() => Object.keys(review.data?.pending ?? {}))

// unsent replies stay with their conversation; one draft for a new conversation
const replies = reactive(new Map<string, string>())
const draft = ref('')

// ---- renaming ---------------------------------------------------------------
const renaming = ref(false)
const newTitle = ref('')
const titleInput = ref<HTMLInputElement | null>(null)
async function startRename(c: ConversationDTO): Promise<void> {
  newTitle.value = c.title
  renaming.value = true
  await nextTick()
  titleInput.value?.select()
}
async function finishRename(c: ConversationDTO, save: boolean): Promise<void> {
  if (!renaming.value) return
  renaming.value = false
  const title = newTitle.value.trim()
  if (save && title && title !== c.title) await review.command({ type: 'retitle', conversation: c.id, title })
}

async function resetComparison(): Promise<void> {
  const n = review.changes.size
  const ok = window.confirm(
    `Compare from the deck as it is now? The ${n} slide${n === 1 ? '' : 's'} changed so far ` +
      'stop showing as changed. Conversations stay open or accepted as they are.',
  )
  if (ok) await review.command({ type: 'mark_seen' })
}

function time(at: string): string {
  return at.slice(11, 16)
}
</script>

<template>
  <section class="review" data-testid="review-panel">
    <template v-if="!review.data || !review.active">
      <p v-if="!review.data && review.comparing" class="dim-text">Loading…</p>
      <p v-else-if="review.data?.final_build" class="hint" data-testid="review-final">
        This PDF is a final build (page numbers shown). Recompile it normally to compare changes
        and talk them over.
      </p>
    </template>

    <template v-else>
      <header class="head">
        <span v-if="review.comparing" class="dim-text small">comparing…</span>
        <span class="spacer"></span>
        <button
          class="btn quiet small"
          type="button"
          :disabled="!review.changes.size"
          title="Compare from the deck as it is now (e.g. after a recompile changed every slide). Conversations stay as they are."
          data-testid="review-reset"
          @click="resetComparison"
        >
          Reset comparison
        </button>
        <button
          class="btn quiet small"
          type="button"
          :disabled="review.closedCount === 0 || review.clearing"
          title="Make accepted changes the new starting point"
          data-testid="review-clear"
          @click="review.command({ type: 'clear' })"
        >
          {{ review.clearing ? 'Clearing…' : `Clear accepted (${review.closedCount})` }}
        </button>
      </header>
      <p v-if="review.data.final_build" class="warn-text small">
        Final build — comparison paused until the next normal compile.
      </p>
      <p v-if="pendingHere.length" class="warn-text small" data-testid="review-pending">
        Not in the PDF yet: {{ pendingHere.map((s) => `@${s}`).join(', ') }} — compile, or fix the id.
      </p>

      <!-- the conversations -->
      <section class="box">
        <div class="row">
          <h3 class="box-title">Conversations</h3>
          <span class="spacer"></span>
          <label v-if="review.closedCount || review.showClosed" class="check small">
            <input v-model="review.showClosed" type="checkbox" data-testid="review-show-closed" />
            show accepted ({{ review.closedCount }})
          </label>
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
            <span class="conv-name">All slides</span>
          </button>
          <div
            v-for="c in listed"
            :key="c.id"
            class="conv-row"
            :class="{ active: c.id === review.filter, closed: c.status === 'closed' }"
          >
            <button
              class="pick"
              type="button"
              :aria-pressed="c.id === review.filter"
              :title="c.id === review.filter ? 'Click again to see all slides' : 'Read this conversation; grey out the other slides'"
              :data-testid="`conv-row-${c.id}`"
              @click="review.toggle(c.id)"
            >
              <span class="conv-name" dir="auto">
                <span v-if="!c.is_deck" class="conv-id mono">{{ c.id }}</span> {{ nameOf(c) }}
              </span>
              <span class="conv-state" :class="c.status === 'closed' ? 'closed' : c.turn">
                {{ turnLabel(c) }}{{ originLabel(c) }}
              </span>
              <span v-if="c.slides.length" class="conv-slides mono">{{ c.slides.map((s) => `@${s}`).join(' ') }}</span>
            </button>
            <button
              v-if="!c.is_deck && c.status === 'open'"
              class="accept"
              type="button"
              title="Accept: close this conversation, its changes are fine"
              :aria-label="`Accept ${c.id}`"
              :data-testid="`accept-${c.id}`"
              @click="review.command({ type: 'accept', conversation: c.id })"
            >
              ✓
            </button>
          </div>
        </div>
      </section>

      <!-- the chosen conversation -->
      <section v-if="chosen" class="box" :data-testid="`conv-${chosen.id}`">
        <div class="row">
          <input
            v-if="renaming"
            ref="titleInput"
            v-model="newTitle"
            class="field title-input"
            aria-label="Conversation title"
            data-testid="conv-title-input"
            @keydown.enter.prevent="finishRename(chosen, true)"
            @keydown.esc.prevent="finishRename(chosen, false)"
            @blur="finishRename(chosen, true)"
          />
          <h3 v-else class="box-title" dir="auto">
            <span v-if="!chosen.is_deck" class="mono">{{ chosen.id }} · </span>{{ nameOf(chosen) }}
            <button
              v-if="!chosen.is_deck"
              class="rename"
              type="button"
              title="Rename"
              data-testid="conv-rename"
              @click="startRename(chosen)"
            >
              ✎
            </button>
          </h3>
          <span class="spacer"></span>
          <span class="conv-state small" :class="chosen.status === 'closed' ? 'closed' : chosen.turn">
            {{ chosen.is_deck ? 'instructions for the whole deck' : turnLabel(chosen) }}
          </span>
        </div>
        <p v-if="chosen.slides.length" class="conv-slides mono">{{ chosen.slides.map((s) => `@${s}`).join(' ') }}</p>
        <ul v-if="chosen.messages.length" class="messages">
          <li v-for="(m, i) in chosen.messages" :key="i" :class="m.author">
            <span class="meta">{{ AUTHOR[m.author] }} · {{ time(m.at) }}</span>
            <span class="text" dir="auto">{{ m.text }}</span>
          </li>
        </ul>
        <template v-if="chosen.status === 'open'">
          <NoteBox
            :model-value="replies.get(chosen.id) ?? ''"
            :test-id="`reply-${chosen.id}`"
            :placeholder="chosen.is_deck ? 'Instructions for the agent about the whole deck…' : 'Reply…'"
            :send="(text) => review.command({ type: 'reply', conversation: chosen!.id, text })"
            @update:model-value="(v) => replies.set(chosen!.id, v)"
          />
        </template>
        <button
          v-else
          class="btn quiet small"
          type="button"
          :data-testid="`reopen-${chosen.id}`"
          @click="review.command({ type: 'reopen', conversation: chosen.id })"
        >
          Reopen
        </button>
      </section>
      <p v-else class="hint">Choose a conversation to read it and reply.</p>

      <!-- a new conversation -->
      <section class="box">
        <div class="row wrap">
          <h3 class="box-title">New conversation about</h3>
          <span v-for="s in review.newSlides" :key="s" class="chip mono" :data-testid="`new-slide-${s}`">
            @{{ s }}
            <button
              v-if="review.pickedByHand"
              type="button"
              :aria-label="`Untag @${s}`"
              :data-testid="`new-slide-remove-${s}`"
              @click="review.unpick(s)"
            >
              ×
            </button>
          </span>
        </div>
        <p v-if="review.pickedByHand" class="hint small">
          Tagged slides stay as you move around. Ctrl-click in the strip to add or remove ·
          <button class="linkish" type="button" data-testid="new-reset" @click="review.resetPicked()">
            back to this slide
          </button>
        </p>
        <p v-else class="hint small">About the slide on screen. Ctrl-click slides in the strip to tag several.</p>
        <NoteBox
          v-if="review.newSlides.length"
          v-model="draft"
          test-id="new-note"
          placeholder="What should change…"
          :send="(text) => review.startConversation(text)"
        />
      </section>
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
  min-width: 0;
}
.row.wrap {
  flex-wrap: wrap;
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
  white-space: nowrap;
}
.hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--dim);
}
.hint.small {
  font-size: var(--text-xs);
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-2);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--line);
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
.rename {
  padding: 0 4px;
  background: transparent;
  border: 0;
  color: var(--dim);
  cursor: pointer;
}
.rename:hover {
  color: var(--accent);
}
.title-input {
  flex: 1;
  min-width: 0;
  height: 28px;
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
  display: flex;
  align-items: stretch;
  background: var(--surface);
  border-top: 1px solid var(--line);
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
.conv-row.closed .conv-name {
  color: var(--dim);
}
.conv-row.all,
.pick {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 2px var(--space-2);
  flex: 1;
  min-width: 0;
  padding: var(--space-2);
  background: transparent;
  border: 0;
  color: var(--text);
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
}
.conv-row.all {
  border-top: 0;
}
.conv-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-id {
  font-weight: 600;
}
.conv-state {
  color: var(--dim);
  white-space: nowrap;
}
.conv-state.author {
  color: var(--warn);
}
.conv-slides {
  grid-column: 1 / -1;
  margin: 0;
  font-size: var(--text-xs);
  color: var(--dim);
  overflow-wrap: anywhere;
}
.accept {
  flex: none;
  width: 36px;
  background: transparent;
  border: 0;
  border-left: 1px solid var(--line);
  color: var(--ok);
  font-size: var(--text-md);
  cursor: pointer;
}
.accept:hover {
  background: var(--ok);
  color: var(--bg);
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 2px 1px 6px;
  background: var(--raised);
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: var(--text-xs);
}
.chip button {
  padding: 0 4px;
  background: transparent;
  border: 0;
  color: var(--dim);
  cursor: pointer;
}
.linkish {
  padding: 0;
  background: transparent;
  border: 0;
  color: var(--accent);
  font-size: inherit;
  cursor: pointer;
}
.linkish:hover {
  text-decoration: underline;
}
.chip button:hover {
  color: var(--err);
}
</style>
