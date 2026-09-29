<script setup lang="ts">
// The deck editor page (/d/:token). Layout: filmstrip | stage + narration |
// console, each side pane resizable and collapsible; below 900 px the side
// panes fold away and open as overlays.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import type { LibraryDeckDTO } from '@/api/client'
import { EventStream } from '@/api/events'
import AppIcon from '@/components/AppIcon.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'
import { usePlayerStore } from '@/stores/player'
import { useReviewStore } from '@/stores/review'
import ReviewPanel from '@/features/review/ReviewPanel.vue'
import WaitingBanner from '@/features/review/WaitingBanner.vue'

import ConflictDialog from './ConflictDialog.vue'
import ConsolePanel from './ConsolePanel.vue'
import DeckHead from './DeckHead.vue'
import DeckSwitcher from './DeckSwitcher.vue'
import FilmStrip from './FilmStrip.vue'
import { shortcut } from './keymap'
import { useLeaveGuard } from './leave'
import NarrationEditor from './NarrationEditor.vue'
import SaveIndicator from './SaveIndicator.vue'
import ScriptView from './ScriptView.vue'
import SlideStage from './SlideStage.vue'
import VoicesDialog from './VoicesDialog.vue'

const route = useRoute()
const router = useRouter()
const editor = useEditorStore()
const generation = useGenerationStore()
const player = usePlayerStore()
const review = useReviewStore()
const consoleTab = ref<'audio' | 'review'>('audio')
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
// ---- panes ------------------------------------------------------------------
function stored(key: string, fallback: number): number {
  try {
    const v = Number(localStorage.getItem(key))
    return Number.isFinite(v) && v > 0 ? v : fallback
  } catch {
    return fallback
  }
}
/** An on/off choice this browser remembers ('1' / '0'); `fallback` until one is made. */
function storedFlag(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : v === '1'
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
const stripOpen = ref(storedFlag('ss.stripOpen', true))
const consoleOpen = ref(storedFlag('ss.consoleOpen', true))
// a link on the slide chose a conversation: show it in the Review tab
watch(
  () => review.panelRequests,
  () => {
    consoleTab.value = 'review'
    if (narrow.value) overlay.value = 'console'
    else consoleOpen.value = true
  },
)
/** Below this width the side panes become pop-overs. */
const NARROW_PX = 900
const narrow = ref(false)
const overlay = ref<'strip' | 'console' | null>(null)
/** The Review tab is on screen (the "agent is waiting" line would only repeat it). */
const reviewShown = computed(
  () => consoleTab.value === 'review' && (narrow.value ? overlay.value === 'console' : consoleOpen.value),
)

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

// The centre pane: the slide stays put above a divider; only the narration
// under it scrolls. Dragging the divider trades height between the two.
const mainEl = ref<HTMLElement | null>(null)
const mainHeight = ref(0)
const stageHeight = ref(stored('ss.stageHeight', 0)) // 0: not chosen yet, use half
const MIN_PART = 140
const stagePx = computed(() => {
  const total = mainHeight.value
  if (total <= 0) return stageHeight.value || 360
  const wanted = stageHeight.value || Math.round(total * 0.5)
  return Math.max(MIN_PART, Math.min(total - MIN_PART, wanted))
})
let mainObserver: ResizeObserver | null = null
watch(mainEl, (el) => {
  mainObserver?.disconnect()
  mainObserver = null
  if (el === null || typeof ResizeObserver === 'undefined') return
  mainObserver = new ResizeObserver(() => {
    mainHeight.value = el.clientHeight
  })
  mainObserver.observe(el)
})
function setStageHeight(px: number): void {
  stageHeight.value = Math.round(px)
  remember('ss.stageHeight', stageHeight.value)
}
function startSplit(event: PointerEvent): void {
  const startY = event.clientY
  const start = stagePx.value
  const onMove = (e: PointerEvent): void => {
    stageHeight.value = Math.max(MIN_PART, Math.min(mainHeight.value - MIN_PART, start + e.clientY - startY))
  }
  const onUp = (): void => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    setStageHeight(stageHeight.value)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}
function onSplitKey(event: KeyboardEvent): void {
  const step = event.key === 'ArrowUp' ? -24 : event.key === 'ArrowDown' ? 24 : 0
  if (step === 0) return
  event.preventDefault()
  setStageHeight(Math.max(MIN_PART, Math.min(mainHeight.value - MIN_PART, stagePx.value + step)))
}
const mainStyle = computed(() => ({ '--stage-px': `${stagePx.value}px` }))

// the narration below the slide: this slide's editor, or the whole deck as one script
const scriptView = ref(storedFlag('ss.scriptView', true)) // the script is the default view
function setScriptView(on: boolean): void {
  scriptView.value = on
  remember('ss.scriptView', on ? 1 : 0)
}

function onResize(): void {
  narrow.value = window.innerWidth < NARROW_PX
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
  if (!(await editor.open(deckToken)) || !editor.snapshot) return
  document.title = `${editor.snapshot.name} · slideSonnet`
  await generation.refresh()
  void generation.focus(editor.currentId)
  void review.refresh()
  if (editor.images.some((img) => img === null)) {
    renderAsked = editor.snapshot.revisions.pdf
    void editor.client.startJob(deckToken, { kind: 'render_pages', near: editor.index }).catch(() => undefined)
  }
}

// every way out of this deck (switcher, links, back/forward) saves first, and
// stays when the narration can't be saved
useLeaveGuard()

async function leaveTo(deck: { token: string }): Promise<void> {
  switcherOpen.value = false
  if (deck.token === token.value) return
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
  if (e.deck !== token.value) return
  generation.noteFailure(e.data) // the line says so until it's retried
  editor.flash(String(e.data.message || 'Couldn’t generate a line.'), 'err')
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

watch(() => editor.externalChanges, () => {
  void generation.sweep()
  void review.fileUnrequested() // an outside narration edit, under review: file it
})
// the review log changed (an agent replied), or a recompile landed: relight review
watch(
  () => [editor.snapshot?.revisions.review, editor.snapshot?.revisions.pdf] as const,
  (now, before) => {
    if (!before || before[0] === undefined) return
    if (now[1] !== before[1]) void review.fileUnrequested().then(() => review.refresh())
    else if (now[0] !== before[0]) void review.refresh()
  },
)
// a recompiled PDF's pages aren't rendered yet (the old pictures stand in): render them (once per change)
let renderAsked = ''
watch(
  () => editor.snapshot?.revisions.pdf,
  (pdfRev) => {
    if (!pdfRev || pdfRev === renderAsked || !editor.pages.some((p) => p.image_url === null)) return
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
function onKey(event: KeyboardEvent): void {
  const action = shortcut(event, {
    dialogOpen: document.querySelector('[role="dialog"]') !== null,
    reviewActive: review.active,
  })
  if (action === null) return
  if (action.kind !== 'compare' && action.kind !== 'next-turn') event.preventDefault()
  switch (action.kind) {
    case 'deck':
      stepDeck(action.delta)
      break
    case 'switcher':
      switcherOpen.value = true
      break
    case 'save':
      void editor.flush()
      break
    case 'compare':
      review.beforeOnly = !review.beforeOnly // the base version full-size / side by side
      break
    case 'next-turn':
      review.nextYourTurn()
      break
    case 'slide':
      // within a chosen conversation, or off a removed slide; else the next page
      if (!review.step(action.delta)) editor.go(editor.index + action.delta)
      break
  }
}

// the console's tabs: arrows (and Home/End) move between them, as tabs do
const TABS = ['audio', 'review'] as const
function onTabKey(event: KeyboardEvent): void {
  const i = TABS.indexOf(consoleTab.value)
  const next =
    event.key === 'ArrowRight' ? (i + 1) % TABS.length
    : event.key === 'ArrowLeft' ? (i + TABS.length - 1) % TABS.length
    : event.key === 'Home' ? 0
    : event.key === 'End' ? TABS.length - 1
    : -1
  if (next < 0) return
  event.preventDefault()
  consoleTab.value = TABS[next] as (typeof TABS)[number]
  ;(event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus()
}

function onBeforeUnload(event: BeforeUnloadEvent): void {
  if (editor.hasUnsaved) {
    void editor.flush()
    event.preventDefault()
  }
}

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
  mainObserver?.disconnect()
  void generation.leave()
})

/** The error pill, for narration whose slide is gone: bring the Unattached narration panel into view. */
async function showOrphans(): Promise<void> {
  consoleTab.value = 'audio'
  if (narrow.value) overlay.value = 'console'
  else if (!consoleOpen.value) toggle('console')
  await nextTick()
  const tray = document.querySelector<HTMLElement>('[data-testid="orphan-tray"]')
  if (!tray) return
  tray.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  tray.classList.remove('flash')
  void tray.offsetWidth // restart the highlight when asked twice
  tray.classList.add('flash')
}

function pick(deck: LibraryDeckDTO): void {
  void leaveTo(deck)
}
</script>

<template>
  <div class="editor-page" :class="{ narrow }">
    <!-- narrow windows only: the side panes are pop-overs, so their openers and the
         deck's name need a bar. Wide windows give the full height to the work. -->
    <header v-if="narrow" class="header">
      <button
        class="icon-btn" :class="{ on: overlay === 'strip' }" type="button"
        title="Show or hide the slides" aria-label="Show or hide the slides" data-testid="toggle-strip"
        @click="toggle('strip')"
      >
        <AppIcon name="panelLeft" />
      </button>
      <DeckHead
        class="bar-head" inline :label="deckLabel" :has-prev="!!snap?.neighbours.prev" :has-next="!!snap?.neighbours.next"
        @switch="switcherOpen = true" @step="stepDeck" @orphans="showOrphans"
      />
      <button
        class="icon-btn console-toggle" :class="{ on: overlay === 'console' }" type="button"
        title="Show or hide audio & export" aria-label="Audio & export" :aria-expanded="overlay === 'console'"
        data-testid="toggle-console" @click="toggle('console')"
      >
        <span class="toggle-label">Audio &amp; export</span>
        <AppIcon name="panelRight" />
      </button>
    </header>

    <!-- the agent waits for you somewhere in the deck (maybe not on this slide) -->
    <WaitingBanner v-if="snap && !editor.loadError && !reviewShown" />
    <p v-if="editor.loadError" class="load-error" role="alert">
      {{ editor.loadError }} <a href="/">Back to your decks</a>
    </p>

    <div v-else-if="snap" class="body" :style="gridStyle">
      <div class="pane strip" :class="{ overlay: narrow && overlay === 'strip', hidden: narrow ? overlay !== 'strip' : !stripOpen }">
        <DeckHead
          v-if="!narrow" :label="deckLabel" :has-prev="!!snap?.neighbours.prev" :has-next="!!snap?.neighbours.next"
          @switch="switcherOpen = true" @step="stepDeck" @orphans="showOrphans"
        />
        <FilmStrip />
      </div>
      <div
        class="divider d1" role="separator" aria-orientation="vertical" aria-label="Resize the slides pane"
        @pointerdown="startResize('strip', $event)"
      >
        <button
          class="fold left" type="button" :title="stripOpen ? 'Hide the slides' : 'Show the slides'"
          :aria-label="stripOpen ? 'Hide the slides' : 'Show the slides'" data-testid="fold-strip"
          @pointerdown.stop @click="toggle('strip')"
        >
          <AppIcon :name="stripOpen ? 'prev' : 'next'" :size="14" />
        </button>
      </div>
      <main ref="mainEl" class="main" :style="mainStyle">
        <div class="stage-area"><SlideStage /></div>
        <div
          class="split"
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize the slide and the narration"
          tabindex="0"
          data-testid="stage-split"
          @pointerdown="startSplit"
          @keydown="onSplitKey"
        ></div>
        <div class="narration-area">
          <div class="view-bar">
            <SaveIndicator />
            <div class="view-switch" role="group" aria-label="Narration view">
              <button
                type="button" :class="{ on: !scriptView }" :aria-pressed="!scriptView" data-testid="view-slide"
                title="Edit this slide's narration" @click="setScriptView(false)"
              >
                Slide
              </button>
              <button
                type="button" :class="{ on: scriptView }" :aria-pressed="scriptView" data-testid="view-script"
                title="The whole deck's narration as one script" @click="setScriptView(true)"
              >
                Script
              </button>
            </div>
          </div>
          <ScriptView v-if="scriptView" />
          <NarrationEditor v-else @voices="voicesOpen = true" />
        </div>
      </main>
      <div
        class="divider d2" role="separator" aria-orientation="vertical" aria-label="Resize the console"
        @pointerdown="startResize('console', $event)"
      >
        <button
          class="fold right" type="button" :title="consoleOpen ? 'Hide the console' : 'Show the console'"
          :aria-label="consoleOpen ? 'Hide the console' : 'Show the console'" data-testid="fold-console"
          @pointerdown.stop @click="toggle('console')"
        >
          <AppIcon :name="consoleOpen ? 'next' : 'prev'" :size="14" />
        </button>
      </div>
      <div class="pane console" :class="{ overlay: narrow && overlay === 'console', hidden: narrow ? overlay !== 'console' : !consoleOpen }">
        <div class="tabs" role="tablist" aria-label="Console" @keydown="onTabKey">
          <button
            role="tab" type="button" class="tab" :class="{ on: consoleTab === 'audio' }"
            :aria-selected="consoleTab === 'audio'" :tabindex="consoleTab === 'audio' ? 0 : -1" data-testid="console-tab-audio" @click="consoleTab = 'audio'"
          >
            Audio
          </button>
          <button
            role="tab" type="button" class="tab" :class="{ on: consoleTab === 'review' }"
            :aria-selected="consoleTab === 'review'" :tabindex="consoleTab === 'review' ? 0 : -1" data-testid="console-tab-review" @click="consoleTab = 'review'"
          >
            Review
            <span
              v-if="review.waitingCount" class="count" data-testid="console-tab-review-badge"
              :title="`${review.waitingCount} conversation(s) waiting for you`"
            >{{ review.waitingCount }}</span>
          </button>
        </div>
        <ConsolePanel v-show="consoleTab === 'audio'" @voices="voicesOpen = true" />
        <div v-show="consoleTab === 'review'" class="review-pane"><ReviewPanel /></div>
      </div>
    </div>

    <!-- short-lived messages ("Copied", "Exported …") float above the work -->
    <p v-if="editor.flashMessage" class="toast" :class="editor.flashMessage.kind" data-testid="flash" role="status">
      {{ editor.flashMessage.text }}
    </p>

    <DeckSwitcher :open="switcherOpen" :current="token" @close="switcherOpen = false" @pick="pick" />
    <VoicesDialog :open="voicesOpen" @close="voicesOpen = false" />
    <ConflictDialog />
    <ConfirmDialog />
  </div>
</template>

<style scoped>
.editor-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}
.header {
  display: flex;
  flex: none;
  align-items: center;
  gap: var(--space-2);
  height: 40px;
  padding: 0 var(--space-2);
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}
.console-toggle {
  display: inline-flex;
  align-items: center;
  flex: none;
  gap: var(--space-1);
  width: auto;
  padding: 0 var(--space-1);
}
.toggle-label {
  display: none;
  font-size: var(--text-xs);
  white-space: nowrap;
}
@media (min-width: 560px) {
  .toggle-label {
    display: inline;
  }
}
.header .bar-head {
  flex: 1;
  min-width: 0;
  padding: 0;
  border: 0;
}
.body {
  position: relative;
  display: grid;
  flex: 1;
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
.pane.strip:not(.hidden) {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}
.pane.console:not(.hidden) {
  display: grid;
  grid-template-rows: auto 1fr;
}
.tabs {
  display: flex;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3) 0;
  border-bottom: 1px solid var(--line);
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3);
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--dim);
  font-size: var(--text-sm);
  cursor: pointer;
}
.tab.on {
  color: var(--text);
  border-bottom-color: var(--accent);
}
.count {
  padding: 0 6px;
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: var(--on-accent);
  font-size: 10px;
  font-weight: 700;
}
.review-pane {
  overflow-y: auto;
  padding: var(--space-4);
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
  position: relative;
  z-index: 3;
  background: var(--line);
  cursor: col-resize;
}
/* the tab on each divider folds its pane away (and back) */
.fold {
  position: absolute;
  top: 50%;
  display: grid;
  place-items: center;
  width: 16px;
  height: 40px;
  padding: 0;
  transform: translateY(-50%);
  background: var(--raised);
  border: 1px solid var(--line);
  color: var(--dim);
  cursor: pointer;
}
.fold:hover {
  color: var(--text);
  border-color: var(--accent-deep);
}
.fold.left {
  left: 0;
  border-radius: 0 6px 6px 0;
}
.fold.right {
  right: 0;
  border-radius: 6px 0 0 6px;
}
.divider:hover {
  background: var(--accent-deep);
}
.narrow .divider {
  display: none;
}
.main {
  display: grid;
  grid-template-rows: var(--stage-px) 6px minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  /* the slide fits the stage area's height, less the player bar under it */
  --stage-h: calc(var(--stage-px) - 84px);
}
.stage-area {
  display: grid;
  align-content: center;
  min-height: 0;
  overflow: hidden;
  padding: var(--space-3) var(--space-5) var(--space-2);
}
.split {
  background: var(--line);
  cursor: row-resize;
}
.split:hover,
.split:focus-visible {
  background: var(--accent-deep);
}
.narration-area {
  display: grid;
  align-content: start;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4) var(--space-5) 48px;
}
.stage-area > * {
  width: 100%; /* the slide is sized by the area's height, not a fixed cap */
}
.view-bar {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  justify-self: end !important;
  width: auto !important;
  margin-bottom: var(--space-1);
}
.view-bar :deep(.save) {
  padding: 2px var(--space-2);
  background: var(--surface);
  border-radius: var(--radius-pill);
}
.view-switch {
  display: flex;
  padding: 2px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
}
.view-switch button {
  padding: 1px var(--space-3);
  background: transparent;
  border: 0;
  border-radius: var(--radius-pill);
  color: var(--dim);
  font-size: var(--text-xs);
  cursor: pointer;
}
.view-switch button.on {
  background: var(--raised);
  color: var(--text);
}
.narration-area > * {
  width: min(100%, 980px); /* long text lines are hard to read */
  justify-self: center;
}
.toast {
  position: fixed;
  bottom: var(--space-4);
  left: 50%;
  z-index: 30;
  max-width: min(640px, 90vw);
  margin: 0;
  padding: var(--space-2) var(--space-4);
  transform: translateX(-50%);
  background: var(--raised);
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
  box-shadow: 0 8px 24px rgb(0 0 0 / 45%);
  color: var(--text);
  font-size: var(--text-sm);
  pointer-events: none;
}
.toast.ok {
  color: var(--ok);
}
.toast.warn {
  color: var(--warn);
}
.toast.err {
  color: var(--err);
  font-weight: 600;
}
.load-error {
  padding: var(--space-6);
  color: var(--err);
}

</style>
