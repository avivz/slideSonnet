<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import type { ClipDTO } from './types'
import AppIcon from '@/components/AppIcon.vue'

import type { EditSeg } from './narration'

const props = defineProps<{
  seg: EditSeg
  index: number
  count: number
  /** The text the saved clip (if any) was made from. */
  savedText: string | null
  clip: ClipDTO | null
  generating: boolean
  voices: { value: string; label: string }[]
  /** The deck's default voice: naming it explicitly is still "the default". */
  defaultVoice?: string | null
  disabled?: boolean
}>()
const emit = defineEmits<{
  /** Change fields of this utterance; `commit` asks for an immediate save. */
  patch: [changes: Partial<EditSeg>, commit: boolean]
  commit: []
  move: [delta: number]
  remove: []
  generate: [force: boolean]
  voices: []
}>()

/** The clip is stale the moment the typed text leaves what it was made from. */
const stale = computed(() => props.savedText !== null && props.seg.text !== props.savedText)
const fresh = computed(() => (props.clip?.cached ?? false) && !stale.value)
const genTitle = computed(() => {
  if (props.generating) return 'Generating…'
  if (stale.value) return 'Edited · click to regenerate'
  if (props.clip?.cached) {
    const bits = []
    if (props.clip.seconds != null) bits.push(`${props.clip.seconds.toFixed(1)}s`)
    if (props.clip.bytes != null) {
      const kb = props.clip.bytes / 1024
      bits.push(kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${Math.round(kb)} KB`)
    }
    return `Generated${bits.length ? ' · ' + bits.join(' · ') : ''} · click for a fresh take`
  }
  return 'No audio yet · click to generate'
})

// Voice, pace and note rarely change, so they stay folded away; a line names
// whichever of them differ from the deck's defaults (click to open them).
const open = ref(false)
const chips = computed(() => {
  const out: string[] = []
  if (props.seg.voice && props.seg.voice !== props.defaultVoice) out.push(props.voices.find((v) => v.value === props.seg.voice)?.label ?? props.seg.voice)
  if (props.seg.pace && props.seg.pace !== 'normal') out.push(props.seg.pace)
  const note = (props.seg.direction ?? '').trim()
  if (note) out.push(`“${note}”`)
  return out
})

function onText(event: Event): void {
  emit('patch', { text: (event.target as HTMLTextAreaElement).value }, false)
}
function onVoice(value: string): void {
  emit('patch', { voice: value === '' ? null : value }, true)
}
function onPace(value: string): void {
  emit('patch', { pace: value as EditSeg['pace'] }, true)
}
function onDirection(event: Event): void {
  emit('patch', { direction: (event.target as HTMLInputElement).value }, false)
}
const area = ref<HTMLTextAreaElement | null>(null)
/** The text box is always as tall as its text (no inner scrolling). */
function grow(): void {
  const el = area.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight + 2}px`
}
onMounted(grow)
watch(
  () => props.seg.text,
  () => void nextTick(grow),
)
</script>

<template>
  <article class="card" :class="{ open }" :data-testid="`utterance-${index}`">
    <textarea
      ref="area"
      class="text"
      dir="auto"
      rows="1"
      placeholder="Spoken words…"
      aria-label="Spoken words"
      :value="seg.text"
      :disabled="disabled"
      :data-testid="`utext-${index}`"
      @input="onText"
      @blur="emit('commit')"
    ></textarea>
    <div class="tools">
      <!-- shown on hover / while editing this line -->
      <span class="more-tools">
        <button
          class="icon-btn" type="button" title="Move up" aria-label="Move up"
          :disabled="disabled || index === 0" :data-testid="`seg-up-${index}`" @click="emit('move', -1)"
        >
          <AppIcon name="up" :size="16" />
        </button>
        <button
          class="icon-btn" type="button" title="Move down" aria-label="Move down"
          :disabled="disabled || index === count - 1" :data-testid="`seg-down-${index}`" @click="emit('move', 1)"
        >
          <AppIcon name="down" :size="16" />
        </button>
        <button
          class="icon-btn danger" type="button" title="Delete this line" aria-label="Delete this line"
          :disabled="disabled" :data-testid="`seg-del-${index}`" @click="emit('remove')"
        >
          <AppIcon name="trash" :size="15" />
        </button>
      </span>
      <button
        class="icon-btn" :class="{ on: open }" type="button" :title="open ? 'Hide voice, pace and note' : 'Voice, pace and note'"
        :aria-label="open ? 'Hide voice, pace and note' : 'Voice, pace and note'" :aria-expanded="open"
        :data-testid="`usettings-${index}`" @click="open = !open"
      >
        <AppIcon name="more" :size="16" />
      </button>
      <button
        class="icon-btn gen"
        :class="{ fresh, busy: generating }"
        type="button"
        :title="genTitle"
        :aria-label="genTitle"
        :disabled="disabled || generating || seg.text.trim() === ''"
        :data-testid="`gen-seg-${index}`"
        :data-state="generating ? 'generating' : fresh ? 'fresh' : 'missing'"
        @click="emit('generate', clip?.cached ?? false)"
      >
        <span v-if="generating" class="spinner" aria-hidden="true"></span>
        <AppIcon v-else :name="fresh ? 'refresh' : 'wave'" :size="16" />
      </button>
    </div>
    <button
      v-if="!open && chips.length" class="chips mono" type="button" title="Change voice, pace or note"
      :data-testid="`uchips-${index}`" @click="open = true"
    >
      {{ chips.join(' · ') }}
    </button>
    <div v-if="open" class="opts">
      <label class="opt voice">
        <span class="label">Voice</span>
        <select
          class="field" :value="seg.voice ?? ''" :disabled="disabled" :data-testid="`uvoice-${index}`"
          @change="onVoice(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="v in voices" :key="v.value" :value="v.value">{{ v.label }}</option>
        </select>
      </label>
      <button
        class="icon-btn manage" type="button" title="Manage named voices" aria-label="Manage named voices"
        :disabled="disabled" @click="emit('voices')"
      >
        <AppIcon name="voice" :size="16" />
      </button>
      <label class="opt pace">
        <span class="label">Pace</span>
        <select
          class="field" :value="seg.pace ?? 'normal'" :disabled="disabled" :data-testid="`upace-${index}`"
          @change="onPace(($event.target as HTMLSelectElement).value)"
        >
          <option value="slow">slow</option>
          <option value="normal">normal</option>
          <option value="fast">fast</option>
        </select>
      </label>
      <label class="opt direction">
        <span class="label">Director's note</span>
        <input
          class="field" dir="auto" placeholder="how to speak it (optional)" :value="seg.direction" :disabled="disabled"
          :data-testid="`udirect-${index}`" @input="onDirection" @blur="emit('commit')"
        />
      </label>
    </div>
  </article>
</template>

<style scoped>
.card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0 var(--space-2);
  padding: 0 2px 0 var(--space-2);
  background: var(--raised);
  border: 1px solid var(--line);
  border-radius: var(--radius-field);
}
.card:focus-within {
  border-color: var(--accent-deep);
}
.tools {
  display: flex;
  align-items: flex-start;
  gap: 0;
}
.tools .icon-btn {
  width: 26px;
  height: 26px;
}
.tools .icon-btn.on {
  color: var(--accent);
}
/* moving and deleting are occasional: out of the way until you're on the line */
.more-tools {
  display: flex;
  opacity: 0;
  transition: opacity var(--fast);
}
.card:hover .more-tools,
.card:focus-within .more-tools {
  opacity: 1;
}
.text {
  width: 100%;
  min-height: 1.45em;
  resize: none;
  overflow: hidden;
  padding: 3px 0;
  background: transparent;
  border: 0;
  border-radius: var(--radius-field);
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 15px;
  line-height: 1.45;
}
.text:focus-visible {
  box-shadow: none;
}
.text::placeholder {
  color: var(--dim);
  font-style: italic;
  opacity: 0.6;
}
.chips {
  grid-column: 1 / -1;
  justify-self: start;
  margin: 0 0 3px;
  padding: 0 var(--space-2);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
  color: var(--dim);
  font-size: var(--text-xs);
  cursor: pointer;
}
.chips:hover {
  color: var(--text);
  border-color: var(--accent-deep);
}
.opts {
  grid-column: 1 / -1;
  padding-bottom: var(--space-1);
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-2);
}
.opt {
  display: grid;
  gap: 2px;
}
.opt .label {
  font-size: 9px;
}
.voice select {
  width: 190px;
}
.pace select {
  width: 96px;
}
.direction {
  flex: 1 1 160px;
}
.direction input {
  width: 100%;
}
.manage {
  align-self: flex-end;
}
.danger:hover:not(:disabled) {
  color: var(--err);
}
.gen {
  color: var(--warn);
}
.gen.fresh {
  color: var(--ok);
}
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--accent);
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
