<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppNotice from '@/components/AppNotice.vue'
import AppWordmark from '@/components/AppWordmark.vue'
import { useLibraryStore } from '@/stores/library'

import DeckRow from './DeckRow.vue'
import { countText, filterDecks } from './library'

const store = useLibraryStore()
const search = ref<HTMLInputElement | null>(null)
const highlight = ref(0)

const highlightedToken = computed(() => store.visible[highlight.value]?.token ?? null)
const unnarrated = computed(() =>
  store.library ? filterDecks(store.library.unnarrated, store.query) : [],
)

watch(
  () => store.query,
  () => {
    highlight.value = 0
  },
)

/** The relative path `levels` folders up: `..`, `../..`, … */
function upPath(levels: number): string {
  return Array.from({ length: levels }, () => '..').join('/')
}

function open(url: string): void {
  window.location.assign(url) // the editor is its own page for now
}

function onSearchKey(event: KeyboardEvent): void {
  const n = store.visible.length
  if (event.key === 'ArrowDown' && n > 0) {
    highlight.value = (highlight.value + 1) % n
    event.preventDefault()
  } else if (event.key === 'ArrowUp' && n > 0) {
    highlight.value = (highlight.value - 1 + n) % n
    event.preventDefault()
  } else if (event.key === 'Enter') {
    const deck = store.visible[highlight.value]
    if (deck) open(deck.url)
  } else if (event.key === 'Escape') {
    store.query = ''
  }
}

function onGlobalKey(event: KeyboardEvent): void {
  const typing = event.target instanceof HTMLInputElement
  const wantsSearch =
    (event.key === '/' && !typing) || (event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey))
  if (wantsSearch) {
    event.preventDefault()
    search.value?.focus()
    search.value?.select()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKey)
  void store.load()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKey))
</script>

<template>
  <div class="page">
    <header class="header">
      <div class="brand">
        <AppWordmark />
        <nav v-if="store.library" class="path mono" data-testid="library-path" aria-label="Folder">
          <button
            class="icon-btn up"
            type="button"
            data-testid="library-up"
            title="Up one folder"
            aria-label="Up one folder"
            :disabled="store.loading || store.library.parents.length === 0"
            @click="store.moveTo('..')"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path fill="currentColor" d="M11 20V7.83l-5.59 5.59L4 12l8-8 8 8-1.41 1.41L13 7.83V20h-2Z" />
            </svg>
          </button>
          <template v-for="(name, i) in store.library.parents" :key="i">
            <button
              class="crumb"
              type="button"
              :data-testid="`library-crumb-${i}`"
              :title="`Show the decks in ${name}`"
              :disabled="store.loading"
              @click="store.moveTo(upPath(store.library.parents.length - i))"
            >
              {{ name }}
            </button>
            <span v-if="!/[\\/]$/.test(name)" class="sep" aria-hidden="true">/</span>
          </template>
          <span class="crumb here" aria-current="location" :title="`Decks found under ${store.library.root}`">
            {{ store.library.root }}
          </span>
        </nav>
      </div>
      <label class="search">
        <span class="visually-hidden">Find a deck</span>
        <input
          ref="search"
          v-model="store.query"
          data-testid="library-search"
          type="search"
          placeholder="Find a deck…   /"
          autocomplete="off"
          spellcheck="false"
          @keydown="onSearchKey"
        />
      </label>
      <div class="tools">
        <span class="count mono" data-testid="library-count">{{ countText(store.deckCount) }}</span>
        <button
          class="icon-btn"
          type="button"
          data-testid="library-rescan"
          title="Look for new decks"
          aria-label="Look for new decks"
          :disabled="store.loading"
          @click="store.load({ rescan: true })"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path
              fill="currentColor"
              d="M17.65 6.35A7.95 7.95 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35Z"
            />
          </svg>
        </button>
      </div>
    </header>

    <main class="main">
      <AppNotice v-if="store.error" tone="err">{{ store.error }}</AppNotice>
      <AppNotice v-if="store.library?.truncated">
        The scan stopped early — this folder holds too much to search. Open a folder closer to your
        decks to see them all.
      </AppNotice>

      <section v-if="store.library && store.deckCount === 0" class="empty" data-testid="library-empty">
        <h1>No decks under this folder</h1>
        <p class="mono">{{ store.library.root }}</p>
        <p>
          A deck is a PDF with a matching <code>.narration</code> file beside it. Go up a folder with
          the arrow at the top, or relaunch from your decks folder.
        </p>
      </section>

      <p v-else-if="store.library && store.visible.length === 0" class="no-match">
        No deck matches “{{ store.query }}”.
      </p>

      <section
        v-for="group in store.groups"
        :key="group.title ?? ''"
        class="group"
        :aria-label="group.title ?? 'Decks'"
      >
        <h2 v-if="group.title" class="heading mono">
          <button
            class="folder"
            type="button"
            :data-testid="`library-open-${group.title}`"
            :title="`Show only the decks in ${group.title}`"
            :disabled="store.loading"
            @click="store.moveTo(group.title)"
          >
            {{ group.title }} <span class="n">{{ group.decks.length }}</span>
          </button>
        </h2>
        <div class="list">
          <DeckRow
            v-for="deck in group.decks"
            :key="deck.token"
            :deck="deck"
            :stats="store.stats[deck.token]"
            :under-heading="group.title !== null"
            :highlighted="deck.token === highlightedToken && store.query !== ''"
          />
        </div>
      </section>

      <details v-if="unnarrated.length > 0" class="bare" data-testid="library-unnarrated">
        <summary class="heading mono">
          Without narration <span class="n">{{ unnarrated.length }}</span>
        </summary>
        <p class="hint">
          These PDFs have no <code>.narration</code> file yet. Start one from a terminal:
        </p>
        <ul>
          <li v-for="deck in unnarrated" :key="deck.token">
            <span class="mono">{{ deck.label }}</span>
            <code class="cmd">slidesonnet init {{ deck.label }}.pdf</code>
          </li>
        </ul>
      </details>
    </main>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
}
.header {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: var(--space-4);
  height: 56px;
  padding: 0 var(--space-4);
  background: rgb(21 26 34 / 92%);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(10px);
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.path {
  display: flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
  max-width: 40vw;
  font-size: var(--text-xs);
  color: var(--dim);
}
.path .up {
  flex: none;
  width: 26px;
  height: 26px;
}
.crumb {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 2px 4px;
  border: 0;
  border-radius: var(--radius-field);
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.crumb:hover:not(:disabled) {
  background: var(--raised);
  color: var(--text);
}
.crumb.here {
  flex: none;
  max-width: 20vw;
  padding: 2px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
  background: var(--raised);
  color: var(--text);
  cursor: default;
}
.sep {
  flex: none;
  color: var(--line);
}
.folder {
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  letter-spacing: inherit;
  text-transform: inherit;
  cursor: pointer;
}
.folder:hover:not(:disabled) {
  color: var(--text);
  text-decoration: underline;
}
.search {
  flex: 1 1 auto;
  max-width: 420px;
  margin-left: auto;
}
.search input {
  width: 100%;
  height: 32px;
  padding: 0 var(--space-3);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-field);
  font-size: var(--text-sm);
}
.search input::placeholder {
  color: var(--dim);
}
.search input:focus-visible {
  border-color: var(--accent-deep);
}
.tools {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.count {
  font-size: var(--text-xs);
  color: var(--dim);
  white-space: nowrap;
}
.icon-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--dim);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--raised);
  color: var(--text);
}
.icon-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.main {
  display: grid;
  gap: var(--space-5);
  width: min(760px, 100%);
  margin: 0 auto;
  padding: var(--space-6) var(--space-4) 64px;
}
.group {
  display: grid;
  gap: var(--space-3);
}
.heading {
  margin: 0;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--dim);
}
.heading .n {
  margin-left: var(--space-1);
  color: var(--line);
  letter-spacing: 0;
}
.list {
  display: grid;
  gap: 1px;
  padding: var(--space-1);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
}
.empty {
  display: grid;
  justify-items: center;
  gap: var(--space-2);
  padding: 72px var(--space-4);
  text-align: center;
}
.empty h1 {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 600;
}
.empty p {
  margin: 0;
  max-width: 48ch;
  color: var(--dim);
}
.no-match {
  margin: 0;
  color: var(--dim);
}
.bare summary {
  cursor: pointer;
  width: fit-content;
  border-radius: var(--radius-field);
}
.bare .hint {
  color: var(--dim);
  font-size: var(--text-sm);
}
.bare ul {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.bare li {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: baseline;
  padding: var(--space-2) var(--space-3);
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: var(--radius-card);
  font-size: var(--text-sm);
}
code {
  font-family: var(--font-mono);
  font-size: 0.95em;
}
.cmd {
  color: var(--dim);
  user-select: all;
}
@media (width < 640px) {
  .header {
    height: auto;
    flex-wrap: wrap;
    padding: var(--space-2) var(--space-4);
  }
  .search {
    order: 3;
    flex-basis: 100%;
    max-width: none;
    margin: 0;
  }
  .tools {
    margin-left: auto;
  }
}
</style>
