<script setup lang="ts">
// A note to the agent: Enter (or Send) sends it; Shift+Enter starts a new line.
// The text is a v-model so the panel can keep each slide's unsent note apart.
defineProps<{ placeholder: string; testId: string }>()
const emit = defineEmits<{ send: [text: string] }>()
const text = defineModel<string>({ default: '' })

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
      rows="3"
      :placeholder="placeholder"
      :aria-label="placeholder"
      :data-testid="testId"
      @keydown="onKey"
    ></textarea>
    <div class="actions">
      <span class="hint">Enter sends · Shift+Enter for a new line</span>
      <button
        class="btn quiet"
        type="button"
        title="Send to the agent (Enter)"
        :disabled="!text.trim()"
        :data-testid="`${testId}-add`"
        @click="send"
      >
        Send
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
