<script setup lang="ts">
// The deck's identity, at the top of the slides column (or in the slim top bar
// on narrow windows): the mark back to the library, the deck switcher with its
// neighbours, real errors only, and the keyboard shortcuts behind "?".
import { computed, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useEditorStore } from '@/stores/editor'

// `inline`: one line (the narrow top bar); otherwise the name gets a line of its own
defineProps<{ label: string; hasPrev: boolean; hasNext: boolean; inline?: boolean }>()
const emit = defineEmits<{ switch: []; step: [delta: 1 | -1] }>()

const editor = useEditorStore()
const helpOpen = ref(false)

const errors = computed(() => editor.errorCount)
function firstError(): void {
  const i = editor.pages.findIndex((p) => p.status === 'error')
  if (i >= 0) editor.go(i)
}

const SHORTCUTS: [string, string][] = [
  ['← →', 'previous / next slide'],
  ['Alt+← →', 'previous / next deck'],
  ['Ctrl+K', 'switch deck'],
  ['Ctrl+S', 'save now (it also saves as you type)'],
  ['D', 'review: before / side by side'],
  ['N', 'review: next slide waiting for you'],
]
</script>

<template>
  <div class="deck-head">
    <div class="row">
      <a class="mark" href="/" title="Your decks" aria-label="slideSonnet — deck library">s<span>S</span></a>
      <span v-if="!inline" class="spacer"></span>
      <button
        class="icon-btn small" type="button" title="Previous deck (Alt+←)" aria-label="Previous deck"
        :disabled="!hasPrev" data-testid="deck-prev" @click="emit('step', -1)"
      >
        <AppIcon name="prev" :size="16" />
      </button>
      <button v-if="inline" class="deck-name mono" type="button" :title="`${label} — switch deck (Ctrl+K)`" data-testid="deck-switcher" @click="emit('switch')">
        <span class="text">{{ label }}</span>
      </button>
      <button
        class="icon-btn small" type="button" title="Next deck (Alt+→)" aria-label="Next deck"
        :disabled="!hasNext" data-testid="deck-next" @click="emit('step', 1)"
      >
        <AppIcon name="next" :size="16" />
      </button>
      <button
        class="icon-btn small" :class="{ on: helpOpen }" type="button" title="Keyboard shortcuts"
        aria-label="Keyboard shortcuts" :aria-expanded="helpOpen" data-testid="shortcuts" @click="helpOpen = !helpOpen"
      >
        <AppIcon name="help" :size="16" />
      </button>
    </div>
    <button
      v-if="!inline" class="deck-name mono wide" type="button" :title="`${label} — switch deck (Ctrl+K)`"
      data-testid="deck-switcher" @click="emit('switch')"
    >
      <span class="text">{{ label }}</span>
    </button>
    <button
      v-if="errors" class="errors mono" type="button" title="Go to the first slide with an error"
      data-testid="error-pill" @click="firstError"
    >
      <AppIcon name="error" :size="13" /> {{ errors }} error{{ errors === 1 ? '' : 's' }}
    </button>
    <dl v-if="helpOpen" class="help" data-testid="shortcuts-list">
      <template v-for="[keys, what] in SHORTCUTS" :key="keys">
        <dt class="mono">{{ keys }}</dt>
        <dd>{{ what }}</dd>
      </template>
    </dl>
  </div>
</template>

<style scoped>
.deck-head {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-2);
  border-bottom: 1px solid var(--line);
}
.row {
  display: flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
}
.mark {
  flex: none;
  margin-right: var(--space-1);
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: 800;
  color: var(--text);
  text-decoration: none;
}
.mark span {
  color: var(--accent);
}
.icon-btn.small {
  flex: none;
  width: 24px;
  height: 24px;
}
.icon-btn.on {
  color: var(--accent);
}
.deck-name {
  flex: 1;
  min-width: 0;
  padding: 2px var(--space-2);
  background: var(--raised);
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
  color: var(--text);
  font-size: var(--text-xs);
  cursor: pointer;
}
.deck-name .text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.deck-name.wide {
  border-radius: var(--radius-field);
  text-align: left;
}
.deck-name.wide .text {
  white-space: normal;
  word-break: break-all; /* fill the line: don't break early at a hyphen */
}
.spacer {
  flex: 1;
}
.deck-name:hover {
  border-color: var(--accent-deep);
}
.errors {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  justify-self: start;
  padding: 1px 8px;
  background: var(--err-fill);
  border: 1px solid rgb(255 107 107 / 45%);
  border-radius: var(--radius-pill);
  color: var(--err);
  font-size: var(--text-xs);
  font-weight: 600;
  cursor: pointer;
}
.help {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px var(--space-2);
  margin: 0;
  padding: var(--space-2);
  background: var(--raised);
  border-radius: var(--radius-field);
  font-size: var(--text-xs);
}
.help dt {
  color: var(--text);
  white-space: nowrap;
}
.help dd {
  margin: 0;
  color: var(--dim);
}
</style>
