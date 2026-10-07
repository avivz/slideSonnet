<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { vTip } from '@/components/tip'
import { formatClock } from '@/features/playback/clock'
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'

import { SHORTCUT_HINT } from './shortcutHint'
import { shortcutTip } from './shortcuts'

const editor = useEditorStore()
const player = usePlayerStore()
const audio = ref<HTMLAudioElement | null>(null)
const scrub = ref<number | null>(null) // position while the thumb is being dragged
const hint = inject(SHORTCUT_HINT, null) // "Press ? for shortcuts", the first few times

const PREV_TIP = shortcutTip('slide', 'Previous slide', 0)
const NEXT_TIP = shortcutTip('slide', 'Next slide', 1)
const JUMP_NOTE = 'Click any line to jump there while playing'
const PLAY_TIP = shortcutTip('play', 'Play from this slide on', undefined, JUMP_NOTE)
const PAUSE_TIP = shortcutTip('play', 'Pause', undefined, JUMP_NOTE)

let detach: (() => void) | null = null
onMounted(() => {
  if (audio.value) detach = player.attach(audio.value)
})
onBeforeUnmount(() => {
  player.stop()
  detach?.()
})

const f = computed(() => player.frame)
const playing = computed(() => f.value.playing)
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
  <div class="bar" data-testid="player-bar" data-slide-keys>
    <button
      v-tip="PREV_TIP" class="icon-btn" type="button" aria-label="Previous slide"
      :disabled="editor.index === 0" data-testid="prev" @click="editor.go(editor.index - 1)"
    >
      <AppIcon name="prev" />
    </button>
    <span class="counter mono" data-testid="counter">Slide {{ editor.index + 1 }} / {{ editor.pages.length }}</span>
    <button
      v-tip="NEXT_TIP" class="icon-btn" type="button" aria-label="Next slide"
      :disabled="editor.index >= editor.pages.length - 1" data-testid="next" @click="editor.go(editor.index + 1)"
    >
      <AppIcon name="next" />
    </button>
    <span class="sep" aria-hidden="true"></span>
    <button
      v-tip="playing ? PAUSE_TIP : PLAY_TIP"
      class="icon-btn"
      :class="{ on: playing }"
      type="button"
      :aria-label="playing ? 'Pause' : 'Play'"
      data-testid="play"
      :data-state="player.building ? 'building' : playing ? 'playing' : 'idle'"
      @click="player.press()"
    >
      <span v-if="player.building" class="spinner" aria-hidden="true"></span>
      <AppIcon v-else :name="playing ? 'pause' : 'play'" />
    </button>
    <button v-tip="'Stop'" class="icon-btn" type="button" aria-label="Stop" data-testid="stop" @click="player.stop()">
      <AppIcon name="stop" />
    </button>
    <button
      v-tip="'Playback speed (preview only — no re-generation)'" class="btn quiet speed mono" type="button"
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
    <span v-if="player.allProgress" class="time mono" data-testid="play-progress">
      slide {{ player.allProgress.at }} of {{ player.allProgress.of }} ·
    </span>
    <span class="time mono" data-testid="time">{{ clock }}</span>
    <span v-if="hint?.shown.value" class="first-hint" data-testid="shortcut-hint">
      Press <kbd>?</kbd> for shortcuts
      <button type="button" class="dismiss" aria-label="Hide this tip" data-testid="shortcut-hint-dismiss" @click="hint.done()">
        <AppIcon name="close" :size="12" />
      </button>
    </span>
    <audio ref="audio" preload="auto" data-testid="preview-audio"></audio>
  </div>
</template>

<style scoped>
/* a narrow bar wraps: the scrubber (and what follows) takes a second row
   rather than sliding off the edge; buttons never shrink below a finger's width */
.bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px var(--space-1);
  min-width: 0;
  padding: var(--space-1) var(--space-2);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
}
.bar .icon-btn {
  flex: none;
  min-width: 28px;
  min-height: 28px;
}
.counter {
  flex: none;
  min-width: 0;
  padding: 0 var(--space-1);
  white-space: nowrap;
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
  flex: none;
  min-width: 44px;
  min-height: 28px;
  padding: 0 var(--space-1);
  font-size: var(--text-xs);
}
.scrub {
  flex: 1 1 140px;
  min-width: 100px;
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
.first-hint {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--dim);
  white-space: nowrap;
}
.dismiss {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  padding: 0;
  background: transparent;
  border: 0;
  border-radius: var(--radius-field);
  color: var(--dim);
  cursor: pointer;
}
.dismiss:hover {
  color: var(--text);
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
