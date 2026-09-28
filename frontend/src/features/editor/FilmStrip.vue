<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useEditorStore } from '@/stores/editor'
import { useReviewStore, type Badge } from '@/stores/review'

const editor = useEditorStore()
const review = useReviewStore()
const list = ref<HTMLElement | null>(null)

const STATUS_LABEL: Record<string, string> = {
  ready: 'ready',
  warning: 'check',
  error: 'error',
  empty: 'no narration',
}
const REVIEW_LABEL: Record<Badge, string> = {
  'your-turn': 'your turn',
  'agent-turn': 'agent',
  closed: 'accepted',
  unfiled: 'changed',
}
const REVIEW_TIP: Record<Badge, string> = {
  'your-turn': 'A conversation here is waiting for you',
  'agent-turn': 'Waiting for the agent',
  closed: 'Accepted — not yet cleared',
  unfiled: 'Changed without a conversation',
}

const items = computed(() => review.strip)

function status(index: number): string {
  return editor.pages[index]?.status ?? 'ready'
}
function statusIcon(index: number): 'error' | 'warn' | 'hourglass' {
  const s = status(index)
  return s === 'error' ? 'error' : s === 'warning' ? 'warn' : 'hourglass'
}
function missingAudio(index: number): number {
  const audio = editor.pages[index]?.audio
  return audio ? audio.speech - audio.cached : 0
}
function dimmed(slideId: string): boolean {
  return review.scope !== null && !review.scope.has(slideId)
}
function moved(slideId: string): number | null {
  const c = review.changes.get(slideId)
  return c?.moved ? (c.base_index ?? -1) : null
}
function openPage(index: number, slideId: string): void {
  review.leaveFilterFor(slideId)
  review.leaveRemoved()
  editor.go(index)
}
function openRemoved(slideId: string): void {
  review.leaveFilterFor(slideId)
  review.viewRemoved(slideId)
}

// keep the slide being shown in view: a page, or a removed slide shown from the base
watch(
  () => [editor.index, review.viewingRemoved] as const,
  async ([i, removed]) => {
    await nextTick()
    const selector = removed === null ? `[data-index="${i}"]` : `[data-removed="${CSS.escape(removed)}"]`
    list.value?.querySelector<HTMLElement>(selector)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  },
)
</script>

<template>
  <nav class="strip" aria-label="Slides">
    <ol ref="list" class="list">
      <li v-for="item in items" :key="item.kind === 'page' ? `p${item.index}-${item.slideId}` : `r-${item.slideId}`">
        <button
          v-if="item.kind === 'page'"
          class="thumb"
          :class="{
            active: item.index === editor.index && !review.viewingRemoved,
            dimmed: dimmed(item.slideId),
          }"
          type="button"
          :data-index="item.index"
          :data-testid="`thumb-${item.index}`"
          :aria-current="item.index === editor.index ? 'true' : undefined"
          :aria-label="`Slide ${item.index + 1}${item.slideId ? ' · ' + item.slideId : ''} · ${STATUS_LABEL[status(item.index)]}`"
          @click="openPage(item.index, item.slideId)"
        >
          <img v-if="editor.images[item.index]" :src="editor.images[item.index] as string" alt="" loading="lazy" />
          <span v-else class="fallback mono">{{ item.slideId || `page ${item.index + 1}` }}</span>
          <span class="num mono">{{ item.index + 1 }}</span>
          <span v-if="status(item.index) !== 'ready'" class="badge" :class="status(item.index)">
            <AppIcon :name="statusIcon(item.index)" :size="11" />
            {{ STATUS_LABEL[status(item.index)] }}
          </span>
          <span
            v-if="missingAudio(item.index) > 0"
            class="audio"
            :title="`${missingAudio(item.index)} clip(s) without audio yet`"
            :data-testid="`thumb-audio-${item.index}`"
          >
            <AppIcon name="wave" :size="11" />
          </span>
          <span
            v-if="review.badge(item.slideId)"
            class="review"
            :class="review.badge(item.slideId) ?? ''"
            :title="REVIEW_TIP[review.badge(item.slideId) as Badge]"
            :data-testid="`thumb-review-${item.index}`"
          >
            {{ REVIEW_LABEL[review.badge(item.slideId) as Badge] }}
          </span>
          <span
            v-if="moved(item.slideId) !== null"
            class="moved"
            :title="moved(item.slideId)! >= 0 ? `Moved — was slide ${moved(item.slideId)! + 1}` : 'Moved'"
          >↕</span>
        </button>
        <button
          v-else
          class="thumb removed"
          :class="{ active: review.viewingRemoved === item.slideId, dimmed: dimmed(item.slideId) }"
          type="button"
          title="Removed since the review started — click to see it"
          :data-removed="item.slideId"
          :data-testid="`removed-thumb-${item.slideId}`"
          @click="openRemoved(item.slideId)"
        >
          <img v-if="review.data?.base_images[item.slideId]" :src="review.data.base_images[item.slideId]" alt="" />
          <span v-else class="fallback mono">{{ item.slideId }}</span>
          <span class="gone">removed</span>
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
    opacity var(--fast);
}
.thumb:hover {
  border-color: var(--accent-deep);
}
.thumb.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}
.thumb.dimmed {
  opacity: 0.25;
  filter: grayscale(1);
}
.thumb.removed {
  opacity: 0.55;
  border-style: dashed;
}
.thumb.removed.active {
  opacity: 0.9;
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
.audio,
.review,
.moved,
.gone {
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
.review {
  top: 4px;
  left: 4px;
  font-weight: 600;
}
.review.your-turn {
  color: var(--accent);
}
.review.agent-turn {
  color: var(--dim);
}
.review.closed {
  color: var(--ok);
}
.review.unfiled {
  color: var(--warn);
}
.moved {
  bottom: 4px;
  left: 24px;
  color: var(--warn);
  font-weight: 700;
}
.gone {
  bottom: 4px;
  left: 4px;
  color: var(--err);
  font-weight: 700;
}
</style>
