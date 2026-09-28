<script setup lang="ts">
import { computed, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'
import { usePlayerStore } from '@/stores/player'
import { useReviewStore } from '@/stores/review'

import { hasSilenceFields, moveSeg, newPause, newSpeech, speechIndexes, type EditSeg } from './narration'
import PauseCard from './PauseCard.vue'
import SilenceField from './SilenceField.vue'
import TransitionPicker from './TransitionPicker.vue'
import UtteranceCard from './UtteranceCard.vue'

const emit = defineEmits<{ voices: [] }>()

const editor = useEditorStore()
const generation = useGenerationStore()
const player = usePlayerStore()
const review = useReviewStore()
const root = ref<HTMLElement | null>(null)
/** Under review: how this slide's narration changed since the base, word by word. */
const diff = computed(() => (review.active ? (review.data?.diffs[slideId.value] ?? null) : null))

const slideId = computed(() => editor.currentId)
const block = computed(() => editor.draftFor(slideId.value))
const speech = computed(() => (block.value ? speechIndexes(block.value) : new Map<string, number>()))
const savedSpeech = computed(
  () =>
    editor.snapshot?.narration[slideId.value]?.segments
      .filter((s) => s.kind === 'speech')
      .map((s) => (s.kind === 'speech' ? (s.text ?? '') : '')) ?? [],
)
const clips = computed(() => editor.page?.clips ?? [])

const voiceOptions = computed(() => {
  const snap = editor.snapshot
  if (!snap) return []
  const deflt = snap.voices.default_voice
  const options = [{ value: '', label: deflt ? `default (${deflt})` : 'default' }]
  for (const name of snap.voices.names) {
    const engineVoice = snap.voices.resolved[name]
    options.push({ value: name, label: engineVoice ? `${name} (${engineVoice})` : `${name} (unmapped)` })
  }
  // an utterance pinned to a voice the deck doesn't name keeps it visible
  for (const seg of block.value?.middle ?? []) {
    if (seg.voice && !options.some((o) => o.value === seg.voice)) {
      options.push({ value: seg.voice, label: seg.voice })
    }
  }
  return options
})

/** Apply a card's change to its (store-owned) draft segment, then save soon or now. */
function patch(seg: EditSeg, changes: Partial<EditSeg>, now: boolean): void {
  Object.assign(seg, changes)
  if (now) commit()
  else editor.touch(slideId.value)
}
/** A change to what plays (voice, pace, a pause, a transition) saves at once. */
function commit(): void {
  editor.touch(slideId.value, { immediate: true })
}
/** Adding, removing, or reordering blocks changes the slide: a loaded track is stale. */
function structural(): void {
  player.stop()
  commit()
}

function add(kind: 'speech' | 'pause'): void {
  block.value?.middle.push(kind === 'speech' ? newSpeech() : newPause())
  structural()
}
function remove(index: number): void {
  block.value?.middle.splice(index, 1)
  structural()
}
function move(index: number, delta: number): void {
  if (block.value && moveSeg(block.value, index, delta)) structural()
}

async function generate(speechIndex: number, force: boolean): Promise<void> {
  const loaded = player.transport.loadedKey
  if (loaded === 'deck' || loaded === slideId.value) player.stop()
  await generation.enqueue([{ slide_id: slideId.value, speech_index: speechIndex }], { force })
}

function onFocusIn(event: FocusEvent): void {
  player.setEditing(true)
  const card = (event.target as HTMLElement).closest<HTMLElement>('[data-speech]')
  generation.focusedSpeech = card
    ? { slideId: slideId.value, index: Number(card.dataset.speech) }
    : null
}
function onFocusOut(event: FocusEvent): void {
  const next = event.relatedTarget as Node | null
  if (next && root.value?.contains(next)) return
  generation.focusedSpeech = null
  player.setEditing(false)
}
function onKey(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    commit() // save now, without leaving the field
  }
}
</script>

<template>
  <section
    ref="root"
    class="editor"
    aria-label="Narration"
    data-testid="narration-editor"
    @focusin="onFocusIn"
    @focusout="onFocusOut"
    @keydown="onKey"
  >
    <header class="head">
      <h2 class="id mono" data-testid="slide-id">{{ slideId || '(no slide id)' }}</h2>
      <span class="spacer"></span>
      <button
        class="btn quiet" type="button" :disabled="!block" data-testid="add-utterance"
        title="Add a spoken line" @click="add('speech')"
      >
        <AppIcon name="plus" :size="16" /> Line
      </button>
      <button
        class="btn quiet" type="button" :disabled="!block" data-testid="add-pause"
        title="Add a silent pause" @click="add('pause')"
      >
        <AppIcon name="hourglass" :size="16" /> Pause
      </button>
    </header>

    <p v-if="diff" class="diff" data-testid="narration-diff">
      <span class="section-title">Narration changes</span>
      <template v-for="([op, word], i) in diff" :key="i">
        <del v-if="op === '-'">{{ word }}</del>
        <ins v-else-if="op === '+'">{{ word }}</ins>
        <span v-else>{{ word }}</span>{{ ' ' }}
      </template>
    </p>
    <p v-if="review.viewingRemoved" class="notice dim-text">
      <span class="mono">@{{ review.viewingRemoved }}</span> was removed since the review started — its
      narration can't be edited here. Its conversations are in the Review tab.
    </p>
    <p v-else-if="!block" class="notice warn-text">
      This page has no slide id — add <code>\ssid</code> in the source to narrate it.
    </p>
    <template v-else-if="editor.meta && !review.viewingRemoved">
      <TransitionPicker v-model="block.transitionIn" which="in" :meta="editor.meta" @update:model-value="commit" />
      <SilenceField
        v-if="hasSilenceFields(block)" v-model="block.start as number" which="start"
        @update:model-value="commit"
      />
      <div class="cards">
        <template v-for="(seg, i) in block.middle" :key="seg.key">
          <UtteranceCard
            v-if="seg.kind === 'speech'"
            :data-speech="speech.get(seg.key)"
            :seg="seg"
            :index="i"
            :count="block.middle.length"
            :saved-text="savedSpeech[speech.get(seg.key) ?? -1] ?? null"
            :clip="clips[speech.get(seg.key) ?? -1] ?? null"
            :generating="generation.inflight.has(`${slideId}#${speech.get(seg.key)}`)"
            :voices="voiceOptions"
            @patch="(changes, now) => patch(seg, changes, now)"
            @commit="commit"
            @move="move(i, $event)"
            @remove="remove(i)"
            @generate="generate(speech.get(seg.key) ?? 0, $event)"
            @voices="emit('voices')"
          />
          <PauseCard
            v-else :seg="seg" :index="i" :count="block.middle.length" @patch="(changes, now) => patch(seg, changes, now)"
            @move="move(i, $event)" @remove="remove(i)"
          />
        </template>
        <p v-if="block.middle.length === 0" class="empty dim-text">
          Nothing to say on this slide yet — add a line or a pause.
        </p>
      </div>
      <SilenceField
        v-if="hasSilenceFields(block)" v-model="block.end as number" which="end"
        @update:model-value="commit"
      />
      <TransitionPicker v-model="block.transitionOut" which="out" :meta="editor.meta" @update:model-value="commit" />
    </template>
  </section>
</template>

<style scoped>
.editor {
  display: grid;
  gap: var(--space-3);
  align-content: start;
}
.head {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.id {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--accent);
}
.spacer {
  flex: 1;
}
.cards {
  display: grid;
  gap: var(--space-2);
}
.diff {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  background: var(--raised);
  border: 1px solid var(--line);
  border-radius: var(--radius-field);
  font-size: var(--text-md);
  line-height: 1.6;
}
.diff .section-title {
  margin-right: var(--space-2);
}
.diff del {
  color: var(--err);
}
.diff ins {
  color: var(--ok);
  text-decoration: none;
  border-bottom: 1px solid var(--ok);
}
.empty,
.notice {
  margin: 0;
  font-size: var(--text-sm);
}
</style>
