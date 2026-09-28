<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { formatClock } from '@/features/playback/cues'
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'

const editor = useEditorStore()
const player = usePlayerStore()
const audio = ref<HTMLAudioElement | null>(null)
const scrub = ref<number | null>(null) // position while the thumb is being dragged

let detach: (() => void) | null = null
onMounted(() => {
  if (audio.value) detach = player.attach(audio.value)
})
onBeforeUnmount(() => {
  player.stop()
  detach?.()
})

const f = computed(() => player.frame)
const slidePlaying = computed(
  () => f.value.playing && player.transport.loadedKey === editor.currentId && editor.currentId !== '',
)
const deckPlaying = computed(() => f.value.playing && player.transport.loadedKey === 'deck')
const canPlaySlide = computed(() => (editor.page?.audio.speech ?? 0) > 0)
const position = computed(() =>
  scrub.value !== null ? scrub.value : f.value.duration > 0 ? f.value.time / f.value.duration : 0,
)
const clock = computed(() =>
  f.value.loaded ? `${formatClock(position.value * f.value.duration)} / ${formatClock(f.value.duration)}` : '',
)

function onScrubInput(event: Event): void {
  scrub.value = Number((event.target as HTMLInputElement).value) / 1000
}
function onScrubChange(event: Event): void {
  player.seekFraction(Number((event.target as HTMLInputElement).value) / 1000) // one seek per scrub
  scrub.value = null
}
</script>

<template>
  <div class="bar" data-testid="player-bar">
    <button
      class="icon-btn" type="button" title="Previous slide (←)" aria-label="Previous slide"
      :disabled="editor.index === 0" data-testid="prev" @click="editor.go(editor.index - 1)"
    >
      <AppIcon name="prev" />
    </button>
    <span class="counter mono" data-testid="counter">Slide {{ editor.index + 1 }} / {{ editor.pages.length }}</span>
    <button
      class="icon-btn" type="button" title="Next slide (→)" aria-label="Next slide"
      :disabled="editor.index >= editor.pages.length - 1" data-testid="next" @click="editor.go(editor.index + 1)"
    >
      <AppIcon name="next" />
    </button>
    <span class="sep" aria-hidden="true"></span>
    <button
      class="icon-btn"
      :class="{ on: slidePlaying, busy: player.building === editor.currentId }"
      type="button"
      :title="slidePlaying ? 'Pause' : 'Hear this slide'"
      :aria-label="slidePlaying ? 'Pause' : 'Hear this slide'"
      :disabled="!canPlaySlide"
      data-testid="play-slide"
      :data-state="player.building === editor.currentId ? 'building' : slidePlaying ? 'playing' : 'idle'"
      @click="player.press(editor.currentId)"
    >
      <span v-if="player.building === editor.currentId" class="spinner" aria-hidden="true"></span>
      <AppIcon v-else :name="slidePlaying ? 'pause' : 'play'" />
    </button>
    <button
      class="icon-btn"
      :class="{ on: deckPlaying }"
      type="button"
      :title="deckPlaying ? 'Pause the deck preview' : 'Preview the whole deck from here'"
      :aria-label="deckPlaying ? 'Pause the deck preview' : 'Preview the whole deck from here'"
      data-testid="play-deck"
      :data-state="player.building === 'deck' ? 'building' : deckPlaying ? 'playing' : 'idle'"
      @click="player.press('deck')"
    >
      <span v-if="player.building === 'deck'" class="spinner" aria-hidden="true"></span>
      <AppIcon v-else :name="deckPlaying ? 'pause' : 'deck'" />
    </button>
    <button class="icon-btn" type="button" title="Stop" aria-label="Stop" data-testid="stop" @click="player.stop()">
      <AppIcon name="stop" />
    </button>
    <button
      class="btn quiet speed mono" type="button" title="Playback speed (preview only — no re-generation)"
      data-testid="speed" @click="player.cycleSpeed()"
    >
      {{ player.speed }}×
    </button>
    <input
      class="scrub"
      type="range"
      min="0"
      max="1000"
      aria-label="Playback position"
      :value="Math.round(position * 1000)"
      :disabled="!f.loaded"
      data-testid="seek"
      @input="onScrubInput"
      @change="onScrubChange"
    />
    <span class="time mono" data-testid="time">{{ clock }}</span>
    <audio ref="audio" preload="auto" data-testid="preview-audio"></audio>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
  padding: var(--space-1) var(--space-2);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
}
.counter {
  min-width: 96px;
  font-size: var(--text-xs);
  color: var(--dim);
  text-align: center;
}
.sep {
  width: 1px;
  height: 20px;
  margin: 0 var(--space-1);
  background: var(--line);
}
.speed {
  min-width: 44px;
  min-height: 28px;
  padding: 0 var(--space-1);
  font-size: var(--text-xs);
}
.scrub {
  flex: 1 1 60px;
  min-width: 40px;
  accent-color: var(--accent);
}
.time {
  min-width: 0;
  font-size: var(--text-xs);
  color: var(--dim);
  white-space: nowrap;
}
audio {
  display: none;
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
