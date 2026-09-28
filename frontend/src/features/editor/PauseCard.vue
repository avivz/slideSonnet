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
  <!-- a pause is a thin rule between lines: its length, and tools on hover -->
  <div class="pause" :data-testid="`pause-${index}`">
    <span class="rule" aria-hidden="true"></span>
    <label class="len" title="Pause length in seconds">
      <input
        class="field" type="number" min="0" step="0.1" aria-label="Pause length in seconds"
        :value="seg.seconds.toFixed(1)" :disabled="disabled" :data-testid="`pause-secs-${index}`" @change="onSeconds"
      />
      <span class="dim-text">s pause</span>
    </label>
    <span class="rule" aria-hidden="true"></span>
    <span class="tools">
      <button
        class="icon-btn" type="button" title="Move up" aria-label="Move up"
        :disabled="disabled || index === 0" :data-testid="`seg-up-${index}`" @click="emit('move', -1)"
      >
        <AppIcon name="up" :size="14" />
      </button>
      <button
        class="icon-btn" type="button" title="Move down" aria-label="Move down"
        :disabled="disabled || index === count - 1" :data-testid="`seg-down-${index}`" @click="emit('move', 1)"
      >
        <AppIcon name="down" :size="14" />
      </button>
      <button
        class="icon-btn" type="button" title="Delete this pause" aria-label="Delete this pause"
        :disabled="disabled" :data-testid="`seg-del-${index}`" @click="emit('remove')"
      >
        <AppIcon name="trash" :size="14" />
      </button>
    </span>
  </div>
</template>

<style scoped>
.pause {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 24px;
  padding: 0 var(--space-1) 0 var(--space-3);
  font-size: var(--text-xs);
}
.rule {
  flex: 1;
  border-top: 1px dashed var(--line);
}
.len {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.field {
  width: 52px;
  height: 22px;
  padding: 0 var(--space-1);
  font-size: var(--text-xs);
}
.tools {
  display: flex;
  opacity: 0;
  transition: opacity var(--fast);
}
.pause:hover .tools,
.pause:focus-within .tools {
  opacity: 1;
}
.tools .icon-btn {
  width: 22px;
  height: 22px;
}
</style>
