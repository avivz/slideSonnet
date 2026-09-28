<script setup lang="ts">
defineProps<{ which: 'start' | 'end'; modelValue: number; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [number] }>()
</script>

<template>
  <label class="silence" :data-testid="`silence-${which}`">
    <span class="dots" aria-hidden="true">···</span>
    <input
      class="field"
      type="number"
      min="0"
      step="0.1"
      :value="modelValue.toFixed(1)"
      :disabled="disabled"
      :data-testid="`silence-secs-${which}`"
      :title="`Held silence at the slide's ${which} — a transition plays over it. 0 = no hold.`"
      @change="emit('update:modelValue', Math.max(0, Number(($event.target as HTMLInputElement).value) || 0))"
    />
    <span class="dim-text">s · {{ which === 'start' ? 'start silence' : 'end silence' }}</span>
  </label>
</template>

<style scoped>
.silence {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
}
.dots {
  width: 24px;
  color: var(--dim);
  text-align: center;
}
.field {
  width: 64px;
}
</style>
