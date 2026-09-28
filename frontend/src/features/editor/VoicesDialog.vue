<script setup lang="ts">
// Name voices and map each one to a concrete voice per engine. Saved in the
// narration file, so the same script narrates under any engine by name.
import { computed, ref, watch } from 'vue'

import type { EngineVoicesDTO } from '@/api/client'
import AppDialog from '@/components/AppDialog.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useEditorStore } from '@/stores/editor'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const editor = useEditorStore()

interface Row {
  id: number
  name: string
  /** The name this row was loaded with (null for a new row): tells a rename from add+delete. */
  original: string | null
  voices: Record<string, string>
}

const engines = computed(() => (editor.meta?.engines ?? []).map((e) => e.name))
const choices = ref<Record<string, EngineVoicesDTO>>({})
const rows = ref<Row[]>([])
const defaultVoice = ref('')
let nextId = 0

async function load(): Promise<void> {
  for (const engine of engines.value) {
    if (!(engine in choices.value)) {
      try {
        choices.value[engine] = await editor.client.engineVoices(engine)
      } catch {
        choices.value[engine] = { engine: engine as EngineVoicesDTO['engine'], voices: [], default: null }
      }
    }
  }
  const map = editor.snapshot?.voices.map ?? {}
  rows.value = Object.entries(map).map(([name, voices]) => ({
    id: nextId++,
    name,
    original: name,
    voices: { ...voices },
  }))
  if (rows.value.length === 0) addRow()
  defaultVoice.value = editor.snapshot?.voices.default_voice ?? ''
}

watch(
  () => props.open,
  (open) => {
    if (open) void load()
  },
)

function addRow(): void {
  const voices: Record<string, string> = {}
  for (const engine of engines.value) voices[engine] = choices.value[engine]?.default ?? ''
  rows.value.push({ id: nextId++, name: '', original: null, voices })
}
function removeRow(id: number): void {
  rows.value = rows.value.filter((r) => r.id !== id)
}

const names = computed(() => rows.value.map((r) => r.name.trim()).filter(Boolean))
const renames = computed(() => {
  const out: Record<string, string> = {}
  for (const r of rows.value) {
    const name = r.name.trim()
    if (r.original && name && r.original !== name) out[r.original] = name
  }
  return out
})
const defaultOptions = computed(() => {
  // a renamed default follows its row
  const current = renames.value[defaultVoice.value] ?? defaultVoice.value
  return { current, names: names.value }
})

async function save(): Promise<void> {
  const voices: Record<string, Record<string, string>> = {}
  for (const r of rows.value) {
    const name = r.name.trim()
    if (!name) continue
    voices[name] = Object.fromEntries(
      Object.entries(r.voices)
        .map(([engine, v]) => [engine, v.trim()])
        .filter(([, v]) => v !== ''),
    )
  }
  const chosen = defaultOptions.value.current
  const ok = await editor.command({
    type: 'edit_voices',
    expected_revision: '',
    voices,
    default_voice: chosen && names.value.includes(chosen) ? chosen : null,
    renames: renames.value,
  })
  if (ok) {
    editor.flash('Voices saved', 'ok')
    emit('close')
  }
}
</script>

<template>
  <AppDialog :open="open" title="Voices" wide @close="emit('close')">
    <p class="hint">
      Name a voice, then map it to a concrete voice per engine: a Kokoro voice (e.g. am_michael), an
      Inworld voice name, or a Qwen3 .pt file relative to the deck. Leave an engine blank to use its
      own default. Saved in the narration file, so the deck narrates under any engine.
    </p>
    <table class="grid" data-testid="voices-table">
      <thead>
        <tr>
          <th class="label">name</th>
          <th v-for="e in engines" :key="e" class="label">{{ e }}</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.id">
          <td>
            <input
              v-model="row.name" class="field mono" placeholder="name" aria-label="Voice name"
              :data-testid="`voice-name-${row.id}`"
            />
          </td>
          <td v-for="e in engines" :key="e">
            <input
              v-model="row.voices[e]"
              class="field mono"
              :placeholder="choices[e]?.default ?? e"
              :aria-label="`${e} voice`"
              :list="choices[e]?.voices.length ? `voices-${e}` : undefined"
              :data-testid="`voice-${e}-${row.id}`"
            />
          </td>
          <td>
            <button
              class="icon-btn" type="button" title="Remove this voice" aria-label="Remove this voice"
              @click="removeRow(row.id)"
            >
              <AppIcon name="trash" :size="15" />
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <datalist v-for="e in engines" :id="`voices-${e}`" :key="e">
      <option v-for="v in choices[e]?.voices ?? []" :key="v" :value="v" />
    </datalist>
    <div class="row">
      <button class="btn quiet" type="button" data-testid="voice-add" @click="addRow">
        <AppIcon name="plus" :size="16" /> Add voice
      </button>
      <span class="spacer"></span>
      <label class="default">
        <span class="label">Default voice</span>
        <select v-model="defaultVoice" class="field" data-testid="voice-default">
          <option value="">(engine default)</option>
          <option v-for="n in rows.filter((r) => r.name.trim())" :key="n.id" :value="n.original ?? n.name.trim()">
            {{ n.name.trim() }}
          </option>
        </select>
      </label>
    </div>
    <template #actions>
      <button class="btn quiet" type="button" @click="emit('close')">Cancel</button>
      <button class="btn primary" type="button" data-testid="voice-save" @click="save">Save</button>
    </template>
  </AppDialog>
</template>

<style scoped>
.hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--dim);
  line-height: 1.5;
}
.grid {
  width: 100%;
  border-collapse: separate;
  border-spacing: var(--space-1);
}
.grid th {
  text-align: left;
  font-weight: 400;
}
.grid .field {
  width: 100%;
}
.row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
}
.spacer {
  flex: 1;
}
.default {
  display: grid;
  gap: 2px;
}
</style>
