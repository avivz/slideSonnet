<script setup lang="ts">
// One line over the work when the agent waits for you somewhere in the deck —
// possibly on a slide you aren't looking at. Show opens the first such
// conversation (in the Review tab, on its slide); × puts the line away.
import { computed } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useReviewStore } from '@/stores/review'

const review = useReviewStore()

const where = computed(() => {
  const n = review.waitingSlides.length
  return n === 0 ? 'about the whole deck' : `on ${n} slide${n === 1 ? '' : 's'}`
})
</script>

<template>
  <p
    v-if="review.active && review.waitingCount > 0 && !review.bannerDismissed"
    class="waiting" role="status" data-testid="waiting-banner"
  >
    <span class="text">The agent is waiting for you {{ where }}</span>
    <button class="linkish" type="button" data-testid="waiting-show" @click="review.showWaiting()">Show</button>
    <span class="spacer"></span>
    <button
      class="icon-btn" type="button" title="Dismiss" aria-label="Dismiss" data-testid="waiting-dismiss"
      @click="review.bannerDismissed = true"
    >
      <AppIcon name="close" :size="14" />
    </button>
  </p>
</template>

<style scoped>
.waiting {
  display: flex;
  flex: none;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  padding: 2px var(--space-2) 2px var(--space-4);
  background: var(--raised);
  border-bottom: 1px solid var(--line);
  box-shadow: inset 3px 0 0 var(--accent);
  font-size: var(--text-sm);
}
.text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.linkish {
  flex: none;
  padding: 0;
  background: transparent;
  border: 0;
  color: var(--accent);
  font-size: inherit;
  font-weight: 600;
  cursor: pointer;
}
.linkish:hover {
  text-decoration: underline;
}
.spacer {
  flex: 1;
}
.icon-btn {
  width: 28px;
  height: 28px;
}
</style>
