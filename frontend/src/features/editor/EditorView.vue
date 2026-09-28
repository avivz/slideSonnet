<script setup lang="ts">
// The deck editor page (/d/:token). Layout: filmstrip | stage + narration |
// console, each side pane resizable and collapsible; below 1100 px the side
// panes fold away and open as overlays.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { LibraryDeckDTO } from '@/api/client'
import { EventStream } from '@/api/events'
import AppIcon from '@/components/AppIcon.vue'
import AppWordmark from '@/components/AppWordmark.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'
import { usePlayerStore } from '@/stores/player'

import ConflictDialog from './ConflictDialog.vue'
import ConsolePanel from './ConsolePanel.vue'
import DeckSwitcher from './DeckSwitcher.vue'
import FilmStrip from './FilmStrip.vue'
import NarrationEditor from './NarrationEditor.vue'
import SlideStage from './SlideStage.vue'
import VoicesDialog from './VoicesDialog.vue'

const route = useRoute()
const router = useRouter()
const editor = useEditorStore()
const generation = useGenerationStore()
const player = usePlayerStore()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const switcherOpen = ref(false)
const voicesOpen = ref(false)

const token = computed(() => String(route.params.token ?? ''))
const snap = computed(() => editor.snapshot)
const deckLabel = computed(() => {
  const s = snap.value
  if (!s) return ''
  const section = s.label.includes('/') ? s.label.split('/')[0] : ''
  return section && section !== s.name ? `${section} / ${s.name}` : s.name
})
const saveLabel = computed(
  () =>
    ({
      saved: 'Saved',
      unsaved: 'Unsaved changes',
      saving: 'Saving…',
      conflict: 'Changed on disk',
      error: 'Not saved',
    })[editor.saveState],
)

// ---- panes ------------------------------------------------------------------
function stored(key: string, fallback: number): number {
  try {
    const v = Number(localStorage.getItem(key))
    return Number.isFinite(v) && v > 0 ? v : fallback
  } catch {
    return fallback
  }
}
function remember(key: string, value: number | boolean): void {
  try {
    localStorage.setItem(key, String(value))
  } catch {
    // private window: panes just start at their defaults next time
  }
}
const stripWidth = ref(stored('ss.stripWidth', 168))
const consoleWidth = ref(stored('ss.consoleWidth', 300))
const stripOpen = ref(stored('ss.stripOpen', 1) === 1)
const consoleOpen = ref(stored('ss.consoleOpen', 1) === 1)
const narrow = ref(false)
const overlay = ref<'strip' | 'console' | null>(null)

function toggle(which: 'strip' | 'console'): void {
  if (narrow.value) {
    overlay.value = overlay.value === which ? null : which
    return
  }
  if (which === 'strip') {
    stripOpen.value = !stripOpen.value
    remember('ss.stripOpen', stripOpen.value ? 1 : 0)
  } else {
    consoleOpen.value = !consoleOpen.value
    remember('ss.consoleOpen', consoleOpen.value ? 1 : 0)
  }
}

function startResize(which: 'strip' | 'console', event: PointerEvent): void {
  const startX = event.clientX
  const start = which === 'strip' ? stripWidth.value : consoleWidth.value
  const onMove = (e: PointerEvent): void => {
    const delta = which === 'strip' ? e.clientX - startX : startX - e.clientX
    const max = which === 'strip' ? 360 : 520
    const next = Math.max(110, Math.min(max, start + delta))
    if (which === 'strip') stripWidth.value = next
    else consoleWidth.value = next
  }
  const onUp = (): void => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    remember(which === 'strip' ? 'ss.stripWidth' : 'ss.consoleWidth', which === 'strip' ? stripWidth.value : consoleWidth.value)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

function onResize(): void {
  narrow.value = window.innerWidth < 1100
  if (!narrow.value) overlay.value = null
}

const gridStyle = computed(() => {
  const strip = !narrow.value && stripOpen.value ? `${stripWidth.value}px` : '0px'
  const console_ = !narrow.value && consoleOpen.value ? `${consoleWidth.value}px` : '0px'
  const ar = snap.value?.aspect ?? 16 / 9
  const dividers = narrow.value ? '0px' : '6px'
  return {
    gridTemplateColumns: `${strip} ${dividers} minmax(0, 1fr) ${dividers} ${console_}`,
    gridTemplateAreas: '"strip d1 main d2 console"',
    '--deck-ar': String(ar),
    '--deck-ar-n': String(ar),
  }
})

// ---- deck lifecycle ------------------------------------------------------------
const events = new EventStream()
let pagesTimer: ReturnType<typeof setTimeout> | null = null

async function openDeck(deckToken: string): Promise<void> {
  player.stop()
  await editor.open(deckToken)
  if (!editor.snapshot) return
  document.title = `${editor.snapshot.name} · slideSonnet`
  await generation.refresh()
  void generation.focus(editor.currentId)
  if (editor.images.some((img) => img === null)) {
    renderAsked = editor.snapshot.revisions.pdf
    void editor.client.startJob(deckToken, { kind: 'render_pages', near: editor.index }).catch(() => undefined)
  }
}

async function leaveTo(deck: { token: string }): Promise<void> {
  switcherOpen.value = false
  if (deck.token === token.value) return
  await editor.flush() // the field being typed in must not vanish
  await generation.leave() // drop the clips only this tab asked for
  player.stop()
  await router.push(`/d/${deck.token}`)
}

function stepDeck(delta: 1 | -1): void {
  const next = snap.value?.neighbours[delta === 1 ? 'next' : 'prev']
  if (next) void leaveTo({ token: next })
}

function schedulePages(): void {
  if (pagesTimer !== null) return
  pagesTimer = setTimeout(() => {
    pagesTimer = null
    void editor.refreshPages()
  }, 250)
}

events.on('deck.changed', (e) => {
  if (e.deck === token.value) void editor.refresh()
})
events.on('generation.changed', (e) => {
  if (e.deck === token.value) void generation.refresh().then(() => editor.refresh())
})
events.on('generation.failed', (e) => {
  if (e.deck === token.value) editor.flash(`Generation failed: ${String(e.data.message ?? '')}`, 'err')
})
for (const type of ['job.progress', 'job.finished'] as const) {
  events.on(type, (e) => {
    if (e.deck === token.value && e.data.kind === 'render_pages') schedulePages()
  })
}
events.onResync(() => {
  void editor.refresh()
  void editor.refreshPages()
  void generation.refresh()
})

watch(() => editor.externalChanges, () => void generation.sweep())
// a recompiled PDF drops its old page images: render the new ones (once per change)
let renderAsked = ''
watch(
  () => editor.snapshot?.revisions.pdf,
  (pdfRev) => {
    if (!pdfRev || pdfRev === renderAsked || !editor.images.some((img) => img === null)) return
    renderAsked = pdfRev
    if (editor.token) {
      void editor.client
        .startJob(editor.token, { kind: 'render_pages', near: editor.index })
        .catch(() => undefined)
    }
  },
)
watch(() => editor.currentId, (id) => void generation.focus(id))
watch(token, (t) => void openDeck(t))

// ---- keyboard -------------------------------------------------------------------
function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
}
function onKey(event: KeyboardEvent): void {
  if (document.querySelector('[role="dialog"]')) return
  const key = event.key
  if (event.altKey && (key === 'ArrowLeft' || key === 'ArrowRight')) {
    event.preventDefault()
    stepDeck(key === 'ArrowRight' ? 1 : -1)
    return
  }
  if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === 'k') {
    event.preventDefault()
    switcherOpen.value = true
    return
  }
  if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === 's') {
    event.preventDefault()
    void editor.flush()
    return
  }
  if (typing(event.target) || event.ctrlKey || event.metaKey || event.shiftKey) return
  if (key === 'ArrowLeft' || key === 'ArrowUp') {
    event.preventDefault()
    editor.go(editor.index - 1)
  } else if (key === 'ArrowRight' || key === 'ArrowDown') {
    event.preventDefault()
    editor.go(editor.index + 1)
  }
}

function onBeforeUnload(event: BeforeUnloadEvent): void {
  if (editor.hasUnsaved) {
    void editor.flush()
    event.preventDefault()
  }
}

// ---- confirmations ----------------------------------------------------------------
function confirm(o: { title: string; lines: string[]; yes: string; danger?: boolean }): Promise<boolean> {
  return confirmDialog.value?.ask(o) ?? Promise.resolve(false)
}
generation.setConfirm((count, engine, action) =>
  confirm({
    title: 'This will spend API credits',
    lines: [`${count} clip(s) aren't generated yet — making them with ${engine} will spend API credits.`],
    yes: action,
  }),
)
player.setConfirm((count) =>
  confirm({
    title: 'This will spend API credits',
    lines: [`${count} clip(s) aren't generated yet — making them with ${editor.activeEngine} will spend API credits.`],
    yes: 'Generate & play',
  }),
)

onMounted(() => {
  onResize()
  window.addEventListener('resize', onResize)
  window.addEventListener('keydown', onKey)
  window.addEventListener('beforeunload', onBeforeUnload)
  events.open()
  void openDeck(token.value)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('beforeunload', onBeforeUnload)
  events.close()
  void generation.leave()
})

function pick(deck: LibraryDeckDTO): void {
  void leaveTo(deck)
}
</script>

<template>
  <div class="editor-page" :class="{ narrow }">
    <header class="header">
      <AppWordmark />
      <div class="deck">
        <button
          class="icon-btn" type="button" title="Previous deck (Alt+←)" aria-label="Previous deck"
          :disabled="!snap?.neighbours.prev" data-testid="deck-prev" @click="stepDeck(-1)"
        >
          <AppIcon name="prev" />
        </button>
        <button
          class="deck-name mono" type="button" title="Switch deck (Ctrl+K)" data-testid="deck-switcher"
          @click="switcherOpen = true"
        >
          {{ deckLabel }} <AppIcon name="down" :size="16" />
        </button>
        <button
          class="icon-btn" type="button" title="Next deck (Alt+→)" aria-label="Next deck"
          :disabled="!snap?.neighbours.next" data-testid="deck-next" @click="stepDeck(1)"
        >
          <AppIcon name="next" />
        </button>
      </div>
      <span class="spacer"></span>
      <span class="save mono" :class="editor.saveState" data-testid="save-state" role="status">{{ saveLabel }}</span>
      <span v-if="snap" class="pill mono" :class="editor.errorCount ? 'bad' : 'good'" data-testid="error-pill">
        {{ editor.errorCount ? `${editor.errorCount} error${editor.errorCount === 1 ? '' : 's'}` : 'no errors' }}
      </span>
      <button
        class="icon-btn" :class="{ on: narrow ? overlay === 'strip' : stripOpen }" type="button"
        title="Show or hide the slides" aria-label="Show or hide the slides" data-testid="toggle-strip"
        @click="toggle('strip')"
      >
        <AppIcon name="panelLeft" />
      </button>
      <button
        class="icon-btn" :class="{ on: narrow ? overlay === 'console' : consoleOpen }" type="button"
        title="Show or hide the console" aria-label="Show or hide the console" data-testid="toggle-console"
        @click="toggle('console')"
      >
        <AppIcon name="panelRight" />
      </button>
    </header>

    <p v-if="editor.loadError" class="load-error" role="alert">
      {{ editor.loadError }} <a href="/">Back to your decks</a>
    </p>

    <div v-else-if="snap" class="body" :style="gridStyle">
      <div class="pane strip" :class="{ overlay: narrow && overlay === 'strip', hidden: narrow ? overlay !== 'strip' : !stripOpen }">
        <FilmStrip />
      </div>
      <div
        class="divider d1" role="separator" aria-orientation="vertical" aria-label="Resize the slides pane"
        @pointerdown="startResize('strip', $event)"
      ></div>
      <main class="main">
        <SlideStage />
        <NarrationEditor @voices="voicesOpen = true" />
      </main>
      <div
        class="divider d2" role="separator" aria-orientation="vertical" aria-label="Resize the console"
        @pointerdown="startResize('console', $event)"
      ></div>
      <div class="pane console" :class="{ overlay: narrow && overlay === 'console', hidden: narrow ? overlay !== 'console' : !consoleOpen }">
        <ConsolePanel :confirm="confirm" @voices="voicesOpen = true" />
      </div>
    </div>

    <footer class="footer mono">
      <span class="flash" :class="editor.flashMessage?.kind" data-testid="flash" role="status">
        {{ editor.flashMessage?.text ?? '' }}
      </span>
      <span class="hints">←→ slides · Ctrl+K decks · saves automatically · Ctrl+S saves now</span>
    </footer>

    <DeckSwitcher :open="switcherOpen" :current="token" @close="switcherOpen = false" @pick="pick" />
    <VoicesDialog :open="voicesOpen" @close="voicesOpen = false" />
    <ConflictDialog />
    <ConfirmDialog ref="confirmDialog" />
  </div>
</template>

<style scoped>
.editor-page {
  display: grid;
  grid-template-rows: 52px 1fr 28px;
  height: 100vh;
  overflow: hidden;
}
.header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-4);
  background: rgb(21 26 34 / 92%);
  border-bottom: 1px solid var(--line);
}
.deck {
  display: flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
}
.deck-name {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  max-width: 40vw;
  overflow: hidden;
  padding: 3px var(--space-2) 3px var(--space-3);
  background: var(--raised);
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
  color: var(--text);
  font-size: var(--text-sm);
  white-space: nowrap;
  text-overflow: ellipsis;
  cursor: pointer;
}
.deck-name:hover {
  border-color: var(--accent-deep);
}
.spacer {
  flex: 1;
}
.save {
  font-size: var(--text-xs);
  color: var(--dim);
}
.save.saved {
  color: var(--ok);
}
.save.unsaved,
.save.saving {
  color: var(--warn);
}
.save.conflict,
.save.error {
  color: var(--err);
}
.pill {
  padding: 2px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: 600;
}
.pill.good {
  color: var(--ok);
  border-color: rgb(126 224 138 / 35%);
}
.pill.bad {
  color: var(--err);
  border-color: rgb(255 107 107 / 45%);
  background: var(--err-fill);
}
.body {
  position: relative;
  display: grid;
  min-height: 0;
}
.pane {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--surface);
}
.pane.strip {
  grid-area: strip;
}
.pane.console {
  grid-area: console;
}
.main {
  grid-area: main;
}
.divider.d1 {
  grid-area: d1;
}
.divider.d2 {
  grid-area: d2;
}
.pane.hidden {
  display: none;
}
.pane.overlay {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 20;
  display: block;
  width: min(320px, 85vw);
  box-shadow: 0 0 28px rgb(0 0 0 / 55%);
}
.pane.strip.overlay {
  left: 0;
}
.pane.console.overlay {
  right: 0;
}
.divider {
  background: var(--line);
  cursor: col-resize;
}
.divider:hover {
  background: var(--accent-deep);
}
.narrow .divider {
  display: none;
}
.main {
  display: grid;
  align-content: start;
  gap: var(--space-4);
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-4) var(--space-5) 48px;
}
.main > * {
  width: min(100%, 980px);
  justify-self: center;
}
.footer {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: 0 var(--space-4);
  overflow: hidden;
  background: var(--surface);
  border-top: 1px solid var(--line);
  font-size: var(--text-xs);
  white-space: nowrap;
}
.flash {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--dim);
}
.flash.ok {
  color: var(--ok);
}
.flash.warn {
  color: var(--warn);
}
.flash.err {
  color: var(--err);
  font-weight: 600;
}
.hints {
  flex: 0 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--dim);
}
.load-error {
  padding: var(--space-6);
  color: var(--err);
}
@media (width < 760px) {
  .hints {
    display: none;
  }
}
</style>
