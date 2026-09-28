<script setup lang="ts">
// The whole deck's narration as one script: each slide a small heading, its
// lines as plain running text, its pauses as small inline marks. It edits the
// same per-slide drafts as the slide view (so saving, conflicts and autosave
// are unchanged); clicking into a slide's words shows that slide above.
import { nextTick, ref, watch, type Directive } from 'vue'

import { useEditorStore } from '@/stores/editor'
import { useReviewStore } from '@/stores/review'

import type { EditSeg } from './narration'

const editor = useEditorStore()
const review = useReviewStore()
const root = ref<HTMLElement | null>(null)

/** A text box as tall as its text. */
const vGrow: Directive<HTMLTextAreaElement> = {
  mounted: grow,
  updated: grow,
}
function grow(el: HTMLTextAreaElement): void {
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

function enter(index: number): void {
  if (index !== editor.index) {
    review.leaveRemoved()
    editor.go(index)
  }
}
function onText(slideId: string, seg: EditSeg, event: Event): void {
  seg.text = (event.target as HTMLTextAreaElement).value
  editor.touch(slideId)
}
function onPause(slideId: string, seg: EditSeg, event: Event): void {
  seg.seconds = Math.max(0, Number((event.target as HTMLInputElement).value) || 0)
  editor.touch(slideId, { immediate: true })
}
function dimmed(slideId: string): boolean {
  return review.scope !== null && !review.scope.has(slideId)
}
function spoken(slideId: string): boolean {
  return (editor.draftFor(slideId)?.middle ?? []).some((s) => s.kind === 'speech')
}

// follow the slide shown above (arrows, filmstrip, playback) — but never pull
// the page away from a line being typed in
watch(
  () => editor.index,
  async (i) => {
    await nextTick()
    const section = root.value?.querySelector<HTMLElement>(`[data-index="${i}"]`)
    if (section && !section.contains(document.activeElement)) {
      section.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }) // absent in jsdom
    }
  },
)
</script>

<template>
  <section ref="root" class="script" data-testid="script-view">
    <article
      v-for="(page, i) in editor.pages"
      :key="`${i}-${page.slide_id}`"
      class="slide"
      :class="{ current: i === editor.index && !review.viewingRemoved, dimmed: dimmed(page.slide_id) }"
      :data-index="i"
      :data-testid="`script-slide-${page.slide_id || i}`"
    >
      <button class="head" type="button" :title="`Show slide ${i + 1}`" @click="enter(i)">
        <span class="num mono">{{ i + 1 }}</span>
        <span class="id mono">{{ page.slide_id ? `@${page.slide_id}` : 'no slide id' }}</span>
      </button>
      <div v-if="page.slide_id" class="body">
        <template v-for="(seg, j) in editor.draftFor(page.slide_id)?.middle ?? []" :key="seg.key">
          <textarea
            v-if="seg.kind === 'speech'"
            v-grow
            class="line"
            dir="auto"
            rows="1"
            placeholder="Spoken words…"
            :aria-label="`Slide ${i + 1}, spoken words`"
            :value="seg.text"
            :data-testid="`script-text-${page.slide_id}-${j}`"
            @focus="enter(i)"
            @input="onText(page.slide_id, seg, $event)"
          ></textarea>
          <label v-else class="pause" title="Pause, in seconds">
            <span aria-hidden="true">⏸</span>
            <input
              class="secs"
              type="number"
              min="0"
              step="0.1"
              :aria-label="`Slide ${i + 1}, pause in seconds`"
              :value="seg.seconds.toFixed(1)"
              :data-testid="`script-pause-${page.slide_id}-${j}`"
              @focus="enter(i)"
              @change="onPause(page.slide_id, seg, $event)"
            />
            <span>s</span>
          </label>
        </template>
        <p v-if="!spoken(page.slide_id)" class="none">No narration yet — open the slide to add a line.</p>
      </div>
    </article>
  </section>
</template>

<style scoped>
.script {
  display: grid;
  gap: var(--space-1);
}
.slide {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: var(--space-3);
  padding: var(--space-1) var(--space-2);
  border-left: 2px solid transparent;
  border-radius: 0 var(--radius-field) var(--radius-field) 0;
}
.slide.current {
  background: var(--raised);
  border-left-color: var(--accent);
}
.slide.dimmed {
  opacity: 0.4;
}
.head {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
  min-width: 0;
  padding: 3px 0 0;
  background: transparent;
  border: 0;
  color: var(--dim);
  text-align: left;
  cursor: pointer;
}
.head:hover .id {
  color: var(--accent);
}
.num {
  font-size: var(--text-xs);
}
.id {
  max-width: 100%;
  overflow: hidden;
  font-size: var(--text-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.current .id {
  color: var(--accent);
}
.body {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
  min-width: 0;
}
.line {
  flex: 1 1 100%;
  min-height: 1.45em;
  padding: 2px 0;
  resize: none;
  overflow: hidden;
  background: transparent;
  border: 0;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 15px;
  line-height: 1.45;
}
.line:focus-visible {
  box-shadow: none;
  background: rgb(0 0 0 / 15%);
}
.pause {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--dim);
  font-size: var(--text-xs);
}
.secs {
  width: 44px;
  height: 20px;
  padding: 0 2px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  color: var(--dim);
  font-size: var(--text-xs);
}
.secs:hover,
.secs:focus-visible {
  border-color: var(--line);
  color: var(--text);
}
.none {
  margin: 0;
  padding: 2px 0;
  color: var(--dim);
  font-size: var(--text-sm);
  font-style: italic;
}
</style>
