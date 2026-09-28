<script setup lang="ts">
import { computed } from 'vue'

import type { MetaDTO, TransitionDTO } from '@/api/client'

import { compose, decompose, directionsFor } from './narration'

const props = defineProps<{
  modelValue: TransitionDTO
  meta: MetaDTO
  which: 'in' | 'out'
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [TransitionDTO] }>()

const parts = computed(() => decompose(props.meta.transitions, props.meta.aliases, props.modelValue.kind))
const directions = computed(() => directionsFor(props.meta.transitions, parts.value.family))
const label = computed(() => (props.which === 'in' ? 'Transition in' : 'Transition out'))

function setFamily(family: string): void {
  const dirs = directionsFor(props.meta.transitions, family)
  const direction = dirs.includes(parts.value.direction ?? '') ? parts.value.direction : (dirs[0] ?? null)
  const kind = compose(props.meta.transitions, family, direction)
  const seconds = kind === 'cut' ? 0 : props.modelValue.seconds || 0.5
  emit('update:modelValue', { kind, seconds })
}

function setDirection(direction: string): void {
  emit('update:modelValue', {
    kind: compose(props.meta.transitions, parts.value.family, direction),
    seconds: props.modelValue.seconds,
  })
}

function setSeconds(raw: string): void {
  const seconds = Math.max(0, Number(raw) || 0)
  emit('update:modelValue', { kind: props.modelValue.kind, seconds })
}
</script>

<template>
  <div class="transition" :data-testid="`trans-${which}`">
    <span class="label">{{ label }}</span>
    <select
      class="field kind"
      :aria-label="`${label}: effect`"
      :value="parts.family"
      :disabled="disabled"
      :data-testid="`trans-${which}-kind`"
      @change="setFamily(($event.target as HTMLSelectElement).value)"
    >
      <option v-for="f in meta.transitions" :key="f.key" :value="f.key">{{ f.label }}</option>
    </select>
    <select
      v-if="directions.length"
      class="field dir"
      :aria-label="`${label}: direction`"
      :value="parts.direction ?? directions[0]"
      :disabled="disabled"
      :data-testid="`trans-${which}-dir`"
      @change="setDirection(($event.target as HTMLSelectElement).value)"
    >
      <option v-for="d in directions" :key="d" :value="d">{{ d }}</option>
    </select>
    <label v-if="modelValue.kind !== 'cut'" class="secs">
      <input
        class="field"
        type="number"
        min="0"
        step="0.1"
        :aria-label="`${label}: seconds`"
        :value="modelValue.seconds.toFixed(1)"
        :disabled="disabled"
        :data-testid="`trans-${which}-secs`"
        @change="setSeconds(($event.target as HTMLInputElement).value)"
      />
      <span class="dim-text">s</span>
    </label>
  </div>
</template>

<style scoped>
.transition {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}
.label {
  min-width: 96px;
}
.kind {
  width: 150px;
}
.dir {
  width: 90px;
}
.secs {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}
.secs .field {
  width: 64px;
}
</style>
