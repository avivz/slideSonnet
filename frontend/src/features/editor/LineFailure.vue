<script setup lang="ts">
// Under a line whose audio couldn't be made: says so until it's retried, with
// the reason one click away (the engine's own words in its tooltip).
import { ref } from 'vue'

import type { ClipFailure } from '@/stores/generation'

defineProps<{ failure: ClipFailure }>()
const emit = defineEmits<{ retry: [] }>()
const why = ref(false)
</script>

<template>
  <p class="failed" role="alert" data-testid="line-failed">
    <span>Couldn’t generate this line</span>
    <span aria-hidden="true">·</span>
    <button
      class="linkish" type="button" :aria-expanded="why" data-testid="line-failed-why" @click="why = !why"
    >
      Why?
    </button>
    <span aria-hidden="true">·</span>
    <button class="linkish" type="button" data-testid="line-failed-retry" @click="emit('retry')">Retry</button>
    <span v-if="why" class="why" :title="failure.detail || undefined">{{ failure.message }}</span>
  </p>
</template>

<style scoped>
.failed {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px var(--space-1);
  margin: 0;
  color: var(--err);
  font-size: var(--text-xs);
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
.why {
  flex: 1 1 100%;
  color: var(--text);
}
</style>
