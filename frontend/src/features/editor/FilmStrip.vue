<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()
const list = ref<HTMLElement | null>(null)

const STATUS_LABEL: Record<string, string> = {
  ready: 'ready',
  warning: 'check',
  error: 'error',
  empty: 'no narration',
}

watch(
  () => editor.index,
  async (i) => {
    await nextTick()
    list.value
      ?.querySelector<HTMLElement>(`[data-index="${i}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  },
)
</script>

<template>
  <nav class="strip" aria-label="Slides">
    <ol ref="list" class="list">
      <li v-for="(page, i) in editor.pages" :key="`${i}-${page.slide_id}`">
        <button
          class="thumb"
          :class="{ active: i === editor.index, [page.status]: true }"
          type="button"
          :data-index="i"
          :data-testid="`thumb-${i}`"
          :aria-current="i === editor.index ? 'true' : undefined"
          :aria-label="`Slide ${i + 1}${page.slide_id ? ' · ' + page.slide_id : ''} · ${STATUS_LABEL[page.status]}`"
          @click="editor.go(i)"
        >
          <img v-if="editor.images[i]" :src="editor.images[i] as string" alt="" loading="lazy" />
          <span v-else class="fallback mono">{{ page.slide_id || `page ${i + 1}` }}</span>
          <span class="num mono">{{ i + 1 }}</span>
          <span v-if="page.status !== 'ready'" class="badge" :class="page.status">
            <AppIcon :name="page.status === 'error' ? 'error' : page.status === 'warning' ? 'warn' : 'hourglass'" :size="11" />
            {{ STATUS_LABEL[page.status] }}
          </span>
          <span
            v-if="page.audio.speech > page.audio.cached"
            class="audio"
            :title="`${page.audio.speech - page.audio.cached} clip(s) without audio yet`"
            :data-testid="`thumb-audio-${i}`"
          >
            <AppIcon name="wave" :size="11" />
          </span>
        </button>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.strip {
  height: 100%;
  overflow-y: auto;
  padding: var(--space-2) var(--space-3) var(--space-4);
}
.list {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.thumb {
  position: relative;
  display: grid;
  place-items: center;
  width: 100%;
  aspect-ratio: var(--deck-ar, 16 / 9);
  padding: 0;
  overflow: hidden;
  background: var(--raised);
  border: 1px solid var(--line);
  border-radius: 8px;
  cursor: pointer;
  transition:
    border-color var(--fast),
    transform var(--fast);
}
.thumb:hover {
  border-color: var(--accent-deep);
}
.thumb.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.fallback {
  padding: var(--space-2);
  font-size: 10px;
  color: var(--dim);
  word-break: break-all;
}
.num,
.badge,
.audio {
  position: absolute;
  padding: 0 5px;
  border-radius: 4px;
  background: rgb(14 17 22 / 85%);
  font-size: 10px;
  line-height: 16px;
}
.num {
  bottom: 4px;
  left: 4px;
  color: var(--dim);
  font-weight: 600;
}
.badge {
  top: 4px;
  right: 4px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.badge.error {
  color: var(--err);
}
.badge.warning {
  color: var(--warn);
}
.badge.empty {
  color: var(--dim);
}
.audio {
  bottom: 4px;
  right: 4px;
  display: inline-grid;
  place-items: center;
  color: var(--warn);
}
</style>
