<script setup lang="ts">
// A note to the agent: Enter (or Send) sends it; Shift+Enter starts a new line.
// The text is a v-model so the panel can keep each slide's unsent note apart.
// It is cleared only once the note went through; a failed send keeps it.
import { ref } from 'vue'

import { vTip } from '@/components/tip'

const props = defineProps<{
  placeholder: string
  testId: string
  /** Sends the note; resolves true once it went through. */
  send: (text: string) => Promise<boolean>
}>()
const text = defineModel<string>({ default: '' })
const sending = ref(false)

async function submit(): Promise<void> {
  const value = text.value.trim()
  if (!value || sending.value) return
  sending.value = true
  try {
    if (await props.send(value)) text.value = ''
  } finally {
    sending.value = false
  }
}
function onKey(event: KeyboardEvent): void {
  // Enter while an input method is composing picks a candidate: it doesn't send
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void submit()
  }
}
</script>

<template>
  <div class="note">
    <textarea
      v-model="text"
      class="field"
      dir="auto"
      rows="3"
      :placeholder="placeholder"
      :aria-label="placeholder"
      :data-testid="testId"
      @keydown="onKey"
    ></textarea>
    <div class="actions">
      <span class="hint">Enter sends · Shift+Enter for a new line</span>
      <button
        v-tip="{ text: 'Send to the agent', keys: [['Enter']] }"
        class="btn quiet"
        type="button"
        :disabled="!text.trim() || sending"
        :data-testid="`${testId}-add`"
        @click="submit"
      >
        {{ sending ? 'Sending…' : 'Send' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.note {
  display: grid;
  gap: var(--space-1);
}
textarea {
  width: 100%;
  height: auto;
  min-height: 84px;
  padding: var(--space-2) var(--space-3);
  resize: vertical;
  line-height: 1.45;
}
.actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
}
.hint {
  font-size: var(--text-xs);
  color: var(--dim);
}
</style>
