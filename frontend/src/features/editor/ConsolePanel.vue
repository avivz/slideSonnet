<script setup lang="ts">
// The console: deck-wide tools on top (engine, voices, generate, export), then
// what concerns the open slide (checks, its audio, unattached narration).
import { computed, ref } from 'vue'

import { ApiError, type Backend, type JobDTO } from '@/api/client'
import { waitForJob } from '@/api/jobs'
import AppIcon from '@/components/AppIcon.vue'
import { formatLength } from '@/features/playback/cues'
import { useConfirm } from '@/stores/confirm'
import { useEditorStore } from '@/stores/editor'
import { useGenerationStore } from '@/stores/generation'
import { usePlayerStore } from '@/stores/player'

import { engineLabel } from './engines'
import OrphanTray from './OrphanTray.vue'

interface ExportDone { video: string; duration: number; draft: boolean; fast?: boolean }

// `orphans`: show the unattached narration an error in the deck checks is about
const emit = defineEmits<{ voices: []; orphans: [] }>()

const editor = useEditorStore()
const generation = useGenerationStore()
const player = usePlayerStore()
const exporting = ref<JobDTO | null>(null)
/** The last export's video: shown until dismissed (or the next export). */
const exported = ref<ExportDone | null>(null)
/** Export a quick, lower-quality video (720p, plain cuts) instead of the full one. */
const quick = ref(false)
/** "Video", "Draft video", "Quick video", "Quick draft video". */
const exportedLabel = computed(() => {
  const e = exported.value
  const text = [e?.fast ? 'quick' : '', e?.draft ? 'draft' : '', 'video'].filter(Boolean).join(' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
})

const engines = computed(() => {
  const snap = editor.snapshot
  if (!snap) return []
  return snap.engines.filter((e) => e.installed || e.name === editor.activeEngine)
})
const orphanIds = computed(() => new Set(editor.snapshot?.orphans ?? []))
const missing = computed(() => editor.snapshot?.missing_audio ?? 0)
const slideAudio = computed(() => editor.page?.audio ?? { speech: 0, cached: 0 })

const gen = computed(() => generation.status)
const genVisible = computed(() => (gen.value?.total ?? 0) > 0 && (gen.value?.running || (gen.value?.done ?? 0) < (gen.value?.total ?? 0)))
const genText = computed(() => {
  const s = gen.value
  if (!s) return ''
  const parts = [`Generating ${Math.min(s.done + 1, s.total)}/${s.total}`]
  if (s.running) {
    let detail = `${s.running.slide_id}`
    detail += ` · ${Math.round(s.running.elapsed)}s`
    if (s.running.estimate) detail += ` of ~${Math.round(s.running.estimate)}s`
    parts.push(detail)
  }
  return parts.join('  ·  ')
})
const exportText = computed(() => {
  const job = exporting.value
  if (!job) return ''
  const p = job.progress
  return p.phase ? `Exporting · ${p.phase} ${p.done}/${p.total}` : 'Exporting…'
})

async function changeEngine(name: string): Promise<void> {
  player.stop() // the loaded preview was the old engine's
  generation.autoBuild = false // the new engine's audio is all missing: don't regenerate unasked
  await editor.setEngine(name as Backend)
  await generation.refresh()
  editor.flash(`Now using ${engineLabel(name)} for previews and export (this session only)`)
  if (editor.snapshot && !editor.snapshot.engine_warm && editor.token) {
    // load a heavy model now, so the first play doesn't stall on it
    void editor.client.startJob(editor.token, { kind: 'warm', engine: name as Backend }).catch(() => undefined)
  }
}

async function generateMissing(): Promise<void> {
  if (missing.value === 0) {
    editor.flash(`Nothing to generate — every line has ${engineLabel(editor.activeEngine)} audio`)
    return
  }
  const n = await generation.enqueue(null)
  if (n > 0) editor.flash(`Generating ${n} clip(s) with ${engineLabel(editor.activeEngine)}…`)
}

async function cancelGeneration(): Promise<void> {
  const n = await generation.cancelAll()
  editor.flash(n ? `Canceled generation (${n} clip${n === 1 ? '' : 's'})` : 'Nothing was generating')
}

async function exportVideo(): Promise<void> {
  const token = editor.token
  if (!token || exporting.value) return
  if (!(await editor.ensureSaved())) return // export what's on screen, or nothing
  let draft = false
  const blockers = await editor.client.exportBlockers(token)
  if (blockers.length) {
    draft = await useConfirm().ask({
      title: 'Not ready for the final video',
      lines: [...blockers.map((b) => `• ${b}`), 'You can still export a draft (saved as a separate .draft.mp4 file).'],
      yes: 'Export draft',
    })
    if (!draft) return
  }
  await runExport(token, draft, false)
}

async function runExport(token: string, draft: boolean, allowPaid: boolean): Promise<void> {
  try {
    const job = await editor.client.startJob(token, {
      kind: 'export', draft, fast: quick.value, engine: editor.activeEngine, allow_paid: allowPaid,
    })
    exporting.value = job
    exported.value = null
    const wait = waitForJob(editor.client, job.id, (j) => (exporting.value = j))
    const done = await wait.done
    if (done.status === 'succeeded' && done.result) {
      exported.value = done.result as unknown as ExportDone
    } else if (done.status === 'failed') {
      editor.flash(`Export failed: ${done.error?.message ?? 'unknown error'}`, 'err')
    } else {
      editor.flash('Export canceled')
    }
  } catch (e) {
    if (e instanceof ApiError && e.code === 'paid_confirmation_required' && !allowPaid) {
      exporting.value = null
      const ok = await useConfirm().ask({
        title: 'This will spend API credits',
        lines: [e.message],
        yes: 'Generate & export',
      })
      if (ok) return runExport(token, draft, true)
      return
    }
    editor.flash(e instanceof ApiError ? e.message : 'The export could not start.', 'err')
  } finally {
    exporting.value = null
  }
}

async function cancelExport(): Promise<void> {
  if (exporting.value) await editor.client.cancelJob(exporting.value.id)
}
</script>

<template>
  <aside class="console" aria-label="Console" data-testid="console">
    <section class="group">
      <h3 class="section-title">Deck</h3>
      <label class="engine">
        <span class="label">Engine</span>
        <select
          class="field mono"
          :value="editor.activeEngine ?? ''"
          data-testid="engine-select"
          title="Generate, preview and export with this engine — for this session only (not saved to the deck)"
          @change="changeEngine(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="e in engines" :key="e.name" :value="e.name">
            {{ engineLabel(e.name) }}{{ e.paid ? ' · paid' : '' }}{{ e.realtime ? '' : ' · slow' }}
          </option>
        </select>
      </label>
      <button class="btn" type="button" data-testid="edit-voices" @click="emit('voices')">
        <AppIcon name="voice" :size="16" /> Voices…
      </button>
      <label class="check" :title="generation.autoBuildAllowed ? 'Quietly generate each slide’s audio in the background after you edit it' : 'Local engines only — a paid engine would bill on every save'">
        <input
          type="checkbox"
          :checked="generation.autoBuild"
          :disabled="!generation.autoBuildAllowed"
          data-testid="auto-build"
          @change="generation.setAutoBuild(($event.target as HTMLInputElement).checked)"
        />
        Auto-generate as I edit
      </label>
      <label class="check" title="When on, playing one slide animates its in/out transitions">
        <input v-model="generation.singleSlideTransitions" type="checkbox" data-testid="single-slide-transitions" />
        Play transitions in single-slide preview
      </label>
      <button
        class="btn"
        type="button"
        :disabled="missing === 0"
        data-testid="gen-missing"
        title="Makes only the clips that don't exist yet — finished audio is left untouched"
        @click="generateMissing"
      >
        <AppIcon name="wave" :size="16" />
        {{ missing ? `Generate missing (${missing})` : 'All audio generated' }}
      </button>
      <div v-if="genVisible" class="progress" data-testid="gen-progress">
        <div class="bar"><span :style="{ width: `${gen && gen.total ? (gen.done / gen.total) * 100 : 0}%` }"></span></div>
        <button
          class="icon-btn" type="button" title="Cancel all generation" aria-label="Cancel all generation"
          data-testid="gen-cancel" @click="cancelGeneration"
        >
          <AppIcon name="close" :size="14" />
        </button>
        <p class="status mono">{{ genText }}</p>
      </div>
      <button class="btn primary" type="button" :disabled="exporting !== null" data-testid="export" @click="exportVideo">
        <AppIcon name="movie" :size="16" /> Export video
      </button>
      <label class="check" title="720p with plain cuts instead of transitions: much faster, for a quick look. Same audio and subtitles. Saved as a separate .fast.mp4 file, so your full video is kept.">
        <input v-model="quick" type="checkbox" :disabled="exporting !== null" data-testid="quick-export" />
        Quick export (lower quality, much faster)
      </label>
      <div v-if="exporting" class="progress" data-testid="export-progress">
        <div class="bar">
          <span :style="{ width: `${exporting.progress.total ? (exporting.progress.done / exporting.progress.total) * 100 : 5}%` }"></span>
        </div>
        <button class="icon-btn" type="button" title="Cancel the export" aria-label="Cancel the export" @click="cancelExport">
          <AppIcon name="close" :size="14" />
        </button>
        <p class="status mono">{{ exportText }}</p>
      </div>
      <div v-if="exported" class="result" role="status" data-testid="export-result">
        <p>
          {{ exportedLabel }} saved to
          <span class="mono">{{ exported.video }}</span> · {{ formatLength(exported.duration) }} long
        </p>
        <button
          class="icon-btn" type="button" title="Dismiss" aria-label="Dismiss" data-testid="export-result-dismiss"
          @click="exported = null"
        >
          <AppIcon name="close" :size="14" />
        </button>
      </div>
    </section>

    <section v-if="editor.deckDiagnostics.length" class="group" data-testid="deck-checks-section">
      <h3 class="section-title">Deck checks</h3>
      <ul class="checks" data-testid="deck-checks">
        <li
          v-for="d in editor.deckDiagnostics"
          :key="d.code + d.message"
          :class="d.severity === 'error' ? 'err-text' : d.severity === 'warning' ? 'warn-text' : 'dim-text'"
        >
          {{ d.message }}
          <button
            v-if="d.slide_id && orphanIds.has(d.slide_id)"
            class="link" type="button" data-testid="deck-check-orphans" @click="emit('orphans')"
          >
            Show the narration
          </button>
        </li>
      </ul>
    </section>

    <section class="group">
      <h3 class="section-title">This slide</h3>
      <ul class="checks" data-testid="checks">
        <li v-if="editor.diagnosticsHere.length === 0" class="ok-text">No issues on this slide</li>
        <li
          v-for="d in editor.diagnosticsHere"
          :key="d.code + d.message"
          :class="d.severity === 'error' ? 'err-text' : d.severity === 'warning' ? 'warn-text' : 'dim-text'"
        >
          {{ d.message }}
        </li>
      </ul>
      <p class="audio" data-testid="audio-status" :class="slideAudio.speech === 0 ? 'dim-text' : slideAudio.cached === slideAudio.speech ? 'ok-text' : 'warn-text'">
        {{ slideAudio.speech === 0 ? 'No speech on this slide' : `${slideAudio.cached} of ${slideAudio.speech} clips generated` }}
      </p>
      <OrphanTray />
    </section>
    <slot />
  </aside>
</template>

<style scoped>
.console {
  display: grid;
  align-content: start;
  gap: var(--space-5);
  height: 100%;
  overflow-y: auto;
  padding: var(--space-4);
}
.group {
  display: grid;
  gap: var(--space-2);
}
.engine {
  display: grid;
  gap: 2px;
}
.engine .field {
  width: 100%;
}
.progress {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: var(--space-1);
}
.bar {
  height: 6px;
  border-radius: var(--radius-pill);
  background: var(--raised);
  overflow: hidden;
}
.bar span {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width var(--pane);
}
.result {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: start;
  gap: var(--space-1);
  padding: var(--space-2);
  background: var(--raised);
  border: 1px solid var(--line);
  border-left: 3px solid var(--ok);
  border-radius: var(--radius-field);
  font-size: var(--text-sm);
}
.result p {
  margin: 0;
  overflow-wrap: anywhere;
}
.status {
  grid-column: 1 / -1;
  margin: 0;
  font-size: var(--text-xs);
  color: var(--dim);
}
.checks {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.4;
}
.link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--accent);
  font: inherit;
  text-decoration: underline;
  cursor: pointer;
}
.audio {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}
</style>
