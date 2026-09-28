<script setup lang="ts">
import { computed } from 'vue'

import type { DeckStatsDTO, LibraryDeckDTO } from '@/api/client'

import { cardStatus, subPath } from './library'

const props = defineProps<{
  deck: LibraryDeckDTO
  stats: DeckStatsDTO | 'error' | undefined
  underHeading: boolean
  highlighted: boolean
}>()

const status = computed(() => cardStatus(props.stats))
const path = computed(() => subPath(props.deck, props.underHeading))
</script>

<template>
  <a
    class="card"
    :class="{ highlighted }"
    :href="deck.url"
    :data-testid="`deck-card-${deck.token}`"
    :aria-current="highlighted ? 'true' : undefined"
  >
    <span class="name mono">{{ deck.name }}</span>
    <span v-if="path" class="path mono">{{ path }}</span>
    <span class="status">
      <span class="bar" aria-hidden="true">
        <span
          class="fill"
          :class="status.tone"
          :style="{ width: `${Math.round((status.progress ?? 0) * 100)}%` }"
        ></span>
      </span>
      <span class="text mono" :class="status.tone">{{ status.text }}</span>
    </span>
  </a>
</template>

<style scoped>
.card {
  display: grid;
  gap: var(--space-1);
  align-content: start;
  min-width: 0;
  padding: var(--space-3) var(--space-4) var(--space-4);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  text-decoration: none;
  transition:
    border-color var(--fast),
    transform var(--fast);
}
.card:hover,
.card.highlighted {
  border-color: var(--accent-deep);
  transform: translateY(-1px);
}
.card.highlighted {
  box-shadow: 0 0 0 1px var(--accent-deep);
}
.name {
  font-size: var(--text-md);
  font-weight: 600;
  overflow-wrap: anywhere;
}
.path {
  font-size: var(--text-xs);
  color: var(--dim);
  overflow-wrap: anywhere;
}
.status {
  display: grid;
  gap: var(--space-1);
  margin-top: var(--space-2);
}
.bar {
  height: 4px;
  border-radius: var(--radius-pill);
  background: var(--raised);
  overflow: hidden;
}
.fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--dim);
  transition: width var(--pane);
}
.fill.ok {
  background: var(--ok);
}
.fill.partial {
  background: var(--warn);
}
.fill.bad {
  background: var(--err);
}
.text {
  font-size: var(--text-xs);
  color: var(--dim);
}
.text.ok {
  color: var(--ok);
}
.text.partial {
  color: var(--warn);
}
.text.bad {
  color: var(--err);
}
</style>
