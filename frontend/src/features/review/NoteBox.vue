<script setup lang="ts">
// A note to the agent: Enter (or Send) sends it; Shift+Enter starts a new line.
import { ref } from 'vue'

defineProps<{ placeholder: string; testId: string }>()
const emit = defineEmits<{ send: [text: string] }>()
const text = ref('')

function send(): void {
  const value = text.value.trim()
  if (!value) return
  emit('send', value)
  text.value = ''
}
function onKey(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}
</script>

<template>
  <div class="note">
    <textarea
      v-model="text"
      class="field"
      dir="auto"
      rows="2"
      :placeholder="placeholder"
      :aria-label="placeholder"
      :data-testid="testId"
      @keydown="onKey"
    ></textarea>
    <button class="btn quiet" type="button" title="Send to the agent (Enter)" :data-testid="`${testId}-add`" @click="send">
      Send
    </button>
  </div>
</template>

<style scoped>
.note {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--space-1);
  align-items: end;
}
textarea {
  height: auto;
  min-height: 52px;
  padding: var(--space-2);
  resize: vertical;
  line-height: 1.4;
}
</style>
