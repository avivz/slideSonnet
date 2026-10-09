<script setup lang="ts">
// The whole deck's narration as one script: each slide a small heading, its
// lines as plain running text, its pauses as small inline marks. It edits the
// same per-slide drafts as the slide view (so saving, conflicts and autosave
// are unchanged); clicking into a slide's words shows that slide above.
import { nextTick, ref, watch } from 'vue'

import { useEditorStore } from '@/stores/editor'
import { useGenerationStore, type ClipFailure } from '@/stores/generation'
import { usePlayerStore } from '@/stores/player'
import { useReviewStore } from '@/stores/review'

import LineFailure from './LineFailure.vue'
import NarrationDiff from './NarrationDiff.vue'
import { joinLines, newPause, newSpeech, speechIndexes, splitLine, written, type EditSeg } from './narration'
import { useEditingFocus } from './useEditingFocus'

const editor = useEditorStore()
const review = useReviewStore()
const player = usePlayerStore()
const generation = useGenerationStore()

/** A spoken line split into what's been said (up to and including the current word) and the rest; null when it isn't playing. */
function spokenParts(slideId: string, seg: EditSeg): [string, string, string] | null {
  const w = player.spoken
  if (w === null || w.slideId !== slideId) return null
  const block = editor.draftFor(slideId)
  if (!block || speechIndexes(block).get(seg.key) !== w.index) return null
  return ['', seg.text.slice(0, w.end), seg.text.slice(w.end)]
}
const root = ref<HTMLElement | null>(null)
// typing in a line holds playback's cursor and auto-generate off it, as in the slide view
// a click in a line's words while playing plays on from there
const { onFocusIn, onFocusOut, onClick } = useEditingFocus(root, (el) => {
  if (el.tagName !== 'TEXTAREA') return null
  const key = el.closest<HTMLElement>('[data-speech]')?.dataset.speech
  const at = key?.lastIndexOf('#') ?? -1
  return key && at > 0 ? { slideId: key.slice(0, at), index: Number(key.slice(at + 1)) } : null
})

/** Show slide `index` above; a slide outside the chosen conversation shows every slide again. */
function enter(index: number): void {
  review.leaveFilterFor(editor.pages[index]?.slide_id ?? '')
  if (index !== editor.index) {
    review.leaveRemoved()
    editor.go(index)
  }
}
/** Once drawn, put the cursor in `seg`'s line (at `at`) or in its pause's length. */
async function focusSeg(seg: EditSeg, at = 0): Promise<void> {
  await nextTick()
  const el = [...(root.value?.querySelectorAll<HTMLElement>('[data-seg]') ?? [])].find((e) => e.dataset.seg === seg.key)
  el?.focus()
  if (el instanceof HTMLTextAreaElement) el.setSelectionRange(at, at)
  else if (el instanceof HTMLInputElement) el.select()
}
/** A new, empty line at `j` of the slide, with the cursor in it (it's written once it has words). */
function addLine(index: number, slideId: string, j?: number): void {
  const middle = editor.draftFor(slideId)?.middle
  if (!middle) return
  enter(index)
  const seg = newSpeech()
  middle.splice(j ?? middle.length, 0, seg)
  void focusSeg(seg)
}
/** Where the words of line `j` and its pauses end: what's added "after" it goes here. */
function afterLine(slideId: string, j: number): number {
  const middle = editor.draftFor(slideId)?.middle ?? []
  let k = j + 1
  while (middle[k]?.kind === 'pause') k++
  return k
}
/**
 * Typing across a line's edges, as in a document: Enter splits the line at the
 * cursor (Shift+Enter is a line break within it); Backspace at its start takes
 * the pause before it, or joins it onto the line before; Delete at its end
 * does the same with what follows.
 */
function onKey(slideId: string, seg: EditSeg, event: KeyboardEvent): void {
  const box = event.target as HTMLTextAreaElement
  const block = editor.draftFor(slideId)
  const j = block?.middle.indexOf(seg) ?? -1
  if (!block || j < 0 || event.isComposing || box.selectionStart !== box.selectionEnd) return
  const at = box.selectionStart
  if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault()
    seg.text = box.value
    const tail = splitLine(block, j, at)
    if (tail) void focusSeg(tail)
  } else if (event.key === 'Backspace' && at === 0 && j > 0) {
    event.preventDefault()
    const before = block.middle[j - 1] as EditSeg
    if (before.kind === 'pause') block.middle.splice(j - 1, 1)
    else {
      seg.text = box.value
      const join = joinLines(block, j - 1)
      if (join !== null) void focusSeg(before, join)
    }
  } else if (event.key === 'Delete' && at === box.value.length && j < block.middle.length - 1) {
    event.preventDefault()
    if (block.middle[j + 1]?.kind === 'pause') block.middle.splice(j + 1, 1)
    else {
      seg.text = box.value
      const join = joinLines(block, j)
      if (join !== null) void focusSeg(seg, join)
    }
  } else return
  editor.touch(slideId, { immediate: true })
}
function onText(slideId: string, seg: EditSeg, event: Event): void {
  seg.text = (event.target as HTMLTextAreaElement).value
  editor.touch(slideId)
}
/**
 * Leaving a line with no words takes it away, as deleting it in the slide view
 * would (it was never written, so nothing more is saved). Not when the whole
 * window lost focus: the cursor is still in the line, to come back to.
 */
function onLeave(slideId: string, seg: EditSeg, event: FocusEvent): void {
  if (written(seg) || document.activeElement === event.target) return
  const middle = editor.draftFor(slideId)?.middle ?? []
  const j = middle.indexOf(seg)
  if (j >= 0) middle.splice(j, 1)
}
/** A pause's new length; cleared or set to nothing, the pause goes away. */
function onPause(slideId: string, seg: EditSeg, event: Event): void {
  seg.seconds = Math.max(0, Number((event.target as HTMLInputElement).value) || 0)
  const middle = editor.draftFor(slideId)?.middle ?? []
  if (seg.seconds === 0 && middle.includes(seg)) middle.splice(middle.indexOf(seg), 1)
  editor.touch(slideId, { immediate: true })
}
/** A pause after line `j` (after any it has already), with the cursor in its length. */
function addPause(index: number, slideId: string, j: number): void {
  const middle = editor.draftFor(slideId)?.middle
  if (!middle) return
  enter(index)
  const seg = newPause()
  middle.splice(afterLine(slideId, j), 0, seg)
  editor.touch(slideId, { immediate: true })
  void focusSeg(seg)
}
/**
 * A slide's lines, each carrying the pauses that follow it (drawn right after
 * its last word, not on a row of their own); a pause before any line stands alone.
 */
type Row =
  | { kind: 'line'; seg: EditSeg; j: number; pauses: { seg: EditSeg; j: number }[] }
  | { kind: 'pause'; seg: EditSeg; j: number }
function rows(slideId: string): Row[] {
  const out: Row[] = []
  const middle = editor.draftFor(slideId)?.middle ?? []
  middle.forEach((seg, j) => {
    const last = out[out.length - 1]
    if (seg.kind === 'speech') out.push({ kind: 'line', seg, j, pauses: [] })
    else if (last?.kind === 'line') last.pauses.push({ seg, j })
    else out.push({ kind: 'pause', seg, j })
  })
  return out
}
/** Under review: how this slide's narration changed since the review began. */
function diffOf(slideId: string): string[][] | null {
  return review.diffFor(slideId)
}
function dimmed(slideId: string): boolean {
  return review.scope !== null && !review.scope.has(slideId)
}
function spoken(slideId: string): boolean {
  return (editor.draftFor(slideId)?.middle ?? []).some((s) => s.kind === 'speech')
}

/** Scroll `el` into view (to the middle while playing) — never away from a line being typed in. */
function reveal(el: HTMLElement | null | undefined, block: 'center' | 'nearest'): void {
  if (!el || root.value?.contains(document.activeElement)) return
  el.scrollIntoView?.({ block, behavior: 'smooth' }) // absent in jsdom
}
// follow the slide shown above (arrows, filmstrip, playback)
watch(
  () => editor.index,
  async (i) => {
    await nextTick()
    const section = root.value?.querySelector<HTMLElement>(`[data-index="${i}"]`)
    reveal(section, player.frame.playing ? 'center' : 'nearest')
  },
)
// while playing, keep the line being spoken in the middle, not at the bottom edge
watch(
  () => (player.spoken ? `${player.spoken.slideId}#${player.spoken.index}` : null),
  async (line) => {
    if (line === null) return
    await nextTick()
    const lines = root.value?.querySelectorAll<HTMLElement>('[data-speech]') ?? []
    reveal([...lines].find((el) => el.dataset.speech === line), 'center')
  },
)
function speechIndex(slideId: string, seg: EditSeg): number | undefined {
  const block = editor.draftFor(slideId)
  return block ? speechIndexes(block).get(seg.key) : undefined
}
function speechKey(slideId: string, seg: EditSeg): string | undefined {
  const index = speechIndex(slideId, seg)
  return index === undefined ? undefined : `${slideId}#${index}`
}
function failureOf(slideId: string, seg: EditSeg): ClipFailure | null {
  return generation.failureFor(slideId, speechIndex(slideId, seg) ?? -1)
}
function retry(slideId: string, seg: EditSeg): void {
  const index = speechIndex(slideId, seg)
  if (index !== undefined) void generation.enqueue([{ slide_id: slideId, speech_index: index }])
}
</script>

<template>
  <section ref="root" class="script" data-testid="script-view" @focusin="onFocusIn" @focusout="onFocusOut" @click="onClick">
    <article
      v-for="(page, i) in editor.pages"
      :key="`${i}-${page.slide_id}`"
      class="slide"
      :class="{ current: i === editor.index && !review.viewingRemoved, dimmed: dimmed(page.slide_id) }"
      :data-index="i"
      :data-testid="`script-slide-${page.slide_id || i}`"
      @click="enter(i)"
    >
      <button class="head" type="button" :title="`Show slide ${i + 1}`" @click="enter(i)">
        <span class="num mono">{{ i + 1 }}</span>
        <span class="id mono">{{ page.slide_id ? `@${page.slide_id}` : 'no slide id' }}</span>
      </button>
      <div v-if="page.slide_id" class="body">
        <template v-for="row in rows(page.slide_id)" :key="row.seg.key">
          <div
            v-if="row.kind === 'line'"
            class="line-wrap"
            :data-speech="speechKey(page.slide_id, row.seg)"
            :data-testid="`script-line-${page.slide_id}-${row.j}`"
          >
            <!-- the same text, laid out beneath the box: it sizes the line, so
                 the box on top wraps exactly as it does; it marks the word being
                 spoken, and carries the pauses right after the last word -->
            <div class="mirror" dir="auto">
              <template v-if="spokenParts(page.slide_id, row.seg)">
                <mark aria-hidden="true">{{ spokenParts(page.slide_id, row.seg)?.[1] }}</mark>
                <span aria-hidden="true">{{ spokenParts(page.slide_id, row.seg)?.[2] }}</span>
              </template>
              <span v-else aria-hidden="true">{{ row.seg.text }}</span>
              <!-- a trailing newline still takes its row -->
              <span aria-hidden="true">{{ '\u200b' }}</span>
              <span class="tail">
                <label v-for="p in row.pauses" :key="p.seg.key" class="pause" title="Pause, in seconds — clear it to remove it">
                  <span aria-hidden="true">⏸</span>
                  <input
                    class="secs"
                    type="number"
                    min="0"
                    step="0.1"
                    :aria-label="`Slide ${i + 1}, pause in seconds`"
                    :value="p.seg.seconds.toFixed(1)"
                    :data-seg="p.seg.key"
                    :data-testid="`script-pause-${page.slide_id}-${p.j}`"
                    @focus="enter(i)"
                    @change="onPause(page.slide_id, p.seg, $event)"
                  />
                </label>
                <!-- more after this line: out of the way until it's pointed at or typed in -->
                <button
                  class="more" type="button" title="Add a pause after this line"
                  :aria-label="`Slide ${i + 1}, add a pause after this line`"
                  :data-testid="`script-add-pause-${page.slide_id}-${row.j}`"
                  @click.stop="addPause(i, page.slide_id, row.j)"
                >
                  + pause
                </button>
                <button
                  class="more" type="button" title="Add a line after this one (or press Enter at its end)"
                  :aria-label="`Slide ${i + 1}, add a line after this one`"
                  :data-testid="`script-add-line-${page.slide_id}-${row.j}`"
                  @click.stop="addLine(i, page.slide_id, afterLine(page.slide_id, row.j))"
                >
                  + line
                </button>
              </span>
            </div>
            <textarea
              class="line"
              dir="auto"
              rows="1"
              placeholder="Spoken words…"
              :aria-label="`Slide ${i + 1}, spoken words`"
              :value="row.seg.text"
              :data-seg="row.seg.key"
              :data-testid="`script-text-${page.slide_id}-${row.j}`"
              @focus="enter(i)"
              @keydown="onKey(page.slide_id, row.seg, $event)"
              @input="onText(page.slide_id, row.seg, $event)"
              @blur="onLeave(page.slide_id, row.seg, $event)"
            ></textarea>
          </div>
          <label v-else class="pause" title="Pause, in seconds — clear it to remove it">
            <span aria-hidden="true">⏸</span>
            <input
              class="secs"
              type="number"
              min="0"
              step="0.1"
              :aria-label="`Slide ${i + 1}, pause in seconds`"
              :value="row.seg.seconds.toFixed(1)"
              :data-seg="row.seg.key"
              :data-testid="`script-pause-${page.slide_id}-${row.j}`"
              @focus="enter(i)"
              @change="onPause(page.slide_id, row.seg, $event)"
            />
          </label>
          <LineFailure
            v-if="row.kind === 'line' && failureOf(page.slide_id, row.seg)"
            class="failure" :failure="failureOf(page.slide_id, row.seg)!" @retry="retry(page.slide_id, row.seg)"
          />
        </template>
        <p v-if="!spoken(page.slide_id)" class="none">
          No narration yet ·
          <button
            class="add" type="button" :data-testid="`script-add-${page.slide_id}`"
            @click="addLine(i, page.slide_id)"
          >
            + Add a line
          </button>
        </p>
        <NarrationDiff
          v-if="diffOf(page.slide_id)"
          class="changes"
          title="Changed:"
          :words="diffOf(page.slide_id) ?? []"
          :data-testid="`script-diff-${page.slide_id}`"
        />
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
.line-wrap {
  position: relative;
  flex: 1 1 100%;
  min-width: 0;
}
/* The mirror and the box over it must lay the text out identically. */
.line,
.mirror {
  box-sizing: border-box;
  margin: 0;
  padding: 2px 0;
  border: 0;
  font-family: var(--font-mono);
  font-size: 15px;
  line-height: 1.45;
  letter-spacing: normal;
  white-space: pre-wrap;
  overflow-wrap: break-word;
}
.mirror {
  position: relative;
  color: transparent;
  pointer-events: none;
}
.mirror mark {
  background: rgb(88 166 255 / 32%);
  border-radius: 3px;
  color: transparent;
}
.tail {
  position: relative;
  z-index: 1;
  display: inline-flex;
  gap: var(--space-1);
  margin-left: var(--space-2);
  white-space: nowrap;
  pointer-events: auto;
  vertical-align: baseline;
}
.line {
  position: absolute;
  inset: 0;
  z-index: 0;
  display: block;
  width: 100%;
  height: 100%;
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
/* adding stays out of the way until the line is pointed at, or typed in
   (then Shift+Tab reaches it) */
.more {
  padding: 0 2px;
  background: transparent;
  border: 0;
  border-radius: 4px;
  color: var(--dim);
  font-size: var(--text-xs);
  cursor: pointer;
  opacity: 0;
}
.more:hover,
.more:focus-visible {
  color: var(--accent);
}
.line-wrap:hover .more,
.line-wrap:focus-within .more {
  opacity: 1;
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
.failure {
  flex: 1 1 100%;
}
.changes {
  flex: 1 1 100%;
  margin: 2px 0 var(--space-1);
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-sm);
  line-height: 1.5;
}
.add {
  padding: 0;
  background: transparent;
  border: 0;
  color: var(--accent);
  font-size: inherit;
  font-style: normal;
  cursor: pointer;
}
.add:hover {
  text-decoration: underline;
}
.none {
  margin: 0;
  padding: 2px 0;
  color: var(--dim);
  font-size: var(--text-sm);
  font-style: italic;
}
</style>
