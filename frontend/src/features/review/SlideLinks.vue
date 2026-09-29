<script setup lang="ts">
// One line under the slide: the conversations it's in, and what changed on it.
// A conversation's link opens it in the Review tab.
import { computed } from 'vue'

import { useReviewStore } from '@/stores/review'

const review = useReviewStore()

const convs = computed(() => review.conversationsFor(review.subject))
const changed = computed(() => {
  const c = review.changes.get(review.subject)
  if (!c || review.authorOnly(review.subject)) return '' // only my own edits: nothing to review
  const what = [c.image ? 'slide' : '', c.narration ? 'narration' : ''].filter(Boolean)
  let text = what.length ? what.join(', ') : c.kinds.join(', ')
  if (c.moved && c.base_index !== null) text += ` (was slide ${c.base_index + 1})`
  return text
})
</script>

<template>
  <p v-if="review.active && (convs.length || changed)" class="links" data-testid="slide-links">
    <template v-if="convs.length">
      <span class="label">On this slide:</span>
      <button
        v-for="c in convs"
        :key="c.id"
        class="link"
        :class="{ closed: c.status === 'closed', mine: c.status === 'open' && c.turn === 'author' }"
        type="button"
        :title="c.title || c.messages[0]?.text || c.id"
        :data-testid="`slide-link-${c.id}`"
        @click="review.showInPanel(c.id)"
      >
        <span class="mono">{{ c.id }}</span>{{ c.title ? ` ${c.title}` : '' }}
      </button>
    </template>
    <span v-if="changed" class="changed" data-testid="review-change">changed: {{ changed }}</span>
  </p>
</template>

<style scoped>
.links {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px var(--space-2);
  margin: 0;
  font-size: var(--text-xs);
  color: var(--dim);
}
.link {
  max-width: 24ch;
  overflow: hidden;
  padding: 0;
  background: transparent;
  border: 0;
  color: var(--accent);
  font-size: inherit;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.link:hover {
  text-decoration: underline;
}
.link.mine {
  color: var(--warn);
}
.link.closed {
  color: var(--dim);
}
.changed {
  color: var(--warn);
}
</style>
