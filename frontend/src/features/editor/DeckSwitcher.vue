<script setup lang="ts">
// Ctrl+K: a type-to-filter list of every deck in the library.
import { computed, ref, watch } from 'vue'

import type { LibraryDeckDTO } from '@/api/client'
import AppDialog from '@/components/AppDialog.vue'
import { filterDecks } from '@/features/library/library'
import { useEditorStore } from '@/stores/editor'

const props = defineProps<{ open: boolean; current: string }>()
const emit = defineEmits<{ close: []; pick: [LibraryDeckDTO] }>()
const editor = useEditorStore()
const decks = ref<LibraryDeckDTO[]>([])
const query = ref('')
const cursor = ref(0)
const matches = computed(() => filterDecks(decks.value, query.value))

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    query.value = ''
    cursor.value = 0
    try {
      const lib = await editor.client.library({ rescan: true }) // a deck added since launch shows up
      decks.value = lib.sections.flatMap((s) => s.decks)
    } catch {
      decks.value = []
    }
  },
)
watch(query, () => (cursor.value = 0))

function onKey(event: KeyboardEvent): void {
  const n = matches.value.length
  if (event.key === 'ArrowDown' && n) {
    cursor.value = (cursor.value + 1) % n
    event.preventDefault()
  } else if (event.key === 'ArrowUp' && n) {
    cursor.value = (cursor.value - 1 + n) % n
    event.preventDefault()
  } else if (event.key === 'Enter') {
    const deck = matches.value[cursor.value]
    if (deck) emit('pick', deck)
  }
}
</script>

<template>
  <AppDialog :open="open" title="Switch deck" @close="emit('close')">
    <input
      v-model="query"
      class="field search mono"
      placeholder="Jump to deck…"
      aria-label="Deck name"
      autofocus
      data-testid="switcher-input"
      @keydown="onKey"
    />
    <ul class="list" role="listbox" aria-label="Decks">
      <li v-if="matches.length === 0" class="empty dim-text">No deck matches</li>
      <li
        v-for="(deck, i) in matches"
        :key="deck.token"
        role="option"
        class="row"
        :class="{ active: i === cursor, current: deck.token === current }"
        :aria-selected="i === cursor"
        :data-testid="`switcher-row-${i}`"
        @click="emit('pick', deck)"
      >
        <span class="section mono">{{ deck.section || '·' }}</span>
        <span class="name mono">{{ deck.name }}</span>
      </li>
    </ul>
  </AppDialog>
</template>

<style scoped>
.search {
  width: 100%;
  height: 36px;
}
.list {
  display: grid;
  max-height: min(420px, 60vh);
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
}
.row {
  display: flex;
  gap: var(--space-3);
  padding: 7px var(--space-2);
  border: 1px solid transparent;
  border-radius: 7px;
  cursor: pointer;
}
.row:hover,
.row.active {
  background: var(--raised);
}
.row.active {
  border-color: var(--accent-deep);
}
.row.current .name {
  color: var(--accent);
}
.section {
  min-width: 74px;
  font-size: var(--text-xs);
  color: var(--dim);
}
.name {
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}
.empty {
  padding: var(--space-3);
  font-size: var(--text-sm);
}
</style>
