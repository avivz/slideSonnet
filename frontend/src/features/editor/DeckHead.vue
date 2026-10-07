<script setup lang="ts">
// The deck's identity, at the top of the slides column (or in the slim top bar
// on narrow windows): the mark back to the library, the deck switcher with its
// neighbours, real errors only, and the keyboard shortcuts behind "?".
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { vTip } from '@/components/tip'
import { useEditorStore } from '@/stores/editor'

import { SHORTCUTS, comboKeys, shortcutTip } from './shortcuts'

// `inline`: one line (the narrow top bar); otherwise the name gets a line of its own
const props = defineProps<{ label: string; hasPrev: boolean; hasNext: boolean; inline?: boolean }>()
// `checks`: no slide has the errors — show the deck's own checks
const emit = defineEmits<{ switch: []; step: [delta: 1 | -1]; checks: [] }>()

const editor = useEditorStore()
/** The shortcuts list is open (the page's ? key opens it too). */
const helpOpen = defineModel<boolean>('help', { default: false })

const errors = computed(() => editor.errorCount)
function firstError(): void {
  const i = editor.pages.findIndex((p) => p.status === 'error')
  if (i >= 0) editor.go(i)
  else emit('checks')
}

// a pair of keys shares its modifier, written once: Alt+← →
const rows = Object.entries(SHORTCUTS).map(([kind, s]) => {
  const presses = s.combos.map(comboKeys)
  return {
    kind,
    mods: presses[0]?.slice(0, -1) ?? [],
    keys: presses.map((p) => p[p.length - 1] ?? ''),
    what: s.review ? `review: ${s.what}` : s.what,
  }
})

// the list floats under the ? button, over the work; Escape or a click elsewhere puts it away
const helpButton = ref<HTMLElement | null>(null)
const list = ref<HTMLElement | null>(null)
const listAt = ref({ top: 0, left: 0 })
function placeList(): void {
  const r = helpButton.value?.getBoundingClientRect()
  if (!r) return
  const width = Math.min(340, window.innerWidth - 16)
  listAt.value = { top: r.bottom + 6, left: Math.max(8, Math.min(r.right - width, window.innerWidth - width - 8)) }
}
function onDocumentPointer(event: PointerEvent): void {
  const target = event.target as Node | null
  if (list.value?.contains(target) || helpButton.value?.contains(target)) return
  helpOpen.value = false
}
function onDocumentKey(event: KeyboardEvent): void {
  if (event.key === 'Escape') helpOpen.value = false
}
function listen(on: boolean): void {
  if (on) {
    document.addEventListener('pointerdown', onDocumentPointer, true)
    document.addEventListener('keydown', onDocumentKey)
    window.addEventListener('resize', placeList)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointer, true)
    document.removeEventListener('keydown', onDocumentKey)
    window.removeEventListener('resize', placeList)
  }
}
watch(
  helpOpen,
  (open) => {
    listen(open)
    if (open) placeList()
  },
  { immediate: true, flush: 'post' },
)
onBeforeUnmount(() => listen(false))
const PREV_DECK = shortcutTip('deck', 'Previous deck', 0)
const NEXT_DECK = shortcutTip('deck', 'Next deck', 1)
const HELP = shortcutTip('help', 'Keyboard shortcuts')
const switchTip = computed(() => shortcutTip('switcher', `${props.label} — switch deck`))
</script>

<template>
  <div class="deck-head">
    <div class="row">
      <a class="mark" href="/" title="Your decks" aria-label="slideSonnet — deck library">s<span>S</span></a>
      <span v-if="!inline" class="spacer"></span>
      <button
        v-tip="PREV_DECK" class="icon-btn small" type="button" aria-label="Previous deck"
        :disabled="!hasPrev" data-testid="deck-prev" @click="emit('step', -1)"
      >
        <AppIcon name="prev" :size="16" />
      </button>
      <button v-if="inline" v-tip="switchTip" class="deck-name mono" type="button" data-testid="deck-switcher" @click="emit('switch')">
        <span class="text">{{ label }}</span>
      </button>
      <button
        v-tip="NEXT_DECK" class="icon-btn small" type="button" aria-label="Next deck"
        :disabled="!hasNext" data-testid="deck-next" @click="emit('step', 1)"
      >
        <AppIcon name="next" :size="16" />
      </button>
      <button
        ref="helpButton"
        v-tip="HELP" class="icon-btn small" :class="{ on: helpOpen }" type="button"
        aria-label="Keyboard shortcuts" :aria-expanded="helpOpen" data-testid="shortcuts" @click="helpOpen = !helpOpen"
      >
        <AppIcon name="help" :size="16" />
      </button>
    </div>
    <button
      v-if="!inline" v-tip="switchTip" class="deck-name mono wide" type="button"
      data-testid="deck-switcher" @click="emit('switch')"
    >
      <span class="text">{{ label }}</span>
    </button>
    <button
      v-if="errors" class="errors mono" type="button" title="Show the first error"
      data-testid="error-pill" @click="firstError"
    >
      <AppIcon name="error" :size="13" /> {{ errors }} error{{ errors === 1 ? '' : 's' }}
    </button>
    <dl
      v-if="helpOpen" ref="list" class="help" :style="{ top: `${listAt.top}px`, left: `${listAt.left}px` }"
      aria-label="Keyboard shortcuts" data-testid="shortcuts-list"
    >
      <template v-for="row in rows" :key="row.kind">
        <dt>
          <template v-for="mod in row.mods" :key="mod"><kbd>{{ mod }}</kbd>+</template>
          <template v-for="(key, i) in row.keys" :key="key">{{ i > 0 ? ' ' : '' }}<kbd>{{ key }}</kbd></template>
        </dt>
        <dd>{{ row.what }}</dd>
      </template>
      <dt><kbd>Ctrl</kbd>+click</dt>
      <dd>review: tag a slide in the strip for a new conversation</dd>
      <dt>click a line</dt>
      <dd>while playing: play on from there</dd>
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
  position: fixed; /* over the panes, whose edges would cut it off */
  z-index: 40;
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: baseline;
  gap: 4px var(--space-3);
  width: min(340px, calc(100vw - 16px));
  margin: 0;
  padding: var(--space-3);
  background: var(--raised);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: 0 10px 28px rgb(0 0 0 / 55%);
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
