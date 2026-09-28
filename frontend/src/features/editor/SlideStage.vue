<script setup lang="ts">
// The slide, large, with the player attached right under it. During a deck
// preview the browser player draws the *playing* slide (and its transitions)
// over the stage, on the audio clock — the editor below may be on another
// slide while you type.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { StageOverlay } from '@/features/playback/dom'
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'

import PlayerBar from './PlayerBar.vue'

const editor = useEditorStore()
const player = usePlayerStore()
const stage = ref<HTMLElement | null>(null)
const image = computed(() => editor.images[editor.index] ?? null)
let stopListening: (() => void) | null = null
let overlay: StageOverlay | null = null

onMounted(() => {
  if (stage.value) {
    overlay = new StageOverlay(stage.value)
    stopListening = player.onFrame((f) => overlay?.render(f))
  }
})
onBeforeUnmount(() => {
  stopListening?.()
  overlay?.dispose()
})
</script>

<template>
  <div class="stage-wrap">
    <div ref="stage" class="stage" data-testid="stage">
      <img v-if="image" class="slide" :src="image" :alt="`Slide ${editor.index + 1}`" data-testid="stage-img" />
      <div v-else class="placeholder mono">{{ editor.currentId || `page ${editor.index + 1}` }} · rendering…</div>
      <slot name="overlay" />
    </div>
    <PlayerBar />
  </div>
</template>

<style scoped>
.stage-wrap {
  display: grid;
  gap: var(--space-2);
  justify-items: center;
}
.stage {
  position: relative;
  display: grid;
  place-items: center;
  width: min(100%, calc(var(--stage-h, 50vh) * var(--deck-ar-n, 1.7778)));
  aspect-ratio: var(--deck-ar, 16 / 9);
  overflow: hidden;
  background: var(--raised);
  border-radius: 8px;
  box-shadow: 0 10px 30px rgb(0 0 0 / 35%);
}
.slide {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.placeholder {
  font-size: var(--text-sm);
  color: var(--dim);
}
.stage-wrap :deep(.player-bar),
.stage-wrap > :last-child {
  width: min(100%, calc(var(--stage-h, 50vh) * var(--deck-ar-n, 1.7778)));
}
.stage :deep(.ss-morph) {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: none;
  overflow: hidden;
  pointer-events: none;
  background: var(--raised);
}
.stage :deep(.ss-morph.ss-on) {
  display: block;
}
.stage :deep(.ss-morph img) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  will-change: opacity, transform, clip-path;
}
</style>
