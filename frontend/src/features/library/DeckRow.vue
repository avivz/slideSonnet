<script setup lang="ts">
import { computed } from 'vue'

import type { DeckStatsDTO, LibraryDeckDTO } from '@/api/client'

import { sizeText, subPath } from './library'

const props = defineProps<{
  deck: LibraryDeckDTO
  stats: DeckStatsDTO | 'error' | undefined
  underHeading: boolean
  highlighted: boolean
}>()

const size = computed(() => sizeText(props.stats))
const path = computed(() => subPath(props.deck, props.underHeading))
</script>

<template>
  <a
    class="row"
    :class="{ highlighted }"
    :href="deck.url"
    :data-testid="`deck-card-${deck.token}`"
    :aria-current="highlighted ? 'true' : undefined"
  >
    <span class="name mono">{{ deck.name }}</span>
    <span v-if="path" class="path mono">{{ path }}</span>
    <span class="size" :class="{ bad: stats === 'error' }">{{ size }}</span>
  </a>
</template>

<style scoped>
.row {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-field);
  text-decoration: none;
  transition: background var(--fast);
}
.row:hover,
.row.highlighted {
  background: var(--raised);
}
.row.highlighted {
  box-shadow: inset 2px 0 0 var(--accent-deep);
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
.size {
  margin-left: auto;
  flex: none;
  font-size: var(--text-sm);
  color: var(--dim);
  white-space: nowrap;
}
.size.bad {
  color: var(--err);
}
</style>
