<script setup lang="ts">
import { computed, ref } from 'vue'

import AppDialog from '@/components/AppDialog.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()
const attaching = ref<string | null>(null)
const deleting = ref<string | null>(null)
const target = ref('')

const orphans = computed(() =>
  (editor.snapshot?.orphans ?? []).map((id) => {
    const block = editor.snapshot?.narration[id]
    const text = (block?.segments ?? [])
      .filter((s) => s.kind === 'speech')
      .map((s) => (s.kind === 'speech' ? s.text : ''))
      .join(' ')
      .trim()
    return { id, text: text || '(pauses only)' }
  }),
)
const emptySlides = computed(() =>
  (editor.snapshot?.pages ?? [])
    .map((p) => p.slide_id)
    .filter((id) => id && !(editor.snapshot?.narration[id]?.segments.length ?? 0)),
)

async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    editor.flash('Copied the narration text')
  } catch {
    editor.flash('Copying isn’t allowed here — select the text and copy it by hand', 'warn')
  }
}
async function appendHere(id: string): Promise<void> {
  const here = editor.currentId
  if (await editor.command({ type: 'append_orphan', expected_revision: '', orphan_id: id, target_id: here })) {
    editor.flash(`Appended @${id} to @${here}`, 'ok')
  }
}
function openAttach(id: string): void {
  if (emptySlides.value.length === 0) {
    editor.flash('No slide without narration to attach to', 'warn')
    return
  }
  target.value = emptySlides.value[0] ?? ''
  attaching.value = id
}
async function attach(): Promise<void> {
  const id = attaching.value
  attaching.value = null
  if (
    id &&
    (await editor.command({ type: 'attach_orphan', expected_revision: '', orphan_id: id, target_id: target.value }))
  ) {
    editor.flash(`Narration attached to @${target.value}`, 'ok')
  }
}
async function remove(): Promise<void> {
  const id = deleting.value
  deleting.value = null
  if (id && (await editor.command({ type: 'delete_orphan', expected_revision: '', orphan_id: id }))) {
    editor.flash(`Deleted the narration @${id}`)
  }
}
</script>

<template>
  <section v-if="orphans.length" class="tray" data-testid="orphan-tray">
    <h3 class="title"><AppIcon name="unlink" :size="16" /> Unattached narration</h3>
    <p class="hint">These slides are gone from the PDF — fold the text into a slide, or keep it here.</p>
    <article v-for="o in orphans" :key="o.id" class="orphan" :data-testid="`orphan-${o.id}`">
      <header>
        <span class="id mono">@{{ o.id }}</span>
        <span class="spacer"></span>
        <button class="icon-btn" type="button" title="Copy the text" aria-label="Copy the text" @click="copy(o.text)">
          <AppIcon name="copy" :size="15" />
        </button>
        <button
          class="icon-btn"
          type="button"
          title="Delete this narration"
          aria-label="Delete this narration"
          :data-testid="`orphan-delete-${o.id}`"
          @click="deleting = o.id"
        >
          <AppIcon name="trash" :size="15" />
        </button>
      </header>
      <p class="text" dir="auto">{{ o.text }}</p>
      <footer>
        <button
          class="btn quiet"
          type="button"
          :disabled="!editor.currentId"
          :title="editor.currentId ? `Append to this slide (@${editor.currentId})` : 'Open a slide with an id first'"
          :data-testid="`orphan-append-${o.id}`"
          @click="appendHere(o.id)"
        >
          Append here
        </button>
        <button class="btn quiet" type="button" :data-testid="`orphan-attach-${o.id}`" @click="openAttach(o.id)">
          Attach to…
        </button>
      </footer>
    </article>

    <AppDialog :open="attaching !== null" :title="`Attach @${attaching} to which slide?`" @close="attaching = null">
      <select v-model="target" class="field" aria-label="Slide to attach to" data-testid="attach-target" autofocus>
        <option v-for="id in emptySlides" :key="id" :value="id">{{ id }}</option>
      </select>
      <template #actions>
        <button class="btn quiet" type="button" @click="attaching = null">Cancel</button>
        <button class="btn primary" type="button" data-testid="attach-confirm" @click="attach">Attach</button>
      </template>
    </AppDialog>
    <AppDialog :open="deleting !== null" title="Delete this narration?" @close="deleting = null">
      <p>
        This removes the text of <span class="mono">@{{ deleting }}</span> from the narration file.
      </p>
      <template #actions>
        <button class="btn quiet" type="button" @click="deleting = null">Cancel</button>
        <button class="btn danger" type="button" data-testid="delete-confirm" @click="remove">Delete</button>
      </template>
    </AppDialog>
  </section>
</template>

<style scoped>
.tray {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--warn-fill);
  border: 1px solid rgb(255 200 87 / 32%);
  border-left: 3px solid var(--warn);
  border-radius: var(--radius-card);
}
.title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  font-size: var(--text-sm);
  color: var(--warn);
}
.hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--dim);
}
.orphan {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-2);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-field);
}
.orphan header,
.orphan footer {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.id {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--warn);
}
.spacer {
  flex: 1;
}
.text {
  margin: 0;
  font-size: var(--text-sm);
  white-space: pre-wrap;
  user-select: text;
}
</style>
