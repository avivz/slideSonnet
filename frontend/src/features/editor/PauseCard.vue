<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'

import type { EditSeg } from './narration'

defineProps<{ seg: EditSeg; index: number; count: number; disabled?: boolean }>()
const emit = defineEmits<{ patch: [changes: Partial<EditSeg>, commit: boolean]; move: [delta: number]; remove: [] }>()

function onSeconds(event: Event): void {
  emit('patch', { seconds: Math.max(0, Number((event.target as HTMLInputElement).value) || 0) }, true)
}
</script>

<template>
  <article class="pause" :data-testid="`pause-${index}`">
    <button
      class="icon-btn" type="button" title="Move up" aria-label="Move up"
      :disabled="disabled || index === 0" :data-testid="`seg-up-${index}`" @click="emit('move', -1)"
    >
      <AppIcon name="up" />
    </button>
    <button
      class="icon-btn" type="button" title="Move down" aria-label="Move down"
      :disabled="disabled || index === count - 1" :data-testid="`seg-down-${index}`" @click="emit('move', 1)"
    >
      <AppIcon name="down" />
    </button>
    <AppIcon name="hourglass" :size="16" class="dim-text" />
    <input
      class="field" type="number" min="0" step="0.1" aria-label="Pause length in seconds"
      :value="seg.seconds.toFixed(1)" :disabled="disabled" :data-testid="`pause-secs-${index}`" @change="onSeconds"
    />
    <span class="dim-text">s · pause</span>
    <span class="spacer"></span>
    <button
      class="icon-btn" type="button" title="Delete this pause" aria-label="Delete this pause"
      :disabled="disabled" :data-testid="`seg-del-${index}`" @click="emit('remove')"
    >
      <AppIcon name="trash" :size="16" />
    </button>
  </article>
</template>

<style scoped>
.pause {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border: 1px dashed var(--line);
  border-radius: var(--radius-card);
  font-size: var(--text-xs);
}
.field {
  width: 64px;
}
.spacer {
  flex: 1;
}
</style>
