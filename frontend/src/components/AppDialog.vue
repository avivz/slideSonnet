<script setup lang="ts">
// A modal dialog: focus moves in and is trapped while open, Esc closes, and
// focus goes back to whatever had it before.
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{ open: boolean; title: string; wide?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
let returnTo: HTMLElement | null = null

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

function focusables(): HTMLElement[] {
  return [...(panel.value?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])].filter(
    (el) => !el.hasAttribute('disabled'),
  )
}

function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.stopPropagation()
    emit('close')
  } else if (event.key === 'Tab') {
    const els = focusables()
    if (els.length === 0) return
    const first = els[0] as HTMLElement
    const last = els.at(-1) as HTMLElement
    if (event.shiftKey && document.activeElement === first) {
      last.focus()
      event.preventDefault()
    } else if (!event.shiftKey && document.activeElement === last) {
      first.focus()
      event.preventDefault()
    }
  }
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      returnTo = document.activeElement instanceof HTMLElement ? document.activeElement : null
      await nextTick()
      const auto = panel.value?.querySelector<HTMLElement>('[autofocus]')
      ;(auto ?? focusables()[0] ?? panel.value)?.focus()
    } else {
      returnTo?.focus()
      returnTo = null
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => returnTo?.focus())
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="backdrop" @mousedown.self="emit('close')">
      <div
        ref="panel"
        class="panel"
        :class="{ wide }"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        tabindex="-1"
        @keydown="onKey"
      >
        <h2 class="title">{{ title }}</h2>
        <slot />
        <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: var(--space-4);
  background: rgb(5 7 10 / 60%);
}
.panel {
  display: grid;
  gap: var(--space-3);
  width: min(460px, 100%);
  max-height: calc(100vh - 32px);
  overflow: auto;
  padding: var(--space-5);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-dialog);
  box-shadow: 0 24px 64px rgb(0 0 0 / 60%);
}
.panel.wide {
  width: min(760px, 100%);
}
.title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 600;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
