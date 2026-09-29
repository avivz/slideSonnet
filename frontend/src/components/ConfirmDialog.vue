<script setup lang="ts">
// A promise-based yes/no dialog: `ask()` resolves true only on an explicit yes.
// Questions asked while one is open wait their turn; every one gets an answer.
import { ref } from 'vue'

import AppDialog from './AppDialog.vue'

interface Question {
  title: string
  lines: string[]
  yes: string
  danger?: boolean
}

const shown = ref<Question | null>(null)
let settle: (ok: boolean) => void = () => {}
const waiting: { question: Question; resolve: (ok: boolean) => void }[] = []

function showNext(): void {
  const next = waiting.shift()
  shown.value = next?.question ?? null
  settle = next?.resolve ?? (() => {})
}

function ask(question: Question): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    waiting.push({ question, resolve })
    if (shown.value === null) showNext()
  })
}
function close(ok: boolean): void {
  if (shown.value === null) return
  const answer = settle
  showNext()
  answer(ok)
}
defineExpose({ ask })
</script>

<template>
  <AppDialog :open="shown !== null" :title="shown?.title ?? ''" @close="close(false)">
    <p v-for="line in shown?.lines ?? []" :key="line" class="line">{{ line }}</p>
    <template #actions>
      <button class="btn quiet" type="button" @click="close(false)">Cancel</button>
      <button
        class="btn"
        :class="shown?.danger ? 'danger' : 'primary'"
        type="button"
        data-testid="confirm-yes"
        autofocus
        @click="close(true)"
      >
        {{ shown?.yes ?? 'OK' }}
      </button>
    </template>
  </AppDialog>
</template>

<style scoped>
.line {
  margin: 0;
}
</style>
