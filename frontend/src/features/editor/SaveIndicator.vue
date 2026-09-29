<script setup lang="ts">
// The deck's save state, shown in both views: every slide's narration counts.
// A failed save stays shown (with a way to try again) until a save succeeds.
import { computed } from 'vue'

import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()
const label = computed(
  () =>
    ({
      saved: 'Saved',
      unsaved: 'Unsaved changes',
      saving: 'Saving…',
      conflict: 'Changed on disk',
      error: 'Not saved',
    })[editor.saveState],
)
</script>

<template>
  <span class="save mono" :class="editor.saveState" role="status">
    <span data-testid="save-state">{{ label }}</span>
    <button
      v-if="editor.saveState === 'error'"
      class="retry"
      type="button"
      title="Try saving again"
      data-testid="save-retry"
      @click="editor.flush()"
    >
      Retry
    </button>
  </span>
</template>

<style scoped>
.save {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--dim);
}
.save.unsaved,
.save.saving {
  color: var(--warn);
}
.save.conflict,
.save.error {
  color: var(--err);
  font-weight: 600;
}
.retry {
  padding: 0 var(--space-2);
  background: transparent;
  border: 1px solid currentColor;
  border-radius: var(--radius-pill);
  color: inherit;
  font: inherit;
  cursor: pointer;
}
</style>
