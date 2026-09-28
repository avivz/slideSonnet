<script setup lang="ts">
// A promise-based yes/no dialog: `ask()` resolves true only on an explicit yes.
import { ref } from 'vue'

import AppDialog from './AppDialog.vue'

const open = ref(false)
const title = ref('')
const lines = ref<string[]>([])
const yes = ref('OK')
const danger = ref(false)
let settle: (ok: boolean) => void = () => {}

function ask(options: { title: string; lines: string[]; yes: string; danger?: boolean }): Promise<boolean> {
  title.value = options.title
  lines.value = options.lines
  yes.value = options.yes
  danger.value = options.danger ?? false
  open.value = true
  return new Promise<boolean>((resolve) => {
    settle = resolve
  })
}
function close(ok: boolean): void {
  open.value = false
  settle(ok)
}
defineExpose({ ask })
</script>

<template>
  <AppDialog :open="open" :title="title" @close="close(false)">
    <p v-for="line in lines" :key="line" class="line">{{ line }}</p>
    <template #actions>
      <button class="btn quiet" type="button" @click="close(false)">Cancel</button>
      <button
        class="btn"
        :class="danger ? 'danger' : 'primary'"
        type="button"
        data-testid="confirm-yes"
        autofocus
        @click="close(true)"
      >
        {{ yes }}
      </button>
    </template>
  </AppDialog>
</template>

<style scoped>
.line {
  margin: 0;
}
</style>
