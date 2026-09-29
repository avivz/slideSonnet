<script setup lang="ts">
// The narration file changed on disk while this slide had unsaved typing.
// Neither side is lost: both are shown, and the user picks.
import AppDialog from '@/components/AppDialog.vue'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()

async function copyMine(): Promise<void> {
  const text = editor.conflict?.mine ?? ''
  try {
    await navigator.clipboard.writeText(text)
    editor.flash('Copied your text')
  } catch {
    editor.flash('Copying isn’t allowed here — select the text and copy it by hand', 'warn')
  }
}
</script>

<template>
  <AppDialog
    :open="editor.conflict !== null"
    title="The narration changed on disk while you were typing"
    wide
    @close="() => {}"
  >
    <p class="lead">
      Something else (probably the agent) changed slide
      <span class="mono">@{{ editor.conflict?.slideId }}</span> while you had unsaved typing on it.
      Nothing has been overwritten yet — choose which version to keep.
    </p>
    <p v-if="editor.conflicts.size > 1" class="lead" data-testid="conflict-more">
      {{ editor.conflicts.size - 1 }} more slide{{ editor.conflicts.size === 2 ? '' : 's' }} changed the same way —
      you'll choose for each one next.
    </p>
    <div class="versions">
      <section>
        <h3 class="section-title">Your version (not saved)</h3>
        <p class="text" dir="auto" data-testid="conflict-mine">{{ editor.conflict?.mine || '(empty)' }}</p>
      </section>
      <section>
        <h3 class="section-title">On disk now</h3>
        <p class="text" dir="auto" data-testid="conflict-theirs">{{ editor.conflict?.theirs || '(empty)' }}</p>
      </section>
    </div>
    <template #actions>
      <button class="btn quiet" type="button" data-testid="conflict-copy" @click="copyMine">Copy my text</button>
      <button class="btn" type="button" data-testid="conflict-theirs-btn" @click="editor.resolveConflict('theirs')">
        Use the file's version
      </button>
      <button class="btn primary" type="button" data-testid="conflict-keep" @click="editor.resolveConflict('mine')">
        Keep my version
      </button>
    </template>
  </AppDialog>
</template>

<style scoped>
.lead {
  margin: 0;
}
.versions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}
.versions section {
  display: grid;
  gap: var(--space-1);
  align-content: start;
  padding: var(--space-3);
  background: var(--raised);
  border-radius: var(--radius-field);
}
.text {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  white-space: pre-wrap;
  user-select: text;
}
@media (width < 640px) {
  .versions {
    grid-template-columns: 1fr;
  }
}
</style>
